# Data license for `data/circuits/`

`fafb783-dna02.json` and `fafb783-steering.json` are built from FlyWire FAFB v783 data. **They are not covered by this project's Apache-2.0 license.** They keep the license of their source data. So does every circuit you build yourself into `data/circuits/local/` (ignored by git).

| Files | Source | License |
| --- | --- | --- |
| `fafb783-dna02.json`, `fafb783-steering.json` and locally built circuits (neuron identities, cell types, sides, predicted transmitters and synapse counts) | FlyWire FAFB v783, through the Bates/Lee lab [harmonized metadata](https://github.com/sjcabs/fly_connectome_data_tutorial) and the connectivity table shipped with [Shiu et al. 2024](https://github.com/philshiu/Drosophila_brain_model) | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/), non-commercial ([FlyWire terms](https://home.flywire.ai/guidelines)) |
| `downloads.json`, `LICENSE.md` | Project metadata: source URLs, releases, sizes and SHA-256 hashes | Apache-2.0, with the rest of the project |

The raw downloads are not redistributed. `scripts/build_circuit.py` fetches them into the ignored `.cache/circuits/` folder and checks their hashes against `downloads.json`.

## Commercial use

The circuit files are licensed for **non-commercial use only**. Anyone using DigitalFly commercially must remove or replace them, and the connectome model with them.

## Credit

If you publish work that uses these files, credit the FlyWire Consortium and cite:

- Dorkenwald S. et al. (2024) Neuronal wiring diagram of an adult brain. *Nature* 634:124–138.
- Schlegel P. et al. (2024) Whole-brain annotation and multi-connectome cell typing of *Drosophila*. *Nature* 634:139–152.
- Eckstein N. et al. (2024) Neurotransmitter classification from electron microscopy images at synaptic sites in *Drosophila melanogaster*. *Cell* 187:2574–2594 (transmitter predictions).
- Shiu P.K. et al. (2024) A *Drosophila* computational brain model reveals sensorimotor processing. *Nature* 634:210–219 (connectivity table).
- Zheng Z. et al. (2018) A complete electron microscopy volume of the brain of adult *Drosophila melanogaster*. *Cell* 174:730–743 (the FAFB volume).

The [research guide](../../docs/RESEARCH.md#the-connectome-model) explains how the files are built and used.
