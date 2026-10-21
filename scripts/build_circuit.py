"""Build the FlyWire FAFB v783 DNa02 input subcircuit: data/circuits/fafb783-dna02.json.

Everything this script writes is data-derived structure: neuron identities, cell types,
sides, predicted transmitters and synapse counts. It does not choose signs, gains or
dynamics; the runtime model applies its own declared assumptions to these counts.

Sources (pinned, both FlyWire v783):
  * Bates/Lee lab harmonized FAFB metadata (cell types, sides, transmitter predictions),
    downloaded whole and checked by SHA-256.
  * Shiu et al. 2024 connectivity table. Only four columns are needed, so only their
    Parquet column chunks (plus the footer) are fetched with HTTP range requests, about
    half of the file. The pinned commit and git blob hash identify the whole upstream file;
    the SHA-256 covers exactly the bytes downloaded.

Raw downloads stay in the ignored cache (.cache/circuits/). The build needs the optional
data dependencies, which the app itself never imports:

    backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements-data.lock
    backend/.venv/bin/python scripts/build_circuit.py
"""
import argparse
import hashlib
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache/circuits"
OUT_DIR = ROOT / "data/circuits"
OUTPUT = OUT_DIR / "fafb783-dna02.json"
DOWNLOADS = OUT_DIR / "downloads.json"
SWC = ROOT / "data/atlas/sources"

# FlyWire v783 root IDs of the two DNa02 neurons, as shipped in the anatomical atlas.
DNA02 = ("720575940604737708", "720575940629327659")
FLYWIRE_LICENSE = "CC BY-NC 4.0 (FlyWire public-release terms): non-commercial use only"
SOURCES = {
    "meta": {
        "name": "fafb_783_meta.feather",
        "url": "https://storage.googleapis.com/lee-lab_brain-and-nerve-cord-fly-connectome/compiled_data/fafb_783/fafb_783_meta.feather",
        "release": "FAFB / FlyWire v783, harmonized to the BANC schema",
        "provider": "Bates/Lee lab compiled connectome data (github.com/sjcabs/fly_connectome_data_tutorial)",
        "documentation": "https://github.com/sjcabs/fly_connectome_data_tutorial/blob/main/data/dataset_documentation/fafb_data.md",
        "gcs_generation": "1787944265562460",
        "license": FLYWIRE_LICENSE + "; the compilation's code is MIT",
        "content": "Per-neuron cell type, super class, side and predicted neurotransmitter",
        "download": "whole file",
    },
    "connectivity": {
        "name": "Connectivity_783.parquet",
        "url": "https://raw.githubusercontent.com/philshiu/Drosophila_brain_model/61555bc764aebab90e37a56fa1f312269fa4dde1/Connectivity_783.parquet",
        "release": "FlyWire v783 connectivity shipped with Shiu et al. 2024 (Nature 634:210-219)",
        "provider": "github.com/philshiu/Drosophila_brain_model",
        "git_commit": "61555bc764aebab90e37a56fa1f312269fa4dde1",
        "git_blob_sha1": "d386555d1a5f40ebfa1380bcb05b1fab044855fd",
        "upstream_bytes": 100804642,
        "license": FLYWIRE_LICENSE + "; the repository's code is MIT",
        "content": "Synapse counts for every connected neuron pair; Shiu et al.'s own excitatory/inhibitory sign",
        "columns": ["Presynaptic_ID", "Postsynaptic_ID", "Connectivity", "Excitatory"],
        "download": "Parquet footer plus the column chunks of the listed columns, by HTTP range requests",
    },
}
CITATIONS = [
    "Dorkenwald S. et al. (2024) Neuronal wiring diagram of an adult brain. Nature 634:124-138. doi:10.1038/s41586-024-07558-y",
    "Schlegel P. et al. (2024) Whole-brain annotation and multi-connectome cell typing of Drosophila. Nature 634:139-152. doi:10.1038/s41586-024-07686-5",
    "Eckstein N. et al. (2024) Neurotransmitter classification from electron microscopy images at synaptic sites in Drosophila melanogaster. Cell 187:2574-2594. doi:10.1016/j.cell.2024.03.016",
    "Shiu P.K. et al. (2024) A Drosophila computational brain model reveals sensorimotor processing. Nature 634:210-219. doi:10.1038/s41586-024-07763-9",
    "Zheng Z. et al. (2018) A complete electron microscopy volume of the brain of adult Drosophila melanogaster. Cell 174:730-743. doi:10.1016/j.cell.2018.06.019",
]
ATTRIBUTION = ("FlyWire Consortium (Princeton University and collaborating labs) for the FAFB/FlyWire "
               "reconstruction and annotations; Eckstein et al. for transmitter predictions; Bates/Lee lab "
               "for the harmonized metadata; Shiu et al. for the v783 connectivity table.")
TRANSMITTERS = {"acetylcholine": "acetylcholine", "ach": "acetylcholine", "gaba": "gaba",
                "glutamate": "glutamate", "glut": "glutamate", "glu": "glutamate",
                "dopamine": "dopamine", "da": "dopamine", "serotonin": "serotonin",
                "ser": "serotonin", "5ht": "serotonin", "5-ht": "serotonin",
                "octopamine": "octopamine", "oct": "octopamine", "oa": "octopamine"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url, start=None, end=None, path=None, size=None, missing_ok=False):
    """GET a URL and return the body, or its byte range [start, end), or stream it into `path` (resuming a partial
    file there; `size` marks it complete) and return the path. Network errors are retried with backoff from where
    the transfer stopped (digitalfly.data.downloads). A download that still fails ends the build with a one-line
    message, except a 404 with missing_ok, which returns None."""
    if str(ROOT / "backend/src") not in sys.path:
        sys.path.insert(0, str(ROOT / "backend/src"))
    from digitalfly.data.downloads import DownloadError, download, fetch_bytes
    try:
        if path is not None:
            return download(url, path, size, agent="digitalfly-build-circuit")
        return fetch_bytes(url, start, end, agent="digitalfly-build-circuit")
    except DownloadError as exc:
        if missing_ok and exc.status == 404:
            return None
        sys.exit(f"Download failed: {exc}. Run the command again to resume.")


