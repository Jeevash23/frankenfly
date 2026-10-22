# Data license for `data/circuits/`

The circuit files and FlyVis bridges in this folder are built from FlyWire FAFB v783 data. **They are not covered by this project's Apache-2.0 license.** They keep the license of their source data. So does every circuit or bridge you build yourself into `data/circuits/local/` (ignored by git).

| Files | Source | License |
| --- | --- | --- |
| `fafb783-dna02.json`, `fafb783-steering.json`, their side-balanced versions `fafb783-dna02-balanced.json` and `fafb783-steering-balanced.json`, and locally built circuits (neuron identities, cell types, sides, predicted transmitters and synapse counts) | FlyWire FAFB v783, through the Bates/Lee lab [harmonized metadata](https://github.com/sjcabs/fly_connectome_data_tutorial) and the connectivity table shipped with [Shiu et al. 2024](https://github.com/philshiu/Drosophila_brain_model) | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/), non-commercial ([FlyWire terms](https://home.flywire.ai/guidelines)) |
| `fafb783-dna02.flyvis.json`, `fafb783-steering.flyvis.json`, `fafb783-dna02-balanced.flyvis.json`, `fafb783-steering-balanced.flyvis.json` and locally built `*.flyvis.json` bridges (FlyWire v783 synapse counts from optic-lobe cell types onto each circuit's visual projection neurons, by eye) | The same FlyWire v783 sources. Only the list of FlyVis cell-type names comes from FlyVis 1.2.0 (MIT); no FlyVis code, weights or connectivity is included | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/), non-commercial ([FlyWire terms](https://home.flywire.ai/guidelines)) |
| `downloads.json`, `LICENSE.md` | Project metadata: source URLs, releases, sizes and SHA-256 hashes | Apache-2.0, with the rest of the project |

Every circuit and bridge file also states its license, attribution and sources in its own header (`provenance` in circuits; `license`, `attribution` and `sources` in bridges).

The raw downloads are not redistributed. `scripts/build_circuit.py` fetches them into the ignored `.cache/circuits/` folder and checks their hashes against `downloads.json`. The code of the two upstream repositories is MIT-licensed; DigitalFly uses their data files only, not their code.

## Commercial use

The circuit and bridge files are licensed for **non-commercial use only**. Anyone using DigitalFly commercially must remove or replace them, and the connectome model and FlyVis eyes with them. The engineered six-unit model does not use them.

## Credit

If you publish work that uses these files, credit the FlyWire Consortium and cite:

- Dorkenwald S. et al. (2024) Neuronal wiring diagram of an adult brain. *Nature* 634:124–138. [doi:10.1038/s41586-024-07558-y](https://doi.org/10.1038/s41586-024-07558-y)
- Schlegel P. et al. (2024) Whole-brain annotation and multi-connectome cell typing of *Drosophila*. *Nature* 634:139–152. [doi:10.1038/s41586-024-07686-5](https://doi.org/10.1038/s41586-024-07686-5)
- Eckstein N. et al. (2024) Neurotransmitter classification from electron microscopy images at synaptic sites in *Drosophila melanogaster*. *Cell* 187:2574–2594 (transmitter predictions). [doi:10.1016/j.cell.2024.03.016](https://doi.org/10.1016/j.cell.2024.03.016)
- Shiu P.K. et al. (2024) A *Drosophila* computational brain model reveals sensorimotor processing. *Nature* 634:210–219 (connectivity table). [doi:10.1038/s41586-024-07763-9](https://doi.org/10.1038/s41586-024-07763-9)
- Zheng Z. et al. (2018) A complete electron microscopy volume of the brain of adult *Drosophila melanogaster*. *Cell* 174:730–743 (the FAFB volume). [doi:10.1016/j.cell.2018.06.019](https://doi.org/10.1016/j.cell.2018.06.019)

If you use the FlyVis bridges, also cite Lappalainen J.K. et al. (2024) Connectome-constrained networks predict neural activity across the fly visual system. *Nature* 634:1132–1140. [doi:10.1038/s41586-024-07939-3](https://doi.org/10.1038/s41586-024-07939-3)

The [research guide](../../docs/RESEARCH.md#the-connectome-model) explains how the files are built and used, and [FlyVis eyes](../../docs/RESEARCH.md#flyvis-eyes) how the bridges are.
