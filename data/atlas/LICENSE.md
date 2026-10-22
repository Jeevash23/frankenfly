# Data licenses for `data/atlas/`

Everything in this folder is third-party scientific data, or a display file built from it. **None of it is covered by this project's Apache-2.0 license.** Each file keeps its original license, listed below. If you reuse these files, follow those terms and credit the original authors.

| Files | Source | License |
| --- | --- | --- |
| `sources/720575940604737708.swc`, `sources/720575940622838154.swc`, `sources/720575940627652358.swc`, `sources/720575940629327659.swc`, `sources/720575940632499757.swc`, `sources/720575940635872101.swc` (six female neuron skeletons) | FAFB / FlyWire v783, via the Bates/Lee lab [compiled data](https://github.com/sjcabs/fly_connectome_data_tutorial) | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/), non-commercial ([FlyWire terms](https://home.flywire.ai/guidelines)) |
| `sources/10001.swc`, `sources/10010.swc`, `sources/10360.swc`, `sources/10783.swc`, `sources/11177.swc`, `sources/523769.swc` (six male neuron skeletons) | [MaleCNS v1.0](https://male-cns.janelia.org/download/): FlyEM/Janelia, Cambridge, MRC LMB and Google | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `sources/FAFB14.ply`, `sources/JRCFIB2022M_brain.ply`, `sources/JRCFIB2022M_vnc.ply` (brain and nerve-cord surfaces) | [navis-flybrains](https://github.com/navis-org/navis-flybrains) | GPL-3.0, full text in `sources/flybrains-LICENSE`. Credits for the original imaging datasets also apply |
| `sources/flybrains-LICENSE` | navis-flybrains' license file, unmodified | The GPL-3.0 text itself (verbatim copying permitted) |
| `female.json` | Built by `scripts/build_atlas.py` from the six female skeletons and `FAFB14.ply` | Two sections under two licenses: `neurons` CC BY-NC 4.0, `surfaces` GPL-3.0. See [combined display files](#combined-display-files) |
| `male.json` | Built by `scripts/build_atlas.py` from the six male skeletons and the two `JRCFIB2022M` surfaces | Two sections under two licenses: `neurons` CC BY 4.0, `surfaces` GPL-3.0. See [combined display files](#combined-display-files) |
| `type-mapping-excerpt.json` | Twelve neuron-to-cell-type assignments excerpted from [flyconnectome/2025malecns](https://github.com/flyconnectome/2025malecns), with the full source file's URL and SHA-256 | The source repository states no license (checked 2026-10-21). The excerpt holds only identifiers and cell-type names; cite Berg et al. 2025 (below) |
| `manifest.json`, `downloads.json`, `LICENSE.md` | Project metadata: descriptions, source URLs and SHA-256 hashes | Apache-2.0, with the rest of the project |

## Combined display files

`female.json` and `male.json` each hold two independent datasets in one JSON file, for the browser to load in one request:

- `neurons`: the six skeletons of that sex, simplified for display (degree-two chains contracted at about 2 µm of cable), with their IDs, cell types, source URLs and hashes. They keep their source license: **CC BY-NC 4.0** (FlyWire) in `female.json`, **CC BY 4.0** (MaleCNS) in `male.json`.
- `surfaces`: the navis-flybrains meshes, modified for DigitalFly v0.2 (October 2026) by clustering vertices at 4 µm and dropping degenerate faces. They keep their source license, **GPL-3.0**. The unmodified meshes (`sources/*.ply`), the license text (`sources/flybrains-LICENSE`) and the script that makes the modification (`scripts/build_atlas.py`) are all in this repository.

Neither section is derived from the other; they share a file, not content. DigitalFly treats each file as two separately licensed works stored together, and its own `license` field says so. Whether a single file holding both counts as a mere aggregate under GPL-3.0 (section 5), or as one combined work, is not settled. If `female.json` were one combined work, it could not meet both licenses at once: GPL-3.0 forbids the non-commercial restriction that CC BY-NC 4.0 requires. This is not legal advice; what it means in practice:

| If you… | `female.json` | `male.json` |
| --- | --- | --- |
| Use DigitalFly, or share a copy of this repository, for non-commercial work | Allowed. Keep this file, `sources/flybrains-LICENSE` and the sources with it | Allowed, on the same terms |
| Use it commercially | Not allowed: the `neurons` section is non-commercial. Remove the file or rebuild it without the FlyWire skeletons | Allowed if you meet both licenses: credit MaleCNS (CC BY 4.0) and keep the GPL-3.0 text and the surfaces' source available |
| Redistribute the file on its own, outside this repository | Ship both notices and the GPL-3.0 surface sources with it; better, split it (below) | Ship both notices and the GPL-3.0 surface sources with it; better, split it (below) |
| Want one license per file | Split `neurons` and `surfaces` into separate files, or rebuild them separately from `sources/` with `scripts/build_atlas.py` | The same |

The FlyWire-derived files, the six female skeletons and `female.json`, are for **non-commercial use only**. The GPL-3.0 surfaces and the CC BY 4.0 male skeletons allow commercial use under their own terms.

## Credit

When you publish work that uses these files, cite the datasets as their providers request:

- FlyWire ([guidelines](https://home.flywire.ai/guidelines)): Dorkenwald S. et al. (2024) *Nature* 634:124–138, [doi:10.1038/s41586-024-07558-y](https://doi.org/10.1038/s41586-024-07558-y), and Schlegel P. et al. (2024) *Nature* 634:139–152, [doi:10.1038/s41586-024-07686-5](https://doi.org/10.1038/s41586-024-07686-5).
- MaleCNS ([download page](https://male-cns.janelia.org/download/)) and the male/female cell-type mapping: Berg S. et al. (2025) Sexual dimorphism in the complete connectome of the *Drosophila* male central nervous system. bioRxiv, [doi:10.1101/2025.10.09.680999](https://doi.org/10.1101/2025.10.09.680999).
- navis-flybrains, and the imaging datasets behind each surface.

The [research guide](../../docs/RESEARCH.md#licensing-and-attribution) has details. Each source file's original URL, size and SHA-256 hash is recorded in `downloads.json`.
