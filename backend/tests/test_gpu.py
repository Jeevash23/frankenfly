"""The optional torch brain backend (neural/gpu.py) and batched MuJoCo Warp worlds (simulation/batched.py).

Three tiers, each skipping cleanly where it cannot run:
  - always: the default stays "cpu", the backend is fixed for a run, an unavailable backend is a clear error, and
    sweep hashes ignore the default;
  - with PyTorch (any build): the torch code on PyTorch's CPU device (DIGITALFLY_TORCH_DEVICE=cpu, the plain
    PyTorch path) against the CPU backend;
  - with CUDA PyTorch (backend/.venv-gpu): the fused Triton kernels, the agreement harness on a committed circuit
    and batched worlds. Run them with
        backend/.venv-gpu/bin/python -m pytest backend/tests/test_gpu.py
"""
import importlib.util
import warnings
import numpy as np
import pytest
from digitalfly.api.models import (CellTypeIntervention, ConnectomeParameters, FIXED_CONNECTOME_FIELDS, Interventions,
                                   RunConfig, SensorState)
from digitalfly.neural import gpu
from digitalfly.neural.connectome import LIF, CircuitData, ConnectomeCircuit, SpikingState, transmitter_signs

HAS_TORCH = importlib.util.find_spec("torch") is not None


def _cuda() -> bool:
    if not HAS_TORCH:
        return False
    import torch
    return torch.cuda.is_available() and torch.version.cuda is not None


HAS_CUDA = _cuda()
needs_torch = pytest.mark.skipif(not HAS_TORCH, reason="PyTorch is not installed")
needs_cuda = pytest.mark.skipif(not HAS_CUDA, reason="needs CUDA PyTorch and an NVIDIA GPU (backend/.venv-gpu)")
warnings.filterwarnings("ignore", "Sparse CSR tensor support is in beta")


@pytest.fixture
def status():
    """Clear the cached availability before and after a test that changes it."""
    gpu._status.cache_clear()
    yield
    getattr(gpu._status, "cache_clear", lambda: None)()  # a test may have replaced it (monkeypatch restores it)


@pytest.fixture
def torch_cpu(monkeypatch, status):
    """The torch backend on PyTorch's CPU device, with the plain PyTorch path."""
    if not HAS_TORCH:
        pytest.skip("PyTorch is not installed")
    monkeypatch.setenv(gpu.DEVICE_VARIABLE, "cpu")
    monkeypatch.setenv("DIGITALFLY_TORCH_EAGER", "1")


def test_the_default_backend_is_the_cpu_and_fixed_for_a_run():
    assert ConnectomeParameters().backend == "cpu" and "backend" in FIXED_CONNECTOME_FIELDS
    from digitalfly.simulation.experiment import Experiment
    exp = Experiment(RunConfig(engine="toy", neural_model="connectome"), render=False)
    try:
        assert exp.circuit._torch_rate is None and exp.circuit.description().get("backend") is None
        with pytest.raises(ValueError, match="backend"):
            exp.set_connectome_parameters(exp.config.connectome_parameters.model_copy(update={"backend": "torch"}))
    finally:
        exp.close()


def test_an_unavailable_torch_backend_is_refused_with_the_fix(monkeypatch, status):
    monkeypatch.setattr(gpu, "_status", lambda: (False, "no GPU here (test)", None))
    assert gpu.available() == (False, "no GPU here (test)")
    with pytest.raises(ValueError, match="torch brain backend is unavailable: no GPU here"):
        ConnectomeCircuit(ConnectomeParameters(backend="torch"))
    with pytest.raises(ValueError, match="unavailable"):
        RunConfig(neural_model="connectome", connectome_parameters={"backend": "torch"})
    model = ConnectomeCircuit()  # a failed switch leaves a running model as it was
    with pytest.raises(ValueError):
        model.configure(ConnectomeParameters(backend="torch"))
    assert model._torch_rate is None and model.parameters.backend == "cpu"


def test_a_cpu_only_pytorch_is_reported_without_importing_it(monkeypatch, status):
    monkeypatch.delenv(gpu.DEVICE_VARIABLE, raising=False)
    monkeypatch.setattr("importlib.metadata.version", lambda name: "2.14.1+cpu")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: object() if name == "torch" else None)
    ok, reason = gpu.available()
    assert not ok and "CPU-only build" in reason and "--with gpu" in reason


