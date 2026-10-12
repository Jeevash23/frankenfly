# Local scientific assets

`atlas/` contains the shipped male/female anatomical samples, source URLs, SHA-256 hashes, license notices and display geometry. These are structural reconstructions, not an executable connectome. There are six selected neurons per sex (DNa02, DNp01, DNp09). They keep their original licenses, listed in [atlas/LICENSE.md](atlas/LICENSE.md), and are not covered by the project's Apache-2.0 license.

`examples/` contains a clearly labeled synthetic connectivity-format fixture.

User imports are saved under ignored `connectivity/`. Optional FlyGym mesh caches stay under ignored `flygym-assets/`. The active walking model still has six engineered rate units.

See [research methods, source data and licensing](../docs/RESEARCH.md).
