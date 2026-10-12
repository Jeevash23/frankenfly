"""Build display-only anatomy from retained upstream SWC/PLY assets, without network access.

SWC topology is contracted along degree-two chains by a 2 µm cable-distance rule.
Every branch/end point survives. Meshes use 4 µm vertex clustering. Source geometry
is retained for analysis; display geometry is never used to drive the simulation.
"""
import hashlib
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "data/atlas"


def skeleton(path, scale):
    rows = np.loadtxt(path)
    ids = rows[:, 0].astype(int)
    index = {int(n): i for i, n in enumerate(ids)}
    xyz = rows[:, 2:5] * scale
    parents = np.array([index.get(int(p), -1) for p in rows[:, 6]])
    children = np.bincount(parents[parents >= 0], minlength=len(rows))
    required = (children != 1) | (parents < 0)
    kept = set(np.flatnonzero(required).tolist())
    cable = 0.
    for i, p in enumerate(parents):
        if p >= 0:
            cable += float(np.linalg.norm(xyz[i]-xyz[p]))
    # Walk every branch from its leaf/branch point toward a retained ancestor.
    for start in sorted(kept):
        current = start
        distance = 0.
        while parents[current] >= 0:
            parent = parents[current]
            distance += np.linalg.norm(xyz[current]-xyz[parent])
            if parent in kept:
                break
            if distance >= 2:
                kept.add(int(parent))
                distance = 0.
            current = parent
    order = sorted(kept)
    remap = {old: new for new, old in enumerate(order)}
    edges = []
    for old in order:
        p = parents[old]
        while p >= 0 and p not in kept:
            p = parents[p]
        if p >= 0:
            edges.append([remap[old], remap[int(p)]])
    return {"points": np.round(xyz[order], 3).tolist(), "edges": edges,
        "original_points": len(rows), "display_points": len(order), "cable_length_um": cable}


def surface(name):
    # These pinned upstream assets use xyz float32 vertices and triangular faces.
    with (ATLAS / "sources" / name).open("rb") as file:
        header = []
        while True:
            line = file.readline().decode().strip()
            header.append(line)
            if line == "end_header":
                break
        assert "format binary_little_endian 1.0" in header
        vertices = int(next(s for s in header if s.startswith("element vertex")).split()[-1])
        face_count = int(next(s for s in header if s.startswith("element face")).split()[-1])
        points = np.frombuffer(file.read(vertices*12), dtype="<f4").reshape(-1, 3).astype(float) / 1000
        raw_faces = np.frombuffer(file.read(), dtype=np.dtype([("count", "u1"), ("index", "<u4", (3,))]))
        assert len(raw_faces) == face_count and np.all(raw_faces["count"] == 3)
        triangles = raw_faces["index"]
    keys = np.round(points / 4).astype(int)
    _, inverse = np.unique(keys, axis=0, return_inverse=True)
    count = np.bincount(inverse)
    clustered = np.stack([np.bincount(inverse, weights=points[:, i])/count for i in range(3)], axis=1)
    faces = inverse[triangles]
    faces = faces[(faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 2] != faces[:, 0])]
    _, inds = np.unique(np.sort(faces, axis=1), axis=0, return_index=True)
    return {"name": name, "points": np.round(clustered, 3).tolist(), "faces": faces[sorted(inds)].tolist()}


def build():
    downloads = json.loads((ATLAS / "downloads.json").read_text())
    mapping = json.loads((ATLAS / "type-mapping-excerpt.json").read_text())
    for item in downloads:
        data = (ATLAS / "sources" / item["name"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == item["sha256"], f"Source hash mismatch: {item['name']}"
    sexes = []
    for sex in ["female", "male"]:
        neurons = []
        for item in downloads:
            if item.get("sex") != sex:
                continue
            assert mapping["assignments"][item["neuron_id"]] == item["cell_type"]
            neuron = skeleton(ATLAS / "sources" / item["name"], .001 if sex == "female" else .008)
            neurons.append({**neuron, "id": item["neuron_id"], "cell_type": item["cell_type"],
                "source_url": item["url"], "sha256": item["sha256"]})
        surfaces = [surface("FAFB14.ply")] if sex == "female" else [surface("JRCFIB2022M_brain.ply"), surface("JRCFIB2022M_vnc.ply")]
        info = {"sex": sex, "dataset": "FAFB / FlyWire" if sex == "female" else "MaleCNS",
            "release": "783; shared cell-type mapping from Berg et al." if sex == "female" else "v1.0",
            "space": "FAFB native" if sex == "female" else "MaleCNS EM",
            "units": "µm", "source_units": "nm" if sex == "female" else "8 nm voxels",
            "neurons_loaded": len(neurons), "types": ["DNa02", "DNp01", "DNp09"],
            "coverage": "Brain surface and six descending-neuron skeletons" if sex == "female" else "Brain + VNC surfaces and six descending-neuron skeletons",
            "license": ("CC BY-NC 4.0 for FlyWire data" if sex == "female" else "CC BY 4.0 for MaleCNS data") + "; navis-flybrains surfaces distributed under GPL-3.0 (source notice retained)",
            "source_url": "https://github.com/sjcabs/fly_connectome_data_tutorial" if sex == "female" else "https://male-cns.janelia.org/download/",
            "caveat": "Anatomy only. No synaptic wiring or activity is inferred. The two specimens have different coverage and preparation; shape differences are not evidence of a sex effect."}
        sexes.append(info)
        (ATLAS / f"{sex}.json").write_text(json.dumps({**info, "neurons": neurons, "surfaces": surfaces}, separators=(",", ":")))
        print(sex, "neurons", len(neurons), "display points", sum(n['display_points'] for n in neurons), "bytes", (ATLAS/f'{sex}.json').stat().st_size)
    manifest = {"version": 1, "datasets": sexes,
        "body": {"sex": "female", "source": "https://neuromechfly.org/", "male_body_available": False},
        "display_processing": "SWC degree-two chain contraction at 2 µm; surface vertex clustering at 4 µm. Original source files and hashes retained.",
        "cell_type_mapping": {k: v for k,v in mapping.items() if k != "assignments"},
        "catalog": [
            {"name": "FlyWire", "sex": "female", "coverage": "Adult brain", "url": "https://codex.flywire.ai/"},
            {"name": "MaleCNS", "sex": "male", "coverage": "Adult brain + nerve cord", "url": "https://male-cns.janelia.org/"},
            {"name": "BANC", "sex": "female", "coverage": "Brain + nerve cord; coverage differs by release", "url": "https://github.com/htem/BANC-project"},
            {"name": "MANC", "sex": "male", "coverage": "Adult nerve cord", "url": "https://www.janelia.org/project-team/flyem/manc-connectome"}]}
    (ATLAS / "manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    build()
