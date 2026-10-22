"""Activation needs a value above 0: "activate at 0 Hz" used to be accepted and, in spiking dynamics, still took
the refractory period away from the neurons it named."""
import subprocess
import sys
from pathlib import Path
import pytest
from pydantic import ValidationError
from digitalfly import toolkit
from digitalfly.api.models import CellTypeIntervention, ConnectomeParameters, Interventions, RunConfig
from digitalfly.neural.connectome import ConnectomeCircuit

ROOT = Path(__file__).resolve().parents[2]
TOY = ConnectomeParameters(circuit="toy-brain", global_gain=.05)
# Toy circuit (conftest): 2/3 LCa L/R (input, no refractory period), 6/7 DNy L/R, 9 Solo (left).


def test_activation_needs_a_value_above_zero(toy_brain):
    for item in [{"name": "Solo", "mode": "activate"}, {"name": "Solo", "mode": "activate", "value": 0}]:
        with pytest.raises(ValidationError, match="Activation needs a value above 0"):
            CellTypeIntervention.model_validate(item)
    with pytest.raises(ValidationError, match="above 0"):
        RunConfig(engine="toy", neural_model="connectome", connectome_parameters=TOY,
                  initial_interventions={"cell_types": [{"name": "Solo", "mode": "activate", "value": 0}]})
    assert CellTypeIntervention(name="Solo", mode="activate", value=.01).value == .01
    assert CellTypeIntervention(name="Solo", mode="scale").value == 0  # output × 0 is still a valid scaling
    with pytest.raises(ValueError, match="Activation needs a value above 0"):
        toolkit.ablation_scan(TOY, ms=20, mode="activate")  # value defaults to 0, so it must be given


def test_neurons_without_activation_keep_their_refractory_period(toy_brain):
    model = ConnectomeCircuit(TOY.model_copy(update={"dynamics": "spiking"}))
    model.reset(1)
    unchecked = [CellTypeIntervention.model_construct(name="Solo", side="both", mode="activate", value=0.),
                 CellTypeIntervention.model_construct(name="DNy", side="both", mode="activate", value=200.)]
    model.spiking.manipulate(model.manipulation(Interventions.model_construct(
        **{**Interventions().model_dump(), "cell_types": unchecked})))
    assert model.spiking.refractory[[9, 6, 7, 2]].tolist() == [22, 0, 0, 0]


def test_the_ablation_command_refuses_activation_at_zero():
    done = subprocess.run([sys.executable, str(ROOT / "scripts/toolkit.py"), "ablation", "--mode", "activate", "--value", "0",
                           "--type", "DNa03", "--ms", "5"], capture_output=True, text=True, timeout=300, cwd=ROOT)
    assert done.returncode == 1 and "Activation needs a value above 0" in done.stderr
