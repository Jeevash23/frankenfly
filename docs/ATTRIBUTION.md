# Upstream attribution

- **NeLy-EPFL FlyGym / NeuroMechFly 2.1.0**, Apache License 2.0. [Source and authors](https://github.com/NeLy-EPFL/flygym/tree/v2.1.0). [Local license](FLYGYM-LICENSE.txt). The body construction, reset posture and upstream controller usage in `scripts/smoke_flygym.py` and `backend/src/digitalfly/simulation/engines.py` follow [tutorial 4d](https://neuromechfly.org/tutorials/4d_turning_controller/). This project changes the ground colors and camera for display; the standard body/controller remains upstream code. Package-distributed meshes/data keep their package license and attribution. Nothing is redistributed here outside the normal installed package.
- **MuJoCo**, accessed through its installed package and FlyGym; retains its upstream license. [Official source](https://github.com/google-deepmind/mujoco).
- **Instrument Serif** and **DM Sans**, locally served Fontsource distributions, SIL Open Font License. [Instrument Serif license](INSTRUMENT-SERIF-LICENSE.txt), [DM Sans license](DM-SANS-LICENSE.txt).
- **Lucide icons**, from the installed `lucide-react` package (ISC). React, Vite and other packages retain their package licenses; versions and integrity hashes are in the frontend lockfile.

The DigitalFly neural matrices, sensor approximation, interface, worker, and application code are custom engineered components. No biological neural identities or connectome weights are attributed to them.


## Anatomical samples added in v0.2

MaleCNS v1.0 reconstructions: FlyEM/Janelia, Cambridge, MRC LMB and Google, CC BY 4.0. Female FAFB/FlyWire reconstructions: FlyWire Consortium and original imaging/reconstruction authors, via the Bates/Lee lab compilation; public-release terms CC BY-NC 4.0. Cross-matched cell identities: authors' `flyconnectome/2025malecns` mapping.

The navis-flybrains surface assets retain their upstream GPL-3.0 distribution notice at `data/atlas/sources/flybrains-LICENSE`. Original dataset attribution remains applicable. Every retained download has a URL, size and SHA-256 in `data/atlas/downloads.json`. The license of every data file is listed in [data/atlas/LICENSE.md](../data/atlas/LICENSE.md); none of it is covered by the project's Apache-2.0 license. See [full source and license details](RESEARCH.md).