def write_atomic(path, write):
    """Write through `write(handle)` to a temporary file next to `path`, then rename it into place, so a
    crash or a terminated build never leaves a truncated file or loses the previous one."""
    part = path.with_name(f".{path.name}.{os.getpid()}.part")  # hidden from the circuit list
    try:
        with part.open("wb") as handle:
            write(handle)
        os.replace(part, path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def recorded(name):
    if DOWNLOADS.is_file():
        for item in json.loads(DOWNLOADS.read_text()):
            if item["name"] == name:
                return item
    return None


def meta_file(offline):
    """Whole-file download of the harmonized metadata, verified against the recorded hash."""
    source = SOURCES["meta"]
    path = CACHE / source["name"]
    if not path.is_file():
        if offline:
            sys.exit(f"Missing {path}. Run once without --offline to download it ({source['url']}).")
        # Ask for the recorded GCS generation, so an overwritten upstream object is not fetched by accident.
        # If that generation is no longer served, the current object is fetched and must match the recorded hash.
        pinned = f"{source['url']}?generation={source['gcs_generation']}"
        print(f"Downloading {pinned} …", flush=True)
        CACHE.mkdir(parents=True, exist_ok=True)
        part, size = path.with_suffix(".part"), (recorded(source["name"]) or {}).get("bytes")
        if fetch(pinned, path=part, size=size, missing_ok=True) is None:
            print(f"Generation {source['gcs_generation']} is no longer served; trying {source['url']} …", flush=True)
            part.unlink(missing_ok=True)  # never resume another object's bytes
            fetch(source["url"], path=part, size=size)
        part.rename(path)
    data = path.read_bytes()
    record = {**source, "bytes": len(data), "sha256": sha256(data)}
    previous = recorded(source["name"])
    if previous and previous["sha256"] != record["sha256"]:
        sys.exit(f"{path.name} differs from the recorded download (sha256 {previous['sha256']}). "
                 "Review the upstream change before rebuilding; delete the cached file to re-download.")
    return path, record


class PartialFile(io.RawIOBase):
    """A read-only view of a remote file that serves only byte ranges already downloaded."""

    def __init__(self, size, ranges):
        self.size, self.ranges, self.pos = size, sorted(ranges.items()), 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        return self.pos

    def readinto(self, buffer):
        n = min(len(buffer), self.size - self.pos)
        if n <= 0:
            return 0
        for start, data in self.ranges:
            if start <= self.pos and self.pos + n <= start + len(data):
                buffer[:n] = data[self.pos - start:self.pos - start + n]
                self.pos += n
                return n
        raise IOError(f"Byte range {self.pos}-{self.pos + n} was not downloaded.")


def connectivity_columns(offline):
    """Fetch (or reuse) the footer and the needed column chunks of the Shiu et al. table."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    source = SOURCES["connectivity"]
    blob_path = CACHE / (source["name"] + ".ranges")
    index_path = CACHE / (source["name"] + ".ranges.json")
    size = source["upstream_bytes"]
    if not blob_path.is_file() or not index_path.is_file():
        if offline:
            sys.exit(f"Missing {blob_path}. Run once without --offline to download the column chunks.")
        CACHE.mkdir(parents=True, exist_ok=True)
        tail_start = size - 65536
        print(f"Reading the Parquet footer of {source['url']} …", flush=True)
        tail = fetch(source["url"], tail_start, size)
        footer = pq.ParquetFile(pa.PythonFile(PartialFile(size, {tail_start: tail}), mode="r")).metadata
        wanted = set(source["columns"])
        spans = []
        for g in range(footer.num_row_groups):
            group = footer.row_group(g)
            for c in range(group.num_columns):
                column = group.column(c)
                if column.path_in_schema in wanted:
                    start = column.dictionary_page_offset if column.has_dictionary_page else column.data_page_offset
                    spans.append([start, start + column.total_compressed_size])
        merged = []
        for start, end in sorted(spans):
            if merged and merged[-1][1] == start:
                merged[-1][1] = end
            else:
                merged.append([start, end])
        total = sum(end - start for start, end in merged)
        print(f"Fetching {len(merged)} column-chunk ranges, {total / 1e6:.1f} MB of {size / 1e6:.1f} MB …", flush=True)
        ranges = [[tail_start, size]]
        chunks = [tail]
        for start, end in merged:
            if end > tail_start:
                raise IOError("A column chunk overlaps the footer read; adjust the footer window.")
            chunks.append(fetch(source["url"], start, end))
            ranges.append([start, end])
        order = np.argsort([r[0] for r in ranges])
        blob = b"".join(chunks[i] for i in order)
        ranges = [ranges[i] for i in order]
        blob_path.with_suffix(".part").write_bytes(blob)
        blob_path.with_suffix(".part").rename(blob_path)
        index_path.write_text(json.dumps({"url": source["url"], "upstream_bytes": size, "ranges": ranges,
                                          "sha256": sha256(blob)}, indent=1))
    index = json.loads(index_path.read_text())
    blob = blob_path.read_bytes()
    if sha256(blob) != index["sha256"]:
        sys.exit(f"{blob_path.name} is corrupted; delete it and {index_path.name} to download again.")
    previous = recorded(source["name"])
    if previous and previous["sha256"] != index["sha256"]:
        sys.exit(f"The cached column chunks differ from the recorded download (sha256 {previous['sha256']}).")
    pieces, offset = {}, 0
    for start, end in index["ranges"]:
        pieces[start] = blob[offset:offset + end - start]
        offset += end - start
    parquet = pq.ParquetFile(pa.PythonFile(PartialFile(size, pieces), mode="r"), pre_buffer=False)
    table = parquet.read(columns=source["columns"], use_threads=False)
    record = {**source, "bytes": len(blob), "sha256": index["sha256"], "ranges": len(index["ranges"]),
              "rows": parquet.metadata.num_rows, "row_groups": parquet.metadata.num_row_groups,
              "hash_scope": "SHA-256 of the downloaded byte ranges (footer and listed column chunks) in file order"}
    return {name: table.column(name).to_numpy() for name in source["columns"]}, record


def text(values):
    return np.array(["" if v is None else str(v) for v in values], dtype=object)


def load_meta(path):
    import pyarrow.feather as feather
    table = feather.read_table(path)
    names = set(table.column_names)
    needed = ["fafb_783_id", "side", "super_class", "cell_class", "cell_sub_class", "cell_type",
              "neurotransmitter_predicted", "neurotransmitter_score"]
    missing = [n for n in needed if n not in names]
    if missing:
        sys.exit(f"Metadata columns missing: {missing}. Available: {sorted(names)}")
    meta = {n: text(table.column(n).to_pylist()) for n in needed if n != "neurotransmitter_score"}
    meta["neurotransmitter_score"] = np.array([np.nan if v is None else float(v)
                                               for v in table.column("neurotransmitter_score").to_pylist()])
    meta["id"] = np.array([int(v) for v in meta.pop("fafb_783_id")], dtype=np.int64)
    if len(np.unique(meta["id"])) != len(meta["id"]):
        sys.exit("Metadata contains duplicate neuron identifiers.")
    return meta, table.num_rows


def transmitter(label):
    key = label.strip().lower().replace(" ", "")
    return TRANSMITTERS.get(key, "unknown")


def soma_x(neuron_id):
    """x coordinate (µm) of the SWC root node, the soma in FlyWire skeletons."""
    path = SWC / f"{neuron_id}.swc"
    if not path.is_file():
        return None
    rows = np.loadtxt(path)
    return float(rows[rows[:, 6] == -1][0, 2] / 1000)


def select_indices(pre, post, count, seeds, n, threshold, hops, cap, whole=False):
    """Choose neurons and connections on integer neuron indices 0..n-1. Vectorised.

    Hop h holds the presynaptic partners (connections with at least `threshold` synapses) of
    hop h-1 that are not already included. Every seed and hop-1 neuron is kept. If more
    neurons qualify than `cap`, the deepest layers are trimmed to the neurons with the
    strongest path to a seed, where a path's strength multiplies the input fractions of its
    connections (synapses on the connection / all synapses onto the postsynaptic neuron).
    The connections are the induced subgraph: every kept pair with at least `threshold`.

    With `whole`, hops run until no new neuron is reached, nothing is capped, and every other
    neuron with a strong connection is appended (hop -1: no path to a seed).
    """
    pre, post, seeds = (np.asarray(a, dtype=np.int64) for a in (pre, post, seeds))
    count = np.asarray(count, dtype=np.float64)
    total_in = np.bincount(post, weights=count, minlength=n)
    strong = count >= threshold
    s_pre, s_post = pre[strong], post[strong]
    fraction = count[strong] / total_in[s_post]
    strength = np.zeros(n)
    strength[seeds] = 1.0
    known = np.zeros(n, dtype=bool)
    known[seeds] = True
    frontier = known.copy()
    layers = [seeds]
    for _ in range(n if whole else hops):
        edge = frontier[s_post] & ~known[s_pre]
        best = np.zeros(n)
        np.maximum.at(best, s_pre[edge], fraction[edge] * strength[s_post[edge]])
        frontier = best > 0
        if not frontier.any():
            break
        strength[frontier] = best[frontier]
        known |= frontier
        layers.append(np.flatnonzero(frontier))

    kept_layers, dropped, budget = [seeds], np.array([], dtype=np.int64), (n if whole else cap) - len(seeds)
    for depth, layer in enumerate(layers[1:], start=1):
        if len(layer) <= budget or depth == 1:
            kept_layers.append(layer)
            budget -= len(layer)
            continue
        ranked = layer[np.lexsort((layer, -strength[layer]))]
        keep = max(budget, 0)
        kept_layers.append(np.sort(ranked[:keep]))
        dropped = np.concatenate([dropped, ranked[keep:]])
        budget -= keep
    hop = np.concatenate([np.full(len(l), h) for h, l in enumerate(kept_layers)])
    kept = np.concatenate(kept_layers)
    if whole:
        connected = np.zeros(n, dtype=bool)
        connected[s_pre] = connected[s_post] = True
        connected[kept] = False
        rest = np.flatnonzero(connected)
        kept, hop = np.concatenate([kept, rest]), np.concatenate([hop, np.full(len(rest), -1)])
    position = np.full(n, -1, dtype=np.int64)
    position[kept] = np.arange(len(kept))
    mask = strong & (position[pre] >= 0) & (position[post] >= 0)
    e_pre, e_post, e_count = position[pre[mask]], position[post[mask]], count[mask].astype(np.int64)
    order = np.lexsort((e_pre, e_post))
    # Compared with the strongest dropped path: the weakest neuron of the deepest hop that kept any.
    deepest = next((layer for layer in reversed(kept_layers[1:]) if len(layer)), None)
    weakest = float(strength[deepest].min()) if len(dropped) and deepest is not None else None
    return {"kept": kept, "hop": hop, "strength": strength[kept],
            "by_hop": [int(len(l)) for l in kept_layers],
            "candidates": int(sum(len(l) for l in layers)), "dropped": dropped,
            "dropped_strength": strength[dropped], "weakest_kept_strength": weakest,
            "edges": (e_pre[order], e_post[order], e_count[order])}


def select_subcircuit(pre, post, count, seeds, threshold, hops, cap, whole=False):
    """`select_indices` on neuron identifiers instead of indices; kept/dropped are identifiers."""
    pre, post, seeds = (np.asarray(a, dtype=np.int64) for a in (pre, post, seeds))
    ids, inverse = np.unique(np.concatenate([seeds, pre, post]), return_inverse=True)
    k, m = len(seeds), len(pre)
    chosen = select_indices(inverse[k:k + m], inverse[k + m:], count, inverse[:k], len(ids),
                            threshold, hops, cap, whole)
    chosen["kept"], chosen["dropped"] = ids[chosen["kept"]], ids[chosen["dropped"]]
    return chosen


def build(threshold, hops, cap, offline):
    meta_path, meta_record = meta_file(offline)
    columns, conn_record = connectivity_columns(offline)
    meta, meta_rows = load_meta(meta_path)
    pre = columns["Presynaptic_ID"].astype(np.int64)
    post = columns["Postsynaptic_ID"].astype(np.int64)
    count = columns["Connectivity"].astype(np.int64)
    shiu_sign = columns["Excitatory"].astype(np.int64)
    if count.min() < 1:
        sys.exit("Connectivity table contains non-positive synapse counts.")

    order = np.argsort(meta["id"])
    sorted_ids = meta["id"][order]

    def meta_index(ids):
        ids = np.asarray(ids, dtype=np.int64)
        position = np.searchsorted(sorted_ids, ids)
        position[position >= len(sorted_ids)] = 0
        return np.where(sorted_ids[position] == ids, order[position], -1)

    dn_meta = meta_index([int(i) for i in DNA02])
    if (dn_meta < 0).any():
        sys.exit("A DNa02 identifier is missing from the v783 metadata.")
    for i, m in zip(DNA02, dn_meta):
        if meta["cell_type"][m] != "DNa02":
            sys.exit(f"{i} is typed {meta['cell_type'][m]!r}, not DNa02, in the metadata.")
    sides = {i: meta["side"][m] for i, m in zip(DNA02, dn_meta)}
    if sorted(sides.values()) != ["left", "right"]:
        sys.exit(f"Expected one left and one right DNa02, found {sides}.")
    left_id = next(i for i, s in sides.items() if s == "left")
    right_id = next(i for i, s in sides.items() if s == "right")
    soma = {i: soma_x(i) for i in DNA02}

    chosen = select_subcircuit(pre, post, count, [int(left_id), int(right_id)], threshold, hops, cap)
    kept = chosen["kept"]
    e_pre, e_post, e_count = chosen["edges"]
    for hop, size in enumerate(chosen["by_hop"]):
        print(f"hop {hop}: {size} neurons kept", flush=True)
    kept_meta = meta_index(kept)

    # Shiu et al.'s own sign for each presynaptic neuron, kept only for comparison.
    sign_of = {}
    from_kept = np.isin(pre, kept)
    for a, s in zip(pre[from_kept].tolist(), shiu_sign[from_kept].tolist()):
        sign_of.setdefault(a, set()).add(s)

    def field(name, k):
        return meta[name][k] if k >= 0 else ""

    cell_types, super_classes, classes, nts, side_values, scores, shiu = [], [], [], [], [], [], []
    for k in kept_meta.tolist():
        label = field("cell_type", k)
        if not label:
            base = field("cell_sub_class", k) or field("cell_class", k) or field("super_class", k) or "unannotated"
            label = f"{base} (untyped)"
        cell_types.append(label)
        super_classes.append(field("super_class", k) or "unknown")
        classes.append(field("cell_class", k))
        nts.append(transmitter(field("neurotransmitter_predicted", k)))
        side_values.append(field("side", k) or "unknown")
        score = meta["neurotransmitter_score"][k] if k >= 0 else np.nan
        scores.append(None if not np.isfinite(score) else round(float(score), 3))
    for i in kept.tolist():
        values = sign_of.get(i, set())
        shiu.append(int(next(iter(values))) if len(values) == 1 else 0)

    def lookup(values):
        table = sorted(set(values))
        index = {v: k for k, v in enumerate(table)}
        return table, [index[v] for v in values]

    type_table, type_index = lookup(cell_types)
    super_table, super_index = lookup(super_classes)
    class_table, class_index = lookup(classes)
    nt_table, nt_index = lookup(nts)
    side_table, side_index = lookup(side_values)

    shiu_rule = {"acetylcholine": 1, "gaba": -1, "glutamate": -1, "dopamine": 1, "serotonin": 1, "octopamine": 1}
    compared = [(nts[k], shiu[k]) for k in range(len(kept)) if shiu[k] != 0 and nts[k] in shiu_rule]
    agreement = {"neurons_compared": len(compared),
                 "agree": int(sum(shiu_rule[nt] == s for nt, s in compared)),
                 "rule_compared": "Shiu et al. 2024: GABA and glutamate inhibitory; acetylcholine, dopamine, serotonin and octopamine excitatory"}
    is_input = np.array(super_classes) == "visual_projection"
    inputs = {side: int((is_input & (np.array(side_values) == side)).sum()) for side in ["left", "right"]}
    dropped_super, dropped_types = {}, {}
    for k in meta_index(chosen["dropped"]).tolist() if len(chosen["dropped"]) else []:
        s = field("super_class", k) or "unknown"
        dropped_super[s] = dropped_super.get(s, 0) + 1
        t = field("cell_type", k) or "untyped"
        dropped_types[t] = dropped_types.get(t, 0) + 1
    cap_report = {
        "cap": cap, "candidates": chosen["candidates"], "kept": int(len(kept)),
        "dropped": int(len(chosen["dropped"])), "binding": bool(len(chosen["dropped"])),
        "rule": ("Every DNa02 and hop-1 partner is kept. When the cap binds, the deepest hop keeps the neurons "
                 "with the strongest path to a DNa02; a path's strength multiplies the input fractions of its "
                 "connections (synapses on the connection / all synapses onto the postsynaptic neuron)."),
        "weakest_kept_path_strength": chosen["weakest_kept_strength"],
        "strongest_dropped_path_strength": float(chosen["dropped_strength"].max()) if len(chosen["dropped"]) else None,
        "dropped_by_super_class": dict(sorted(dropped_super.items(), key=lambda x: -x[1])),
        "dropped_top_cell_types": dict(sorted(dropped_types.items(), key=lambda x: -x[1])[:25]),
    }
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    previous = {item["name"]: item for item in (json.loads(DOWNLOADS.read_text()) if DOWNLOADS.is_file() else [])}
    records = []
    for record in ({**meta_record, "rows": meta_rows}, conn_record):
        records.append({**record, "retrieved_utc": previous.get(record["name"], {}).get("retrieved_utc", now)})
    import pyarrow
    circuit = {
        "format": "digitalfly-circuit", "version": 1,
        "name": "FlyWire FAFB v783 DNa02 input subcircuit",
        "kind": "Data-derived structure: identities, types, sides, predicted transmitters and synapse counts. "
                "Signs, gains and dynamics are runtime assumptions of the model that loads it.",
        "provenance": {
            "dataset": "FlyWire FAFB", "release": "v783", "specimen": "FAFB, one adult female brain", "sex": "female",
            "coverage": f"Both DNa02 neurons and their presynaptic partners up to {hops} hops back, "
                        f"connections with at least {threshold} synapses, at most {cap} neurons",
            "license": FLYWIRE_LICENSE, "non_commercial": True, "attribution": ATTRIBUTION, "citations": CITATIONS,
            "sources": records,
            "build": {"script": "scripts/build_circuit.py", "synapse_threshold": threshold, "hops": hops,
                      "neuron_cap": cap, "connections": "induced subgraph: every kept pair with at least the threshold",
                      "pyarrow": pyarrow.__version__, "numpy": np.__version__},
            "dna02": {"left": left_id, "right": right_id,
                      "side_evidence": "FlyWire side annotation in the v783 metadata",
                      "soma_x_um": soma,
                      "soma_note": "SWC root-node x in native FAFB coordinates, from the atlas skeletons"},
            "counts": {"neurons": int(len(kept)), "connections": int(len(e_count)),
                       "synapses": int(e_count.sum()), "cell_types": len(type_table),
                       "by_hop": chosen["by_hop"], "unmatched_in_metadata": int((kept_meta < 0).sum()),
                       "visual_projection_inputs": inputs},
            "cap_report": cap_report,
            "transmitters": {"source": "neurotransmitter_predicted in the harmonized metadata (Eckstein et al. 2024 predictions)",
                             "counts": {nt: nts.count(nt) for nt in nt_table},
                             "shiu_sign_comparison": agreement},
        },
        "lookups": {"cell_type": type_table, "super_class": super_table, "cell_class": class_table,
                    "transmitter": nt_table, "side": side_table},
        "neurons": {"id": [str(i) for i in kept.tolist()], "cell_type": type_index, "super_class": super_index,
                    "cell_class": class_index, "transmitter": nt_index, "transmitter_score": scores,
                    "side": side_index, "hop": [int(h) for h in chosen["hop"]],
                    "path_strength": [float(f"{v:.6g}") for v in chosen["strength"]], "shiu_sign": shiu},
        "edges": {"pre": e_pre.tolist(), "post": e_post.tolist(), "synapses": e_count.tolist()},
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_atomic(OUTPUT, lambda handle: handle.write(json.dumps(circuit, separators=(",", ":")).encode()))
    DOWNLOADS.write_text(json.dumps(records, indent=2) + "\n")
    print(json.dumps(circuit["provenance"]["counts"], indent=1))
    print("cap:", json.dumps({k: cap_report[k] for k in ["candidates", "kept", "dropped", "binding"]}))
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size / 1e6:.2f} MB), sha256 {sha256(OUTPUT.read_bytes())}")


PREPARED = CACHE / "fafb783-connectome.npz"
CATALOG = CACHE / "fafb783-catalog.json"
LOCAL_DIR = OUT_DIR / "local"
NAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
JSON_EDGE_LIMIT = 200_000  # larger circuits are written as compressed NumPy archives


def neuron_labels(meta):
    """A neuron's cell type, or its class marked as untyped: the label cell-type groups use."""
    return np.array([t or f"{sub or cls or sup or 'unannotated'} (untyped)" for t, sub, cls, sup in
                     zip(meta["cell_type"], meta["cell_sub_class"], meta["cell_class"], meta["super_class"])],
                    dtype=object)


def encode(values):
    table, index = np.unique(np.asarray(values, dtype=str), return_inverse=True)
    return table, index.astype(np.int32)


def shown(path):
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def prepare(offline):
    """Convert the cached downloads into one NumPy archive that `build` reads without pyarrow."""
    meta_path, meta_record = meta_file(offline)
    columns, conn_record = connectivity_columns(offline)
    meta, meta_rows = load_meta(meta_path)
    save_prepared(meta, columns, [{**meta_record, "rows": meta_rows}, conn_record])


def save_prepared(meta, columns, sources):
    """Write the prepared archive and the cell-type catalog from metadata and connectivity columns."""
    # Index neurons in ID order, so hop layers and ties order by FlyWire ID as in the default build.
    order = np.argsort(meta["id"])
    meta = {key: values[order] for key, values in meta.items()}
    ids = meta["id"]

    def index_of(values):
        position = np.searchsorted(ids, values)
        position[position >= len(ids)] = 0
        return np.where(ids[position] == values, position, -1)

    pre = index_of(columns["Presynaptic_ID"].astype(np.int64))
    post = index_of(columns["Postsynaptic_ID"].astype(np.int64))
    matched = (pre >= 0) & (post >= 0)
    types, type_index = encode(neuron_labels(meta))
    supers, super_index = encode(np.where(meta["super_class"] == "", "unknown", meta["super_class"]))
    classes, class_index = encode(meta["cell_class"])
    sides, side_index = encode(np.where(meta["side"] == "", "unknown", meta["side"]))
    nts, nt_index = encode([transmitter(v) for v in meta["neurotransmitter_predicted"]])
    header = {"sources": sources, "neurons": int(len(ids)),
              "connections": int(matched.sum()), "unmatched_connections": int((~matched).sum())}
    PREPARED.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        PREPARED, header=np.array(json.dumps(header)), neuron_id=ids, cell_type=type_index,
        super_class=super_index, cell_class=class_index, side=side_index, transmitter=nt_index,
        transmitter_score=meta["neurotransmitter_score"].astype(np.float32),
        pre=pre[matched].astype(np.int32), post=post[matched].astype(np.int32),
        synapses=columns["Connectivity"][matched].astype(np.int32),
        shiu_sign=columns["Excitatory"][matched].astype(np.int8),
        lookup_cell_type=types, lookup_super_class=supers, lookup_cell_class=classes,
        lookup_side=sides, lookup_transmitter=nts)
    counts = np.bincount(type_index, minlength=len(types))
    left = np.bincount(type_index, weights=sides[side_index] == "left", minlength=len(types))
    right = np.bincount(type_index, weights=sides[side_index] == "right", minlength=len(types))
    first_super = np.zeros(len(types), dtype=np.int64)
    first_super[type_index[::-1]] = super_index[::-1]
    catalog = [{"cell_type": str(t), "neurons": int(c), "left": int(l), "right": int(r),
                "super_class": str(supers[sc])} for t, c, l, r, sc in zip(types, counts, left, right, first_super)]
    CATALOG.write_text(json.dumps({"release": "FlyWire FAFB v783", "cell_types": catalog}, separators=(",", ":")))
    print(f"prepared {shown(PREPARED)}: {len(ids):,} neurons, {int(matched.sum()):,} connections "
          f"({int((~matched).sum()):,} without metadata left out), {len(types):,} cell types")


