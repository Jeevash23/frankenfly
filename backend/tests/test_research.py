import json
import time
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from digitalfly.api.models import (BatchRequest, Interventions, NeuralParameters, Protocol,
    ProtocolEvent, RunConfig, Stimulus)
from digitalfly.data.research import ConnectivityGraph, graph_summary, run_detail, list_runs
from digitalfly.main import create_app
from digitalfly.neural.model import RateCircuit
from digitalfly.simulation.engines import ROOT
from digitalfly.simulation.experiment import Experiment


def test_protocol_exact_boundaries_and_repeatability(tmp_path):
    protocol = Protocol(duration_steps=30, events=[ProtocolEvent(step=10, stimulus=Stimulus(x=12,y=-8)),
        ProtocolEvent(step=20, interventions=Interventions(silence="descending"))])
    config = RunConfig(engine="toy", protocol=protocol)
    exp = Experiment(config, False)
    try:
        for _ in range(10): exp.advance()
        assert exp.config.stimulus.y == 8
        exp.advance()
        assert exp.config.stimulus.y == -8
        for _ in range(19): exp.advance()
        assert exp.status == "paused" and exp.protocol_complete and exp.t == .3
        assert exp.sample.motor == [0, 0]
        assert [(e.kind, e.step) for e in exp.events if e.payload.get("source") == "protocol"] == [("stimulus",10),("interventions",20)]
        expected = exp.sample.model_dump()
        saved = exp.export(tmp_path)
        detail = run_detail(Path(saved["path"]).name, tmp_path)
        assert detail["metrics"]["path_length_mm"] >= detail["metrics"]["displacement_mm"] > 0
        assert len(list_runs(tmp_path)) == 1 and detail["trajectory"][-1][0] == .3
        with pytest.raises(RuntimeError, match="finished"): exp.advance()
        exp.reset(config)
        for _ in range(30): exp.advance()
        assert exp.sample.model_dump() == expected
    finally: exp.close()


def test_parameters_change_actual_pipeline_and_export(tmp_path):
    exp=Experiment(RunConfig(engine="toy"),False)
    try:
        exp.set_parameters(NeuralParameters(tonic_drive=0,sensory_gain=0))
        for _ in range(30): exp.advance()
        assert exp.sample.motor == [0,0] and exp.sample.pose.x == 0
        exported=exp.export(tmp_path)
        data=json.loads((Path(exported['path'])/'metadata.json').read_text())
        assert data['neural']['bias'][4:] == [0,0]
        assert data['events'][-1]['kind'] == 'parameters'
        exp.reset(RunConfig(engine='toy'))
        for _ in range(30): exp.advance()
        assert exp.sample.pose.x > .5
    finally: exp.close()


def test_invalid_research_configs():
    with pytest.raises(ValidationError): RunConfig(engine='toy',sensor_model='vision')
    with pytest.raises(ValidationError): NeuralParameters(time_scale=0)
    with pytest.raises(ValidationError): Protocol(duration_steps=10,events=[ProtocolEvent(step=10,stimulus=Stimulus())])
    with pytest.raises(ValidationError): Protocol(events=[ProtocolEvent(step=8,stimulus=Stimulus()),ProtocolEvent(step=2,stimulus=Stimulus())])
    with pytest.raises(ValidationError): BatchRequest(config=RunConfig())
    with pytest.raises(ValidationError): BatchRequest(config=RunConfig(protocol=Protocol(duration_steps=10000)),seeds=[1,2],conditions=['control','baseline'])
    with pytest.raises(ValidationError): BatchRequest(config=RunConfig(protocol=Protocol(events=[ProtocolEvent(step=2,interventions=Interventions())])))


def test_connectivity_identifiers_and_structural_statistics():
    data=json.loads((ROOT/'data/examples/connectivity-example.json').read_text())
    data['nodes'][0]['id']='720575940604737708'
    data['edges'][0]['pre_id']='720575940604737708'
    graph=ConnectivityGraph.model_validate(data)
    assert graph.nodes[0].id == '720575940604737708'
    summary=graph_summary(graph)
    assert summary['synapses']==15 and summary['outgoing_synapses']['720575940604737708']==10
    data['nodes'][0]['id']=720575940604737708
    with pytest.raises(ValidationError):ConnectivityGraph.model_validate(data)
    data['nodes'][0]['id']='missing'
    with pytest.raises(ValidationError):ConnectivityGraph.model_validate(data)


