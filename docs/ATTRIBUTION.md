# Upstream attribution

- **NeLy-EPFL FlyGym / NeuroMechFly 2.1.0**, Apache License 2.0. [Source and authors](https://github.com/NeLy-EPFL/flygym/tree/v2.1.0). [Local license](FLYGYM-LICENSE.txt). The body construction, reset posture and upstream controller usage in `scripts/smoke_flygym.py` and `backend/src/digitalfly/simulation/engines.py` follow [tutorial 4d](https://neuromechfly.org/tutorials/4d_turning_controller/). This project changes the ground colors and camera for display; the standard body/controller remains upstream code. Package-distributed meshes/data keep their package license and attribution. Nothing is redistributed here outside the normal installed package.
- **MuJoCo**, accessed through its installed package and FlyGym; retains its upstream license. [Official source](https://github.com/google-deepmind/mujoco).
- **Instrument Serif** and **DM Sans**, locally served Fontsource distributions, SIL Open Font License. [Instrument Serif license](INSTRUMENT-SERIF-LICENSE.txt), [DM Sans license](DM-SANS-LICENSE.txt).
- **Lucide icons**, from the installed `lucide-react` package (ISC). React, Vite and other packages retain their package licenses; versions and integrity hashes are in the frontend lockfile.

The engineered model's neural matrices, the sensor approximation, interface, worker and application code are custom engineered components. No biological neural identities or connectome weights are attributed to them. `fast_turning_controller` and `ContactForces` in `backend/src/digitalfly/simulation/engines.py` re-implement FlyGym 2.1.0's `HybridController.step`, `HybridTurningController.step` and `Simulation.get_bodysegment_contact_forces` (Apache-2.0) with precomputed lookups and the same arithmetic.


## Anatomical samples added in v0.2

MaleCNS v1.0 reconstructions: FlyEM/Janelia, Cambridge, MRC LMB and Google, CC BY 4.0. Female FAFB/FlyWire reconstructions: FlyWire Consortium and original imaging/reconstruction authors, via the Bates/Lee lab compilation; public-release terms CC BY-NC 4.0. Cross-matched cell identities: authors' `flyconnectome/2025malecns` mapping.

The navis-flybrains surface assets retain their upstream GPL-3.0 distribution notice at `data/atlas/sources/flybrains-LICENSE`. Original dataset attribution remains applicable. Every retained download has a URL, size and SHA-256 in `data/atlas/downloads.json`. The license of every data file is listed in [data/atlas/LICENSE.md](../data/atlas/LICENSE.md); none of it is covered by the project's Apache-2.0 license. See [full source and license details](RESEARCH.md).

## Connectome data added in v0.3

`data/circuits/fafb783-dna02.json` is derived from FlyWire FAFB v783: the FlyWire Consortium's reconstruction (Dorkenwald et al. 2024, *Nature*) and annotations (Schlegel et al. 2024, *Nature*), neurotransmitter predictions by Eckstein et al. (2024, *Cell*), the Bates/Lee lab's harmonized metadata compilation ([sjcabs/fly_connectome_data_tutorial](https://github.com/sjcabs/fly_connectome_data_tutorial), code MIT) and the v783 connectivity table published with Shiu et al. (2024, *Nature*; [philshiu/Drosophila_brain_model](https://github.com/philshiu/Drosophila_brain_model), code MIT). The data is CC BY-NC 4.0, for non-commercial use only. The sign rule for acetylcholine, GABA and glutamate follows Shiu et al.; the DNa02 steering direction follows Rayshubskiy et al. (2025, *eLife* 13:RP102230). Sources, sizes and hashes are in `data/circuits/downloads.json`; licensing in [data/circuits/LICENSE.md](../data/circuits/LICENSE.md).