def load_prepared():
    if not PREPARED.is_file():
        sys.exit(f"Missing {shown(PREPARED)}. Run `scripts/build_circuit.py prepare` first "
                 "(it needs the build-only data lock and the FlyWire downloads, about 61 MB).")
    with np.load(PREPARED, allow_pickle=False) as archive:
        data = {key: archive[key] for key in archive.files}
    data["header"] = json.loads(str(data["header"]))
    return data


def resolve_seeds(data, tokens):
    """Seeds by FlyWire root ID or exact cell-type name, in the given order, left before right."""
    ids, labels, sides = data["neuron_id"], data["lookup_cell_type"], data["lookup_side"]
    side_rank = {"left": 0, "right": 1}
    seeds, records = [], []
    for token in tokens:
        token = token.strip()
        if token.isdigit():
            members = np.flatnonzero(ids == int(token))
            if not len(members):
                sys.exit(f"Neuron {token} is not in the FlyWire v783 metadata.")
        else:
            matches = np.flatnonzero(labels == token)
            if not len(matches):
                sys.exit(f"No cell type is named {token!r}. Names are case-sensitive; see {CATALOG.name}.")
            members = np.flatnonzero(data["cell_type"] == matches[0])
        members = sorted(members.tolist(), key=lambda i: (side_rank.get(str(sides[data["side"][i]]), 2), int(ids[i])))
        members = [m for m in members if m not in seeds]
        seeds.extend(members)
        record = {"seed": token, "cell_types": sorted({str(labels[data["cell_type"][m]]) for m in members})}
        for side in ["left", "right"]:
            record[side] = [str(ids[m]) for m in members if str(sides[data["side"][m]]) == side]
        record["other"] = [str(ids[m]) for m in members if str(sides[data["side"][m]]) not in side_rank]
        records.append(record)
    return np.array(seeds, dtype=np.int64), records


