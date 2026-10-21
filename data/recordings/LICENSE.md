# Data license for `data/recordings/`

This folder holds only metadata: `downloads.json` records each recorded-fly dataset that DigitalFly can compare with (URL, release, size, MD5 and SHA-256 hashes, license and citation). The data files themselves are not redistributed. `scripts/fetch_recording.py` downloads them into the ignored `.cache/recordings/` folder and checks their hashes. Keep raw recordings there: this folder is not ignored by git.

| File | Source | License |
| --- | --- | --- |
| `rayshubskiy2025-a2_d_13.mat` (not in the repository) | Rayshubskiy et al. 2025, Harvard Dataverse [doi:10.7910/DVN/0NCLP1](https://doi.org/10.7910/DVN/0NCLP1), version 1.2 | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| `downloads.json`, `LICENSE.md` | Project metadata | Apache-2.0, with the rest of the project |

CC0 asks for nothing, but please cite the work that produced the data:

- Rayshubskiy A., Holtz S.L., Bates A.S., Vanderbeck Q.X., Serratosa Capdevila L., Rockwell V., Wilson R.I. (2025) Neural circuit mechanisms for steering control in walking *Drosophila*. *eLife* 13:RP102230. [doi:10.7554/eLife.102230](https://doi.org/10.7554/eLife.102230)

## Analysis code

The conversion to firing rates (`detect_spikes`, `firing_rate` and `rayshubskiy_recording` in `backend/src/digitalfly/compare.py`) is adapted from the authors' secondary analysis code, [wilson-lab/rayshubskiy_elife_102230_secondary_analysis_code](https://github.com/wilson-lab/rayshubskiy_elife_102230_secondary_analysis_code), Copyright (c) 2025 Wilson Lab, MIT License. That notice and the MIT permission text are reproduced in [NOTICE](../../NOTICE); see also [docs/ATTRIBUTION.md](../../docs/ATTRIBUTION.md) and the [research guide](../../docs/RESEARCH.md#comparing-with-real-flies).
