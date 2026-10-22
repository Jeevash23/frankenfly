# Local scientific assets

Everything committed under `data/` is third-party scientific data, a file derived from it, or project metadata about it. The data keeps its original licenses, listed in each folder's `LICENSE.md`; it is **not** covered by the project's Apache-2.0 license. All FlyWire-derived files are CC BY-NC 4.0, for non-commercial use only.

| Folder | What is committed | License |
| --- | --- | --- |
| `atlas/` | Anatomy for the atlas view: twelve neuron skeletons (DNa02, DNp01 and DNp09, two per type per sex), brain and nerve-cord surfaces, the display files `female.json` and `male.json` built from them, and their sources, hashes and cell-type mapping | Per file: CC BY-NC 4.0, CC BY 4.0 and GPL-3.0; see [atlas/LICENSE.md](atlas/LICENSE.md) |
| `circuits/` | The connectome model's two FlyWire v783 circuits, their FlyVis bridges and the record of the downloads they are built from | CC BY-NC 4.0; see [circuits/LICENSE.md](circuits/LICENSE.md) |
| `recordings/` | Metadata only: where to download each recorded-fly dataset, with its hashes, license and citation | Data CC0 1.0; see [recordings/LICENSE.md](recordings/LICENSE.md) |
| `examples/` | A clearly labeled synthetic fixture for the connectivity import format | CC0 1.0, as the file declares |

## atlas/

Structural reconstructions for display, not an executable connectome: the female (FAFB / FlyWire v783) and male (MaleCNS v1.0) skeletons in `sources/*.swc`, the navis-flybrains surfaces in `sources/*.ply`, and `female.json` / `male.json`, which `scripts/build_atlas.py` builds offline from them after checking every source against `downloads.json`. `manifest.json` describes the two datasets; `type-mapping-excerpt.json` holds the twelve cell-type assignments. Each display file combines a CC BY-NC 4.0 or CC BY 4.0 `neurons` section with a GPL-3.0 `surfaces` section; [atlas/LICENSE.md](atlas/LICENSE.md) explains what that means for redistribution.

## circuits/

| File | Content |
| --- | --- |
| `fafb783-dna02.json` | The default circuit: both DNa02 neurons and their presynaptic partners up to two hops back (3,000 neurons, 78,615 connections, 1,257 cell types) |
| `fafb783-steering.json` | The steering circuit around DNa01, DNa02 and DNp09 (4,000 neurons, 120,728 connections, 1,650 cell types) |
| `fafb783-dna02-balanced.json`, `fafb783-steering-balanced.json` | The same seeds and caps built with `--balance-sides`: the cap keeps each cell type's left and right neurons in pairs (3,000 neurons and 1,056 cell types; 3,999 neurons and 1,438 cell types) |
| `fafb783-dna02.flyvis.json`, `fafb783-steering.flyvis.json`, `fafb783-dna02-balanced.flyvis.json`, `fafb783-steering-balanced.flyvis.json` | FlyVis bridges: FlyWire v783 synapse counts from the optic-lobe cell types FlyVis models onto each circuit's visual projection neurons, by eye, tied to the circuit by its SHA-256. Only the optional FlyVis eyes read them; they never appear as circuits |
| `downloads.json` | URL, release, size and SHA-256 of the two FlyWire v783 downloads the circuits are built from |
| `local/` (ignored by git) | Circuits you build in the app or with `scripts/build_circuit.py build`, and their bridges. They stay on your computer and keep the FlyWire license |

`scripts/build_circuit.py` rebuilds the committed circuits and builds new ones; `build_circuit.py flyvis-bridge --circuit NAME` writes a bridge next to its circuit. Raw downloads and the prepared archive stay in the ignored `.cache/circuits/`. See the [research guide](../docs/RESEARCH.md#the-connectome-model).

## recordings/

`downloads.json` lists each recorded-fly dataset DigitalFly can compare with: today one paired left/right DNa02 recording from Rayshubskiy et al. 2025. No recording is committed. `scripts/fetch_recording.py NAME` downloads the file into the ignored `.cache/recordings/` and keeps it only if its size, MD5 and SHA-256 match. Keep raw recordings there: git ignores everything in `data/recordings/` except `downloads.json` and `LICENSE.md`. See [comparing with real flies](../docs/RESEARCH.md#comparing-with-real-flies).

## Local, ignored folders

- `connectivity/`: connectivity graphs you import in the app. Imported graphs are displayed, never used to drive the body.
- `flygym-assets/`: optional FlyGym mesh caches.
- `circuits/local/`: circuits you build (above).

The walking controller uses six engineered rate units by default; the connectome model uses `circuits/`. See [research methods, source data and licensing](../docs/RESEARCH.md).