def build_custom(name, tokens, hops, threshold, cap, whole, fmt, committed):
    """Select a circuit around any seeds from the prepared archive (NumPy only) and write format 2."""
    import re
    if not re.fullmatch(NAME_PATTERN, name) or name in ("local", "downloads"):
        sys.exit("Use a circuit name of lower-case letters, digits, dots, dashes or underscores.")
    if name.endswith(".flyvis"):
        sys.exit("Circuit names cannot end in .flyvis: that suffix marks a circuit's FlyVis bridge.")
    if not committed and any((OUT_DIR / f"{name}{suffix}").exists() for suffix in (".json", ".npz")):
        sys.exit(f"{name} is a built-in circuit. Choose another name for a local build.")
    data = load_prepared()
    # Retrieval dates come from the recorded downloads when the hashes match.
    recorded_sources = {item["name"]: item for item in json.loads(DOWNLOADS.read_text())} if DOWNLOADS.is_file() else {}
    sources = [{**source, **({"retrieved_utc": recorded_sources[source["name"]]["retrieved_utc"]}
                             if recorded_sources.get(source["name"], {}).get("sha256") == source.get("sha256") else {})}
               for source in data["header"]["sources"]]
    seeds, records = resolve_seeds(data, tokens)
    n = len(data["neuron_id"])
    chosen = select_indices(data["pre"], data["post"], data["synapses"], seeds, n, threshold, hops, cap, whole)
    kept = chosen["kept"]
    e_pre, e_post, e_count = chosen["edges"]
    position = np.full(n, -1, dtype=np.int64)
    position[kept] = np.arange(len(kept))
    lookups, columns = {}, {}
    for key in ["cell_type", "super_class", "cell_class", "transmitter", "side"]:
        table, index = np.unique(data[key][kept], return_inverse=True)
        lookups[key] = [str(v) for v in data["lookup_" + key][table]]
        columns[key] = index.astype(np.int32)
    # Shiu et al.'s own sign per presynaptic neuron (0 when mixed or absent), for comparison only.
    outgoing = position[data["pre"]] >= 0
    low, high = np.full(len(kept), 2, dtype=np.int64), np.full(len(kept), -2, dtype=np.int64)
    np.minimum.at(low, position[data["pre"][outgoing]], data["shiu_sign"][outgoing])
    np.maximum.at(high, position[data["pre"][outgoing]], data["shiu_sign"][outgoing])
    shiu = np.where(low == high, low, 0)
    nts = np.array(lookups["transmitter"])[columns["transmitter"]]
    supers = np.array(lookups["super_class"])[columns["super_class"]]
    sides = np.array(lookups["side"])[columns["side"]]
    rule = {"acetylcholine": 1, "gaba": -1, "glutamate": -1, "dopamine": 1, "serotonin": 1, "octopamine": 1}
    expected = np.array([rule.get(nt, 0) for nt in nts])
    compared = (shiu != 0) & (expected != 0)
    dropped = chosen["dropped"]
    dropped_super = {str(k): int(v) for k, v in zip(*np.unique(data["lookup_super_class"][data["super_class"][dropped]], return_counts=True))} if len(dropped) else {}
    dropped_types = {}
    if len(dropped):
        names, counts = np.unique(data["lookup_cell_type"][data["cell_type"][dropped]], return_counts=True)
        dropped_types = {str(k): int(v) for k, v in sorted(zip(names, counts), key=lambda x: -x[1])[:25]}
    # Default steering readout: the seeds' cell types that have seed neurons on both sides.
    seed_labels = data["lookup_cell_type"][data["cell_type"][seeds]]
    seed_sides = data["lookup_side"][data["side"][seeds]]
    readout = [str(t) for t in dict.fromkeys(seed_labels.tolist())
               if {"left", "right"} <= set(seed_sides[seed_labels == t].tolist())]
    seed_text = ", ".join(r["seed"] for r in records)
    header = {
        "format": "digitalfly-circuit", "version": 2, "name": name,
        "kind": "Data-derived structure: identities, types, sides, predicted transmitters and synapse counts. "
                "Signs, gains and dynamics are runtime assumptions of the model that loads it.",
        "provenance": {
            "dataset": "FlyWire FAFB", "release": "v783", "specimen": "FAFB, one adult female brain", "sex": "female",
            "coverage": (f"Every neuron with a connection of at least {threshold} synapses; hop distances from {seed_text}"
                         if whole else f"{seed_text} and their presynaptic partners up to {hops} hops back, connections "
                         f"with at least {threshold} synapses, at most {cap} neurons"),
            "license": FLYWIRE_LICENSE, "non_commercial": True, "attribution": ATTRIBUTION, "citations": CITATIONS,
            "sources": sources,
            "build": {"script": "scripts/build_circuit.py", "command": "build", "seeds": [r["seed"] for r in records],
                      "synapse_threshold": threshold, "hops": None if whole else hops,
                      "neuron_cap": None if whole else cap, "whole_brain": whole,
                      "connections": "induced subgraph: every kept pair with at least the threshold",
                      "numpy": np.__version__},
            "seeds": records,
            "counts": {"neurons": int(len(kept)), "connections": int(len(e_count)), "synapses": int(e_count.sum()),
                       "cell_types": len(lookups["cell_type"]), "by_hop": chosen["by_hop"],
                       "unreached": int((chosen["hop"] < 0).sum()),
                       "visual_projection_inputs": {side: int(((supers == "visual_projection") & (sides == side)).sum())
                                                    for side in ["left", "right"]}},
            "cap_report": {"cap": None if whole else cap, "candidates": chosen["candidates"], "kept": int(len(kept)),
                           "dropped": int(len(dropped)), "binding": bool(len(dropped)),
                           "weakest_kept_path_strength": chosen["weakest_kept_strength"],
                           "strongest_dropped_path_strength": float(chosen["dropped_strength"].max()) if len(dropped) else None,
                           "dropped_by_super_class": dict(sorted(dropped_super.items(), key=lambda x: -x[1])),
                           "dropped_top_cell_types": dropped_types},
            "transmitters": {"source": "neurotransmitter_predicted in the harmonized metadata (Eckstein et al. 2024 predictions)",
                             "counts": {nt: int((nts == nt).sum()) for nt in lookups["transmitter"]},
                             "shiu_sign_comparison": {"neurons_compared": int(compared.sum()),
                                                      "agree": int((compared & (shiu == expected)).sum())}},
        },
        "defaults": {"readout_types": readout, "input": "visual_projection"},
        "lookups": lookups,
    }
    folder = OUT_DIR if committed else LOCAL_DIR
    folder.mkdir(parents=True, exist_ok=True)
    fmt = fmt if fmt != "auto" else ("json" if len(e_count) <= JSON_EDGE_LIMIT else "npz")
    path = folder / f"{name}.{fmt}"
    score = data["transmitter_score"][kept]
    if fmt == "json":
        payload = {**header, "neurons": {
            "id": [str(i) for i in data["neuron_id"][kept]], **{k: columns[k].tolist() for k in columns},
            "transmitter_score": [None if not np.isfinite(v) else round(float(v), 3) for v in score],
            "hop": chosen["hop"].tolist(), "path_strength": [float(f"{v:.6g}") for v in chosen["strength"]],
            "shiu_sign": shiu.tolist()},
            "edges": {"pre": e_pre.tolist(), "post": e_post.tolist(), "synapses": e_count.tolist()}}
        write_atomic(path, lambda handle: handle.write(json.dumps(payload, separators=(",", ":")).encode()))
    else:
        write_atomic(path, lambda handle: np.savez_compressed(
            handle, header=np.array(json.dumps(header)), neuron_id=data["neuron_id"][kept],
            **{f"neuron_{k}": v for k, v in columns.items()},
            neuron_transmitter_score=score, neuron_hop=chosen["hop"].astype(np.int32),
            neuron_path_strength=chosen["strength"].astype(np.float64),
            neuron_shiu_sign=shiu.astype(np.int8), edge_pre=e_pre.astype(np.int32),
            edge_post=e_post.astype(np.int32), edge_synapses=e_count.astype(np.int32)))
    # Only once the new file is in place: drop this name's other format, never other circuits or bridges.
    (folder / f"{name}.{'npz' if fmt == 'json' else 'json'}").unlink(missing_ok=True)
    counts = header["provenance"]["counts"]
    print(json.dumps({"name": name, "path": str(shown(path)), **{k: counts[k] for k in ["neurons", "connections", "cell_types", "by_hop"]},
                      "readout_types": readout, "bytes": path.stat().st_size, "sha256": sha256(path.read_bytes())}))