def test_sequential_batch_saves_matched_trials_and_rejects_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr('digitalfly.simulation.experiment.ROOT',tmp_path)
    app=create_app(RunConfig(engine='toy'),False)
    with TestClient(app,base_url='http://127.0.0.1:8000') as client:
        assert app.state.worker.ready.wait(5)
        config=RunConfig(engine='toy',speed=2,protocol=Protocol(duration_steps=25))
        response=client.post('/api/batch/start',json={'config':config.model_dump(),'seeds':[42,43],'conditions':['control','descending_off']})
        assert response.status_code==200, response.text
        assert client.post('/api/stimulus',json={'x':0}).status_code==409
        client.post('/api/pause',json={})
        s=client.get('/api/status').json();assert s['batch']['status']=='paused'
        time.sleep(.04);assert client.get('/api/status').json()['sample']['step']==s['sample']['step']
        client.post('/api/run',json={})
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            state=client.get('/api/status').json()
            if state['batch']['status']=='completed':break
            time.sleep(.04)
        assert state['batch']['status']=='completed',state
        assert len(state['batch']['results'])==4
        trials=[json.loads(path.read_text()) for path in tmp_path.glob('runs/*/metadata.json')]
        assert len(trials)==4
        assert {(m['trial']['condition'],m['initial_config']['seed']) for m in trials}=={(c,s) for c in ['control','descending_off'] for s in [42,43]}
        for m in trials:
            assert m['recorded_samples']==26 and m['metrics']['protocol_complete']
            if m['trial']['condition']=='descending_off': assert m['metrics']['path_length_mm']==0
            else:assert m['metrics']['path_length_mm']>0
        assert client.post('/api/run',json={}).status_code==409
    assert not app.state.worker.thread.is_alive()


def test_batch_cancel_and_shutdown_scope(tmp_path,monkeypatch):
    monkeypatch.setattr('digitalfly.simulation.experiment.ROOT',tmp_path)
    app=create_app(RunConfig(engine='toy'),False)
    called=[];app.state.shutdown_callback=lambda:called.append(True)
    with TestClient(app,base_url='http://127.0.0.1:8000') as client:
        assert app.state.worker.ready.wait(5)
        config=RunConfig(engine='toy',protocol=Protocol(duration_steps=100))
        client.post('/api/batch/start',json={'config':config.model_dump(),'seeds':[42],'conditions':['control']})
        state=client.post('/api/batch/cancel',json={}).json()
        assert state['status']=='paused' and state['batch']['status']=='cancelled'
        assert client.post('/api/parameters',json={'tonic_drive':.4}).status_code==200
        assert client.post('/api/shutdown',json={'instance_id':'wrong'}).status_code==409
        assert not called
        assert client.post('/api/shutdown',json={'instance_id':state['instance_id']},headers={'Origin':'https://elsewhere.example'}).status_code==403
        assert not called
        assert client.post('/api/shutdown',json={'instance_id':state['instance_id']}).status_code==200
        assert called==[True]


def test_anatomy_integrity_and_api(tmp_path,monkeypatch):
    mapping=json.loads((ROOT/'data/atlas/type-mapping-excerpt.json').read_text())['assignments']
    for sex in ['female','male']:
        data=json.loads((ROOT/f'data/atlas/{sex}.json').read_text())
        assert data['sex']==sex and len(data['neurons'])==6
        for n in data['neurons']:
            assert isinstance(n['id'],str) and mapping[n['id']]==n['cell_type']
            assert n['display_points']<=n['original_points'] and n['cable_length_um']>0
            assert np.isfinite(np.asarray(n['points'])).all()
            assert all(0<=i<len(n['points']) for edge in n['edges'] for i in edge)
    monkeypatch.setattr('digitalfly.data.research.ROOT',tmp_path)
    app=create_app(RunConfig(engine='toy'),False)
    with TestClient(app,base_url='http://127.0.0.1:8000') as client:
        assert app.state.worker.ready.wait(5)
        assert client.get('/api/atlas').status_code==200
        assert client.get('/api/atlas/male').json()['neurons_loaded']==6
        assert client.get('/api/atlas/other').status_code==404
        data=json.loads((ROOT/'data/examples/connectivity-example.json').read_text())
        example=client.get('/api/examples/connectivity')
        assert example.status_code==200 and example.headers['content-type'].startswith('application/json')
        assert 'attachment' in example.headers['content-disposition'] and example.json()==data
        result=client.post('/api/connectivity/import',json=data)
        assert result.status_code==200
        key=result.json()['key']
        assert client.get('/api/connectivity/'+key).json()['summary']['synapses']==15
        assert len(client.get('/api/connectivity').json()['datasets'])==1
        data['nodes'][0]['id']=9007199254740993
        assert client.post('/api/connectivity/import',json=data).status_code==422
        assert client.get('/api/runs/not-a-run').status_code==404


@pytest.mark.flygym
@pytest.mark.render
def test_actual_compound_eyes_and_body_observations():
    exp=Experiment(RunConfig(sensor_model='vision'),render=False)
    try:
        assert exp.status=='paused',exp.error
        assert exp.body.vision['ommatidia_per_eye']==721
        assert len(exp.body.eye_frame)>1000
        original=exp.sample.sensors.raw_left
        exp.set_stimulus(Stimulus(x=12,y=-8))
        assert abs(exp.sample.sensors.raw_left-original)>.001
        exp.set_interventions(Interventions(zero_left=True))
        for _ in range(12):exp.advance()
        assert exp.sample.sensors.left==0 and exp.sample.rates[0]==0
        assert exp.sample.pose.x>.1
        body=exp.sample.body_signals
        assert len(body['contact'])==6 and len(body['cpg_phase_rad'])==6
        assert len(body['joint_position_rad'])>40 and np.isfinite(body['ground_contact_force']).all()
        assert exp.metrics['contact_fraction']
        exp.set_stimulus(Stimulus(intensity=0))
        assert max(exp.sample.sensors.raw_left,exp.sample.sensors.raw_right)<.1
    finally:exp.close()