def test_sweep_hashes_leave_the_default_backend_out():
    import hashlib
    import json
    from digitalfly import toolkit
    config = RunConfig(engine="toy", neural_model="connectome")
    dumped = config.model_dump(mode="json")
    del dumped["connectome_parameters"]["backend"]
    settings = {k: float(v) if isinstance(toolkit.TRIAL_SETTINGS[k], float) else v
                for k, v in toolkit.TRIAL_SETTINGS.items()}
    before = hashlib.sha256(json.dumps({"config": dumped, "settings": settings,
                                        "circuit_sha256": toolkit.circuit_sha256(config.connectome_parameters.circuit)},
                                       sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert toolkit.config_hash(config) == before  # what the hash was before the backend setting existed
    torch_config = config.model_copy(update={"connectome_parameters": config.connectome_parameters.model_copy(
        update={"backend": "torch"})})
    assert toolkit.config_hash(torch_config) != before


def test_capabilities_list_the_backends(monkeypatch, status):
    from fastapi.testclient import TestClient
    from digitalfly.main import create_app
    with TestClient(create_app(RunConfig(engine="toy"), render=False), base_url="http://127.0.0.1:8000") as client:
        capabilities = client.get("/api/capabilities").json()
    assert capabilities["connectome_backends"] == ["cpu", "torch"]
    assert set(capabilities["torch_backend"]) == {"available", "reason"}


def test_benchmark_backend_options_are_checked():
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    done = subprocess.run([sys.executable, str(root / "scripts/benchmark.py"), "--check", "--backend", "torch"],
                          capture_output=True, text=True, timeout=120, cwd=root)
    assert done.returncode == 2 and "--backend applies to --neural" in done.stderr


# The torch code on PyTorch's CPU device: the plain PyTorch path.

def test_rate_dynamics_match_the_cpu_backend(torch_cpu, toy_brain):
    from digitalfly.neural.agreement import rate_agreement
    manipulations = [CellTypeIntervention(name="DNa02", side="left", mode="scale", value=.5),
                     CellTypeIntervention(name="LC10a", side="both", mode="activate", value=.7),
                     CellTypeIntervention(name="DNa03", side="both", mode="silence")]
    result = rate_agreement("fafb783-dna02", steps=120, interventions=manipulations)
    assert result["passed"] and result["max_abs_difference"] < 1e-12, result
    toy = rate_agreement("toy-brain", steps=60)
    assert toy["passed"] and toy["max_abs_difference"] < 1e-14


def test_rate_state_carries_over_live_edits_and_resets(torch_cpu):
    sensors, none = SensorState(left=.7, right=.2), Interventions()
    cpu, torch_model = ConnectomeCircuit(), ConnectomeCircuit(ConnectomeParameters(backend="torch"))
    for model in (cpu, torch_model):
        for _ in range(30):
            model.advance(sensors, none)
        model.configure(model.parameters.model_copy(update={"global_gain": .002}))
        for _ in range(30):
            model.advance(sensors, none)
    assert np.allclose(cpu.activity, torch_model.activity, rtol=0, atol=1e-12)
    assert cpu.readout() == pytest.approx(torch_model.readout(), abs=1e-12) and torch_model.turn() != 0
    description = torch_model.description()
    assert description["backend"]["name"] == "torch" and description["parameters"]["backend"] == "torch"
    torch_model.reset(3)
    assert not torch_model.activity.any()


def torch_state(path, parameters=ConnectomeParameters(dynamics="spiking")):
    data = CircuitData(path)
    signs = transmitter_signs(data, parameters.other_transmitters)
    active = np.ones(len(data.synapses), dtype=bool)
    inputs = (np.array([2]), np.array([3]))
    state = gpu.TorchSpikingState(data, active, signs, parameters, inputs, gpu.device())
    cpu = SpikingState(data, active, signs, parameters, inputs)
    state.substeps = cpu.substeps = 1
    return state, cpu


def _check_spike_timing(path):
    """Without Poisson input the network is deterministic: the torch state follows the CPU state exactly."""
    state, cpu = torch_state(path)
    none = np.array([], dtype=np.int64)
    for s in (state, cpu):
        s.v[2] = -40.0  # LCa left fires in the first substep
    assert int(state.advance(0, 0, none)) == cpu.advance(0, 0, none) == 1
    for _ in range(18):
        state.advance(0, 0, none)
        cpu.advance(0, 0, none)
    torch_g = state.g[:state.n].cpu().numpy()
    assert torch_g[0] == pytest.approx(10 * .275) and torch_g[6] == pytest.approx(8 * .275)
    for _ in range(40):
        state.advance(0, 0, none)
        cpu.advance(0, 0, none)
    assert np.allclose(state.membrane(), cpu.v, rtol=0, atol=1e-9)
    assert np.array_equal(state.rate_hz > 0, cpu.rate_hz > 0)
    assert state.base_refractory[2].item() == 0 and state.base_refractory[0].item() == round(2.2 / .1)


def test_spikes_arrive_after_1_8_ms_as_on_the_cpu(torch_cpu, toy_brain):
    _check_spike_timing(toy_brain)


def test_spiking_interface_matches_the_cpu_state(torch_cpu, toy_brain):
    """Seeds repeat, interventions apply, spikes are recorded and live edits keep the network."""
    parameters = ConnectomeParameters(circuit="toy-brain", dynamics="spiking", backend="torch", input_gain=10)
    sensors = SensorState(left=.8, right=.2)

    def run(seed, interventions=Interventions(), steps=150):
        model = ConnectomeCircuit(parameters)
        model.reset(seed)
        model.record_spikes(np.arange(len(model.data.ids)))
        model.apply_silencing(interventions)
        rows = []
        for _ in range(steps):
            model.advance(sensors, interventions)
            rows.append(model.readout())
        return np.array(rows), model
    a, model = run(1)
    b, _ = run(1)
    c, _ = run(2)
    assert np.array_equal(a, b) and not np.array_equal(a, c)
    spikes, count = model.spike_record()
    assert count == sum(len(hit) for _, hit in spikes) > 0 and model.spiking.recorded_count == count
    assert a[-1, 0] > a[-1, 1] and model.turn() < 0  # left input → left DNx → left turn, as on the CPU
    silenced, model = run(1, Interventions(cell_types=[CellTypeIntervention(name="DNx", side="left", mode="silence")]))
    assert (silenced[:, 0] == 0).all() and silenced[:, 2].max() > 0  # DNx L silent; LCa L still fires
    state = model.spiking
    model.configure(parameters.model_copy(update={"output_gain": 2, "spiking": parameters.spiking.model_copy(
        update={"synapse_weight_mv": .3})}))
    assert model.spiking is state and state.step_index == 1500 and state.kick == pytest.approx(250 * .3)
    model.advance(sensors, Interventions())
    assert state.step_index == 1510


# The fused Triton kernels (CUDA).

@pytest.fixture
def cuda(status, monkeypatch):
    monkeypatch.delenv(gpu.DEVICE_VARIABLE, raising=False)
    monkeypatch.delenv("DIGITALFLY_TORCH_EAGER", raising=False)


@needs_cuda
def test_the_fused_kernels_time_spikes_as_the_cpu(cuda, toy_brain):
    state, _ = torch_state(toy_brain)
    assert state.fused and state.size % 256 == 0
    _check_spike_timing(toy_brain)


@needs_cuda
def test_fused_spiking_repeats_exactly_for_a_seed(cuda):
    sensors = SensorState(left=.6, right=.4)
    scaled = Interventions(cell_types=[CellTypeIntervention(name="DNa02", side="left", mode="scale", value=.5),
                                       CellTypeIntervention(name="LC10a", side="right", mode="activate", value=40)])

    def run(seed, edit=False):
        model = ConnectomeCircuit(ConnectomeParameters(dynamics="spiking", backend="torch"))
        model.reset(seed)
        model.record_spikes(model.readouts[0][1])
        for k in range(200):
            if edit and k == 100:  # queued spikes keep their weights across a live edit
                p = model.parameters
                model.configure(p.model_copy(update={"spiking": p.spiking.model_copy(update={"synapse_weight_mv": .3})}))
            model.advance(sensors, scaled if k >= 50 else Interventions())
        return model.spiking.rate_hz.copy(), model.spiking.membrane(), model.spike_record()[1]
    a, b, c = run(0), run(0), run(1)
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1]) and a[2] == b[2]
    assert not np.array_equal(a[0], c[0])
    edited, again = run(0, edit=True), run(0, edit=True)
    assert np.array_equal(edited[1], again[1]) and not np.array_equal(edited[1], a[1])


