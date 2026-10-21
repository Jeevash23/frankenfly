# Upstream attribution

- **NeLy-EPFL FlyGym / NeuroMechFly 2.1.0**, Apache License 2.0. [Source and authors](https://github.com/NeLy-EPFL/flygym/tree/v2.1.0). [Local license](FLYGYM-LICENSE.txt). The body construction, reset posture and upstream controller usage in `scripts/smoke_flygym.py` and `backend/src/digitalfly/simulation/engines.py` follow [tutorial 4d](https://neuromechfly.org/tutorials/4d_turning_controller/). This project changes the ground colors and camera for display; the standard body/controller remains upstream code. Package-distributed meshes/data keep their package license and attribution. Nothing is redistributed here outside the normal installed package.
- **MuJoCo**, accessed through its installed package and FlyGym; retains its upstream license. [Official source](https://github.com/google-deepmind/mujoco).
- **Instrument Serif** and **DM Sans**, locally served Fontsource distributions, SIL Open Font License. [Instrument Serif license](INSTRUMENT-SERIF-LICENSE.txt), [DM Sans license](DM-SANS-LICENSE.txt).
- **Lucide icons**, from the installed `lucide-react` package (ISC). React, Vite and other packages retain their package licenses; versions and integrity hashes are in the frontend lockfile.

The engineered model's neural matrices, the sensor approximation, interface, worker and application code are custom engineered components. No biological neural identities or connectome weights are attributed to them. `fast_turning_controller` and `ContactForces` in `backend/src/digitalfly/simulation/engines.py` re-implement FlyGym 2.1.0's `HybridController.step`, `HybridTurningController.step` and `Simulation.get_bodysegment_contact_forces` (Apache-2.0) with precomputed lookups and the same arithmetic.

Code adapted from other projects is listed, with its copyright and license notices, in [NOTICE](../NOTICE).


## Anatomical samples added in v0.2

MaleCNS v1.0 reconstructions: FlyEM/Janelia, Cambridge, MRC LMB and Google, CC BY 4.0. Female FAFB/FlyWire reconstructions: FlyWire Consortium and original imaging/reconstruction authors, via the Bates/Lee lab compilation; public-release terms CC BY-NC 4.0. Cross-matched cell identities: authors' `flyconnectome/2025malecns` mapping (Berg et al. 2025; the repository states no license).

The navis-flybrains surface assets retain their upstream GPL-3.0 distribution notice at `data/atlas/sources/flybrains-LICENSE`. Original dataset attribution remains applicable. Every retained download has a URL, size and SHA-256 in `data/atlas/downloads.json`. `data/atlas/female.json` and `male.json` each combine simplified skeletons (CC BY-NC 4.0 or CC BY 4.0) with simplified GPL-3.0 surfaces in one file. The license of every data file, and what the combined files mean for redistribution, are in [data/atlas/LICENSE.md](../data/atlas/LICENSE.md); none of it is covered by the project's Apache-2.0 license. See [full source and license details](RESEARCH.md#licensing-and-attribution).

## Connectome data added in v0.3

`data/circuits/fafb783-dna02.json` (and, from v0.4, `fafb783-steering.json` and any circuit you build) is derived from FlyWire FAFB v783: the FlyWire Consortium's reconstruction (Dorkenwald et al. 2024, *Nature*) and annotations (Schlegel et al. 2024, *Nature*), neurotransmitter predictions by Eckstein et al. (2024, *Cell*), the Bates/Lee lab's harmonized metadata compilation ([sjcabs/fly_connectome_data_tutorial](https://github.com/sjcabs/fly_connectome_data_tutorial), code MIT) and the v783 connectivity table published with Shiu et al. (2024, *Nature*; [philshiu/Drosophila_brain_model](https://github.com/philshiu/Drosophila_brain_model), code MIT). Only their data is used, not their code. The data is CC BY-NC 4.0, for non-commercial use only. The sign rule for acetylcholine, GABA and glutamate follows Shiu et al.; the DNa02 steering direction follows Rayshubskiy et al. (2025, *eLife* 13:RP102230). Sources, sizes and hashes are in `data/circuits/downloads.json`; licensing in [data/circuits/LICENSE.md](../data/circuits/LICENSE.md).

## Spiking dynamics added in v0.4

The spiking dynamics in `backend/src/digitalfly/neural/connectome.py` re-implement in NumPy the leaky integrate-and-fire model, constants and Brian2 update order of Shiu et al.'s `model.py` ([philshiu/Drosophila_brain_model](https://github.com/philshiu/Drosophila_brain_model), Copyright (c) 2023 Philip Shiu and Nico Spiller, MIT). The notice is in [NOTICE](../NOTICE). Brian2 itself is not used.

## FlyVis eyes added in v0.5

- **FlyVis 1.2.0** (Lappalainen et al. 2024, *Nature* 634:1132–1140, [doi:10.1038/s41586-024-07939-3](https://doi.org/10.1038/s41586-024-07939-3)), MIT License, Copyright (c) 2023 Janne K. Lappalainen, Fabian D. Tschopp, Mason McGill, Jakob H. Macke, Srinivas C. Turaga. Checked in the `license` file of the 1.2.0 source distribution on PyPI and its "MIT License" classifier. It is an optional install (`backend/requirements-vision.lock`) and is not redistributed here. `backend/src/digitalfly/vision/flyvis_eyes.py` calls its API; it copies none of its code. FlyVis's own optic-lobe connectivity (from the FIB-25 and FIB-19 medulla reconstructions) ships inside the FlyVis package under FlyVis's terms.
- **FlyVis pretrained networks.** `scripts/fetch_flyvis.py` downloads the 50 networks (3,417,042 bytes, SHA-256 checked against the value FlyVis's own downloader expects) from the archive the FlyVis authors publish, into the ignored `.cache/flyvis/`. The archive carries no license file of its own, and FlyVis's documentation names no separate terms for it; DigitalFly treats the networks as covered by FlyVis's MIT license. **To verify** with the FlyVis authors before redistributing the networks; DigitalFly does not redistribute them.
- **PyTorch and torchvision** (BSD-style licenses) come with the optional vision lock; they are not redistributed.
- **Column mapping.** The anchored affine fit that matches FlyGym ommatidia to FlyVis columns follows FlyGym 1.x's `RetinaMapper` (Apache-2.0). The eye-orientation check follows Maisak et al. (2013, *Nature* 500:212–216).
- **FlyVis bridges** (`data/circuits/*.flyvis.json`) are FlyWire v783 synapse counts, CC BY-NC 4.0, non-commercial; see [data/circuits/LICENSE.md](../data/circuits/LICENSE.md).

## Recorded-fly comparison added in v0.5

- **Data.** One paired DNa02 recording from Rayshubskiy et al. 2025 (*eLife* 13:RP102230, [doi:10.7554/eLife.102230](https://doi.org/10.7554/eLife.102230)), Harvard Dataverse [doi:10.7910/DVN/0NCLP1](https://doi.org/10.7910/DVN/0NCLP1), CC0 1.0. `scripts/fetch_recording.py` downloads it into the ignored `.cache/recordings/`; it is not redistributed. See [data/recordings/LICENSE.md](../data/recordings/LICENSE.md).
- **Code.** `detect_spikes`, `firing_rate` and `rayshubskiy_recording` in `backend/src/digitalfly/compare.py` are adapted from the authors' secondary analysis code ([wilson-lab/rayshubskiy_elife_102230_secondary_analysis_code](https://github.com/wilson-lab/rayshubskiy_elife_102230_secondary_analysis_code), Copyright (c) 2025 Wilson Lab, MIT). The notice is in [NOTICE](../NOTICE).
