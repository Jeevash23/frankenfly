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
import sys
import urllib.request
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


def fetch(url, start=None, end=None):
    """GET a URL, or the byte range [start, end), and return the body."""
    headers = {"User-Agent": "digitalfly-build-circuit"}
    if start is not None:
        headers["Range"] = f"bytes={start}-{end - 1}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
        data = response.read()
    if start is not None and len(data) != end - start:
        raise IOError(f"Expected {end - start} bytes from {url}, received {len(data)}.")
    return data


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
        print(f"Downloading {source['url']} …", flush=True)
        CACHE.mkdir(parents=True, exist_ok=True)
        data = fetch(source["url"])
        path.with_suffix(".part").write_bytes(data)
        path.with_suffix(".part").rename(path)
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


def select_subcircuit(pre, post, count, seeds, threshold, hops, cap):
    """Choose the neurons and connections. A pure function of the full edge list.

    Hop h holds the presynaptic partners (connections with at least `threshold` synapses) of
    hop h-1 that are not already included. Every seed and hop-1 neuron is kept. If more
    neurons qualify than `cap`, the deepest layers are trimmed to the neurons with the
    strongest path to a seed, where a path's strength multiplies the input fractions of its
    connections (synapses on the connection / all synapses onto the postsynaptic neuron).
    The connections are the induced subgraph: every kept pair with at least `threshold`.
    """
    pre, post, count = (np.asarray(a, dtype=np.int64) for a in (pre, post, count))
    seeds = np.asarray(seeds, dtype=np.int64)
    unique_post, inverse_post = np.unique(post, return_inverse=True)
    total_in = np.bincount(inverse_post, weights=count)

    def input_total(ids):
        position = np.searchsorted(unique_post, ids)
        position[position >= len(unique_post)] = 0
        return np.where(unique_post[position] == ids, total_in[position], 0.)

    strong = count >= threshold
    s_pre, s_post, s_count = pre[strong], post[strong], count[strong]
    layers = [seeds]
    strength = {int(i): 1.0 for i in seeds}
    for _ in range(hops):
        mask = np.isin(s_post, layers[-1])
        e_pre, e_post, e_count = s_pre[mask], s_post[mask], s_count[mask]
        fraction = e_count / input_total(e_post)
        best = {}
        for a, b, f in zip(e_pre.tolist(), e_post.tolist(), fraction.tolist()):
            if a in strength:
                continue
            value = f * strength[b]
            if value > best.get(a, 0.):
                best[a] = value
        strength.update(best)
        layers.append(np.array(sorted(best), dtype=np.int64))

    kept_layers, dropped, budget = [seeds], [], cap - len(seeds)
    for depth, layer in enumerate(layers[1:], start=1):
        if len(layer) <= budget or depth == 1:
            kept_layers.append(layer)
            budget -= len(layer)
            continue
        ranked = sorted(layer.tolist(), key=lambda i: (-strength[i], i))
        keep = max(budget, 0)
        kept_layers.append(np.array(sorted(ranked[:keep]), dtype=np.int64))
        dropped.extend(ranked[keep:])
        budget -= keep
    kept = np.concatenate(kept_layers)
    position = {int(i): k for k, i in enumerate(kept)}
    mask = strong & np.isin(pre, kept) & np.isin(post, kept)
    e_pre = np.array([position[int(i)] for i in pre[mask]], dtype=np.int64)
    e_post = np.array([position[int(i)] for i in post[mask]], dtype=np.int64)
    e_count = count[mask]
    order = np.lexsort((e_pre, e_post))
    weakest = min((strength[int(i)] for i in kept_layers[-1]), default=None) if dropped else None
    return {"kept": kept, "hop": np.concatenate([np.full(len(l), h) for h, l in enumerate(kept_layers)]),
            "strength": np.array([strength[int(i)] for i in kept]),
            "by_hop": [int(len(l)) for l in kept_layers],
            "candidates": int(sum(len(l) for l in layers)), "dropped": np.array(dropped, dtype=np.int64),
            "dropped_strength": np.array([strength[int(i)] for i in dropped]),
            "weakest_kept_strength": weakest,
            "edges": (e_pre[order], e_post[order], e_count[order])}


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
    OUTPUT.write_text(json.dumps(circuit, separators=(",", ":")))
    DOWNLOADS.write_text(json.dumps(records, indent=2) + "\n")
    print(json.dumps(circuit["provenance"]["counts"], indent=1))
    print("cap:", json.dumps({k: cap_report[k] for k in ["candidates", "kept", "dropped", "binding"]}))
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size / 1e6:.2f} MB), sha256 {sha256(OUTPUT.read_bytes())}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--threshold", type=int, default=5, help="Minimum synapses per connection (default 5)")
    parser.add_argument("--hops", type=int, default=2, help="Presynaptic hops back from DNa02 (default 2)")
    parser.add_argument("--cap", type=int, default=3000, help="Maximum neurons, DNa02 included (default 3000)")
    parser.add_argument("--offline", action="store_true", help="Use cached downloads only")
    args = parser.parse_args()
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        sys.exit("pyarrow is missing. Install the build-only dependencies: "
                 "backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements-data.lock")
    build(args.threshold, args.hops, args.cap, args.offline)
