# DigitalFly — v0.2 status

DigitalFly is a local research workspace for embodied sensorimotor experiments. See the [quick start](README.md#quick-start) for portable setup and shutdown instructions.

## Implemented

- Real FlyGym / MuJoCo walking and turning with the female-derived NeuroMechFly body, joints, contact and adhesion.
- Selectable geometric sensing or actual rendered compound-eye input, with 721 ommatidia per eye and an explicitly engineered green-contrast encoder.
- A live six-unit circuit inspector with editable parameters, group silencing, exact weights and computed rates.
- Male/female anatomical reference surfaces and twelve published neuron skeletons, with rotation, selection, source IDs and attribution.
- Validated local structural-connectivity import, preserving string IDs and declared provenance. Imported graphs do not replace the walking controller.
- Timed stimulus protocols, matched-seed condition comparisons, sequential trials, pause/resume/cancel and automatic completed-trial exports.
- Joint, contact and motion measurements; a local run library, trajectory overlays, configuration restoration, CSV/JSON/ZIP export and replay.
- One authoritative worker with bounded queues/history/recording, explicit error handling and graceful Quit / Save current run & quit.

## Validation summary

The v0.2 reference validation covered macOS/ARM64, Python 3.12 and the pinned dependencies. This describes a tested platform, not a required hardware model. Other operating systems and graphics combinations require their own validation.

| Check | Reference result |
| --- | --- |
| Full backend suite | 29 passed, including real FlyGym, graphics, protocols, comparisons and data validation |
| Frontend unit tests | 10 passed: plotting, protocol editing and error messages |
| Prettier formatting, TypeScript and production build | Passed |
| Clean-checkout run | A copy containing only the version-controlled files passed the full suite with a cold font cache |
| Browser flow | Real body/eye inputs, circuit controls, male/female anatomy, connectivity import, trial comparisons and both Quit paths exercised |
| Replay | Visual-input and timed-protocol runs reproduced with zero difference in checked fields, at tolerance 1e-8 on the same software/graphics stack |
| Export integrity | CSV/body sample counts and joint labels matched; ZIP integrity passed |
| Shutdown | Launcher exited cleanly and the server port closed |

Four short matched-condition trials confirmed that silencing the engineered descending output changes actual simulated movement. This establishes an implemented computational effect, not biological validity or statistical significance.

Two upstream TestClient deprecation notices were present in the reference tests. There is no guarantee of bitwise numerical agreement across devices or dependency versions.

Raw logs, session identifiers and machine-specific measurements are local generated evidence and are excluded from version control. To reproduce the checks and benchmark your own hardware, see [validation commands](docs/evidence/README.md).

## Scientific scope

**The walking controller is not a full biological connectome.** Six engineered rate units and an engineered locomotion controller generate motor commands. Published anatomical shapes and imported synaptic counts are separate structural data; they do not automatically supply validated neural physiology.

**Both sexes have anatomical data; only the female-derived body is simulated.** There is no male body model, fitted sex-specific physiology/behavior, whole-CNS dynamics, spiking network, flight, feeding, learning, courtship or multi-animal interaction. The visual encoder is an engineered green-object detector. The target is a non-colliding landmark. Long trajectories can overshoot, circle or leave the bounded schematic display.

Whole-connectome downloads, pretrained FlyVis integration and larger neural models remain future work. The next scientific milestone is a specified biological circuit with justified dynamics and a documented motor mapping, evaluated against measured behavior and held-out interventions. Methods and dataset-specific licensing are in the [research guide](docs/RESEARCH.md).

## Repository scope

Runtime files stay local. The repository contains instructions, code, dependency locks, examples and attributed scientific assets. Local environments, imported datasets, run records and execution evidence are excluded by [.gitignore](.gitignore). See [sharing the project](docs/SHARING.md).

The code and documentation are Apache-2.0 ([LICENSE](LICENSE), [NOTICE](NOTICE)). The anatomical data keeps its own licenses, listed in [data/atlas/LICENSE.md](data/atlas/LICENSE.md).