@needs_cuda
def test_spiking_agrees_with_the_cpu_in_distribution(cuda):
    from digitalfly.neural.agreement import spiking_agreement
    result = spiking_agreement("fafb783-dna02", seconds=1, seeds=(0, 1, 2))
    assert result["passed"], result
    corr = result["per_neuron_rate_correlation"]
    assert corr["cpu_vs_torch"] > .95 and abs(corr["cpu_vs_torch"] - corr["cpu_vs_cpu"]) < .03


@needs_cuda
def test_rate_dynamics_on_the_gpu_match_the_cpu(cuda):
    from digitalfly.neural.agreement import rate_agreement
    result = rate_agreement("fafb783-steering", steps=200,
                            interventions=[CellTypeIntervention(name="DNa02", side="right", mode="scale", value=1.5)])
    assert result["passed"] and result["max_abs_difference"] < 1e-12, result


@needs_cuda
def test_the_gpu_backend_runs_in_an_experiment(cuda):
    from digitalfly.simulation.experiment import Experiment
    exp = Experiment(RunConfig(engine="toy", neural_model="connectome", seed=3,
                               connectome_parameters={"dynamics": "spiking", "backend": "torch"}), render=False)
    try:
        assert exp.status == "paused", exp.error
        for _ in range(20):
            exp.advance()
        assert exp.sample.t == pytest.approx(.2) and any(exp.sample.rates)
        assert exp.circuit.description()["backend"]["name"] == "torch"
    finally:
        exp.close()


@needs_cuda
@pytest.mark.skipif(importlib.util.find_spec("mujoco_warp") is None, reason="needs MuJoCo Warp (backend/.venv-gpu)")
def test_batched_worlds_follow_the_cpu_engine_closely(cuda):
    from digitalfly.simulation.batched import compare_worlds
    result = compare_worlds((1, 4), seconds=.03)
    assert result["available"] and result["cpu_replay_matches_closed_loop_mm"] < 1e-6
    for row in result["rows"][1:]:
        assert row["world_steps_per_s"] > 0 and row["distance_from_cpu_end_mm"] < .05
    assert LIF["dt_ms"] == .1  # the neural constants are untouched by the physics extra
