# Data licenses for `data/atlas/`

Everything in this folder is third-party scientific data, or a display file built from it. **None of it is covered by this project's Apache-2.0 license.** Each file keeps its original license, listed below. If you reuse these files, follow those terms and credit the original authors.

| Files | Source | License |
| --- | --- | --- |
| `sources/720575940604737708.swc`, `sources/720575940622838154.swc`, `sources/720575940627652358.swc`, `sources/720575940629327659.swc`, `sources/720575940632499757.swc`, `sources/720575940635872101.swc` (six female neuron skeletons) | FAFB / FlyWire v783, via the Bates/Lee lab [compiled data](https://github.com/sjcabs/fly_connectome_data_tutorial) | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/), non-commercial ([FlyWire terms](https://home.flywire.ai/guidelines)) |
| `sources/10001.swc`, `sources/10010.swc`, `sources/10360.swc`, `sources/10783.swc`, `sources/11177.swc`, `sources/523769.swc` (six male neuron skeletons) | [MaleCNS v1.0](https://male-cns.janelia.org/download/): FlyEM/Janelia, Cambridge, MRC LMB and Google | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `sources/FAFB14.ply`, `sources/JRCFIB2022M_brain.ply`, `sources/JRCFIB2022M_vnc.ply` (brain and nerve-cord surfaces) | [navis-flybrains](https://github.com/navis-org/navis-flybrains) | GPL-3.0, notice in `sources/flybrains-LICENSE`. Credits for the original imaging datasets also apply. |
| `female.json` | Built by `scripts/build_atlas.py` from the female skeletons and `FAFB14.ply` | Its `neurons` section follows CC BY-NC 4.0; its `surfaces` section follows GPL-3.0 |
| `male.json` | Built from the male skeletons and the `JRCFIB2022M` surfaces | Its `neurons` section follows CC BY 4.0; its `surfaces` section follows GPL-3.0 |
| `type-mapping-excerpt.json` | Twelve cell-type assignments excerpted from [flyconnectome/2025malecns](https://github.com/flyconnectome/2025malecns) | See the source repository |
| `manifest.json`, `downloads.json`, `LICENSE.md` | Project metadata: descriptions, source URLs and SHA-256 hashes | Apache-2.0, with the rest of the project |

## Commercial use

The FlyWire-derived files (the six female skeletons and `female.json`) are licensed for **non-commercial use only**. Anyone using DigitalFly commercially must remove or replace them.

## Credit

When you publish work that uses these files, cite the datasets as their providers request: FlyWire ([guidelines](https://home.flywire.ai/guidelines)), MaleCNS ([download page](https://male-cns.janelia.org/download/)) and navis-flybrains. The [research guide](../../docs/RESEARCH.md#licensing-and-attribution) has details. Each source file's original URL, size and SHA-256 hash is recorded in `downloads.json`.