# The 65 node types of FlyVis 1.2.0 (Lappalainen et al. 2024), and the FlyWire v783 types that stand for them.
# CT1 has two compartments in FlyVis; its lobula compartment is the one that can reach lobula neurons.
FLYVIS_TYPES = ["Am", "C2", "C3", "CT1(Lo1)", "CT1(M10)", "L1", "L2", "L3", "L4", "L5", "Lawf1", "Lawf2", "Mi1",
                "Mi10", "Mi11", "Mi12", "Mi13", "Mi14", "Mi15", "Mi2", "Mi3", "Mi4", "Mi9", "R1", "R2", "R3", "R4",
                "R5", "R6", "R7", "R8", "T1", "T2", "T2a", "T3", "T4a", "T4b", "T4c", "T4d", "T5a", "T5b", "T5c",
                "T5d", "Tm1", "Tm16", "Tm2", "Tm20", "Tm28", "Tm3", "Tm30", "Tm4", "Tm5Y", "Tm5a", "Tm5b", "Tm5c",
                "Tm9", "TmY10", "TmY13", "TmY14", "TmY15", "TmY18", "TmY3", "TmY4", "TmY5a", "TmY9"]
FLYVIS_ALIASES = {"CT1(Lo1)": "CT1"}


def flyvis_bridge(circuit_name):
    """Synapses from FlyVis-modelled optic-lobe types onto each visual projection neuron of a circuit, by eye.

    Data-derived (FlyWire v783 synapse counts); written next to the circuit as <name>.flyvis.json."""
    sys.path.insert(0, str(ROOT / "backend/src"))
    from digitalfly.neural.connectome import circuit_path, load_circuit
    path = circuit_path(circuit_name)
    circuit = load_circuit(path)
    data = load_prepared()
    labels = data["lookup_cell_type"]
    names = {str(n): k for k, n in enumerate(labels)}
    mapping = {t: FLYVIS_ALIASES.get(t, t) for t in FLYVIS_TYPES if FLYVIS_ALIASES.get(t, t) in names}
    flyvis_of_label = np.full(len(labels), -1)
    for t, flywire in mapping.items():
        flyvis_of_label[names[flywire]] = FLYVIS_TYPES.index(t)
    ids = data["neuron_id"]
    targets = np.flatnonzero(circuit.super_class == "visual_projection")
    position = np.searchsorted(ids, np.array([int(circuit.ids[i]) for i in targets]))
    if not np.array_equal(ids[position], np.array([int(circuit.ids[i]) for i in targets])):
        sys.exit("The circuit's neurons are missing from the prepared archive.")
    row = np.full(len(ids), -1)
    row[position] = np.arange(len(targets))
    onto = row[data["post"]] >= 0
    total = np.bincount(row[data["post"][onto]], weights=data["synapses"][onto], minlength=len(targets))
    pre = data["pre"][onto]
    flyvis_type = flyvis_of_label[data["cell_type"][pre]]
    sides = data["lookup_side"][data["side"][pre]]
    eye = np.where(sides == "left", 0, np.where(sides == "right", 1, -1))
    keep = (flyvis_type >= 0) & (eye >= 0)
    key = (row[data["post"][onto]][keep] * len(FLYVIS_TYPES) + flyvis_type[keep]) * 2 + eye[keep]
    unique, inverse = np.unique(key, return_inverse=True)
    synapses = np.bincount(inverse, weights=data["synapses"][onto][keep])
    neuron, rest = np.divmod(unique, len(FLYVIS_TYPES) * 2)
    ftype, eyes = np.divmod(rest, 2)
    covered = np.bincount(neuron, weights=synapses, minlength=len(targets))
    weight = synapses / covered[neuron]
    bridge = {
        "format": "digitalfly-flyvis-bridge", "version": 1, "circuit": path.stem, "circuit_sha256": circuit.sha256,
        "kind": "Data-derived: FlyWire v783 synapse counts from optic-lobe types that FlyVis models onto the "
                "circuit's visual projection neurons, by the presynaptic neuron's side (eye).",
        "flyvis": {"release": "1.2.0", "types": FLYVIS_TYPES, "flywire_names": mapping,
                   "unmapped": [t for t in FLYVIS_TYPES if t not in mapping]},
        "rule": "weight = synapses from that type and eye ÷ the neuron's synapses from all mapped types; "
                "coverage = mapped synapses ÷ all of the neuron's input synapses in FlyWire v783",
        "license": FLYWIRE_LICENSE, "non_commercial": True, "attribution": ATTRIBUTION,
        "sources": data["header"]["sources"],
        "neurons": [int(i) for i in targets],
        "coverage": [round(float(c / t), 6) if t else 0.0 for c, t in zip(covered, total)],
        "entries": {"neuron": neuron.astype(int).tolist(), "type": ftype.astype(int).tolist(),
                    "eye": eyes.astype(int).tolist(), "weight": [round(float(w), 6) for w in weight]},
    }
    out = path.with_name(f"{path.stem}.flyvis.json")
    write_atomic(out, lambda handle: handle.write(json.dumps(bridge, separators=(",", ":")).encode()))
    print(json.dumps({"bridge": str(shown(out)), "input_neurons": len(targets),
                      "with_flyvis_input": int((covered > 0).sum()), "entries": len(weight),
                      "median_coverage": float(np.median(covered / np.maximum(total, 1))),
                      "mapped_types": len(mapping), "bytes": out.stat().st_size}))


