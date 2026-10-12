# Local scientific assets

`atlas/` contains the shipped male/female anatomical samples, source URLs, SHA-256 hashes, license notices and display geometry. These are structural reconstructions, not an executable connectome. There are six selected neurons per sex (DNa02, DNp01, DNp09). They keep their original licenses, listed in [atlas/LICENSE.md](atlas/LICENSE.md), and are not covered by the project's Apache-2.0 license.

`circuits/` contains the connectome model's circuit: both DNa02 neurons and their presynaptic partners up to two hops back from FlyWire FAFB v783 (3,000 neurons, 78,615 connections), with its sources, hashes and license in `downloads.json` and [circuits/LICENSE.md](circuits/LICENSE.md). It is CC BY-NC 4.0, non-commercial. `scripts/build_circuit.py` rebuilds it; its raw downloads stay in the ignored `.cache/circuits/`.

`examples/` contains a clearly labeled synthetic connectivity-format fixture.

User imports are saved under ignored `connectivity/`. Optional FlyGym mesh caches stay under ignored `flygym-assets/`. The walking controller uses six engineered rate units by default; the connectome model uses `circuits/`. Imported graphs never drive the body.

See [research methods, source data and licensing](../docs/RESEARCH.md).