def arguments(argv=None):
    """Parse the command line. The shared options work before or after the subcommand: the subcommands'
    copies default to SUPPRESS, so they never overwrite a value given before the subcommand."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--threshold", type=int, default=5, help="Minimum synapses per connection (default 5)")
    parser.add_argument("--hops", type=int, default=2, help="Presynaptic hops back from DNa02 (default 2)")
    parser.add_argument("--cap", type=int, default=3000, help="Maximum neurons, DNa02 included (default 3000)")
    parser.add_argument("--offline", action="store_true", help="Use cached downloads only")
    commands = parser.add_subparsers(dest="command", help="Without a command: rebuild the committed DNa02 circuit")
    prep = commands.add_parser("prepare", help="Convert the cached downloads for `build` (needs pyarrow once)")
    prep.add_argument("--offline", action="store_true", default=argparse.SUPPRESS, help="Use cached downloads only")
    custom = commands.add_parser("build", help="Build a circuit around any seeds from the prepared archive (NumPy only)")
    custom.add_argument("--name", required=True, help="Circuit name: lower-case letters, digits, '.', '-', '_'")
    custom.add_argument("--seeds", default="", help="Comma-separated cell types or FlyWire root IDs, e.g. DNa01,DNa02")
    custom.add_argument("--seed", action="append", default=[], help="One seed; repeat it, and use it for names with commas")
    custom.add_argument("--hops", type=int, default=argparse.SUPPRESS, help="Presynaptic hops back from the seeds (default 2)")
    custom.add_argument("--threshold", type=int, default=argparse.SUPPRESS, help="Minimum synapses per connection (default 5)")
    custom.add_argument("--cap", type=int, default=argparse.SUPPRESS, help="Maximum neurons, seeds included (default 3000)")
    custom.add_argument("--whole-brain", action="store_true", help="Every connected neuron; seeds set hop distances")
    custom.add_argument("--format", choices=["auto", "json", "npz"], default="auto")
    custom.add_argument("--committed", action="store_true", help="Write to data/circuits/ (maintainers) instead of data/circuits/local/")
    bridge = commands.add_parser("flyvis-bridge", help="Wire FlyVis cell types to a circuit's visual projection neurons")
    bridge.add_argument("--circuit", required=True, help="Circuit name, committed or local")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = arguments()
    if args.command == "flyvis-bridge":
        flyvis_bridge(args.circuit)
        sys.exit(0)
    if args.command == "build":
        if not 1 <= args.threshold <= 1000 or not 1 <= args.hops <= 6 or not 1 <= args.cap <= 200_000:
            sys.exit("Choose a threshold of 1-1000 synapses, 1-6 hops and a cap of 1-200,000 neurons.")
        seeds = [t for t in args.seeds.split(",") if t.strip()] + args.seed
        if not seeds:
            sys.exit("Give at least one seed with --seeds or --seed.")
        build_custom(args.name, seeds, args.hops, args.threshold, args.cap, args.whole_brain, args.format, args.committed)
        sys.exit(0)
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        sys.exit("pyarrow is missing. Install the build-only dependencies: "
                 "backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements-data.lock")
    if args.command == "prepare":
        prepare(args.offline)
    else:
        build(args.threshold, args.hops, args.cap, args.offline)
