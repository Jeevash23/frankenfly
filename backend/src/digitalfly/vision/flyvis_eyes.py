"""FlyVis as the fly's early visual system: rendered compound-eye images → 65 optic-lobe cell types per eye.

FlyVis (Lappalainen et al. 2024, Nature 634:1132; MIT) is a connectome-constrained network of 64 optic-lobe
cell types (45,669 neurons per eye, from photoreceptors to T4/T5 and the Tm/TmY layer) on a hexagonal lattice
of 721 columns, the same count as FlyGym's ommatidia. Its connectivity comes from the FIB-25/FIB-19 medulla
reconstructions, not FlyWire, and its unknown single-neuron and synapse parameters were trained on a motion
task. It sees luminance only. It is an optional install (`backend/requirements-vision.lock`) with pretrained
models in the ignored `.cache/flyvis/` (see docs/RESEARCH.md).

What this module adds, and what is engineered:
  * Column mapping: FlyGym ommatidia are matched to FlyVis columns by the nearest centroid after an affine
    fit anchored on the lattice's extreme columns, after FlyGym 1.x's RetinaMapper (Apache-2.0). FlyGym's two
    eye cameras are mirror images of each other; the right eye is mirrored onto FlyVis's layout so that T4a/T5a
    prefer front-to-back and T4c/T4d upward/downward motion, as in flies (Maisak et al. 2013; tested).
  * Luminance: the mean of the RGB channels per ommatidium (FlyVis receives one value per column).
  * Pooled output: for each cell type and eye, the largest rectified activity across the eye's columns minus
    the same quantity at the grey steady state, clipped at zero. This discards where in the eye a response is.
"""
import os
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
FLYVIS_ROOT = ROOT / ".cache/flyvis"
DEFAULT_NETWORK = "flow/0000/000"  # the best-ranked of the 50 pretrained networks
DT = 0.01  # one FlyVis step per 10 ms control interval; FlyVis warns above 1/50 s


def network_dir(name: str = DEFAULT_NETWORK) -> Path:
    return FLYVIS_ROOT / "results" / name


def available(name: str = DEFAULT_NETWORK) -> tuple[bool, str]:
    """Whether FlyVis and the pretrained network are installed, with the reason if not."""
    import importlib.util
    if importlib.util.find_spec("flyvis") is None or importlib.util.find_spec("torch") is None:
        return False, ("FlyVis is not installed. Install the optional vision lock: backend/.venv/bin/python -m pip "
                       "install --require-hashes -r backend/requirements-vision.lock")
    if not (network_dir(name) / "best_chkpt").is_file():
        return False, "The pretrained FlyVis networks are missing. Run: backend/.venv/bin/python scripts/fetch_flyvis.py (3.4 MB)."
    return True, ""


def ommatidia_centroids(id_map: np.ndarray) -> np.ndarray:
    """(row, col) centroid of every ommatidium in a FlyGym id map (ids 1..N)."""
    ids = id_map.ravel()
    rows, cols = np.divmod(np.arange(ids.size), id_map.shape[1])
    keep = ids > 0
    n = int(ids.max())
    counts = np.bincount(ids[keep], minlength=n + 1)[1:]
    return np.stack([np.bincount(ids[keep], weights=rows[keep], minlength=n + 1)[1:] / counts,
                     np.bincount(ids[keep], weights=cols[keep], minlength=n + 1)[1:] / counts], axis=1)


def column_order(centroids: np.ndarray, receptor_centers: np.ndarray) -> np.ndarray:
    """For each FlyVis column, the index of the FlyGym ommatidium at the same lattice position.

    Both lattices are anchored like FlyGym 1.x's RetinaMapper: the top of the leftmost column and the bottom of
    the rightmost column fix an axis-aligned affine map from FlyVis receptor coordinates (row, col) to FlyGym
    image coordinates; each FlyVis column then takes its nearest FlyGym centroid. Raises if that is not a
    one-to-one match."""
    rc = np.asarray(receptor_centers, dtype=np.float64)

    def anchors(points):
        left, right = points[:, 1].min(), points[:, 1].max()
        top_left = points[np.isclose(points[:, 1], left)][:, 0].min()
        bottom_right = points[np.isclose(points[:, 1], right)][:, 0].max()
        return np.array([top_left, left]), np.array([bottom_right, right])

    # FlyGym columns are not exactly aligned, so its anchors use the extreme centroids by column.
    gym_left, gym_right = centroids[:, 1].min(), centroids[:, 1].max()
    first = centroids[np.abs(centroids[:, 1] - gym_left) < 2]
    last = centroids[np.abs(centroids[:, 1] - gym_right) < 2]
    gym_a, gym_b = np.array([first[:, 0].min(), gym_left]), np.array([last[:, 0].max(), gym_right])
    vis_a, vis_b = anchors(rc)
    scale = (gym_b - gym_a) / (vis_b - vis_a)
    mapped = gym_a + (rc - vis_a) * scale
    distance = ((mapped[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=-1)
    order = distance.argmin(axis=1)
    if len(np.unique(order)) != len(order) or len(order) != len(centroids):
        raise ValueError("FlyVis columns and FlyGym ommatidia do not match one to one.")
    return order


class FlyVisEyes:
    """Both eyes as one FlyVis network run with a batch of two (left mirrored, right as is)."""

    def __init__(self, network: str = DEFAULT_NETWORK, dt: float = DT, retina=None):
        ok, reason = available(network)
        if not ok:
            raise RuntimeError(reason)
        os.environ.setdefault("FLYVIS_ROOT_DIR", str(FLYVIS_ROOT))
        import logging
        level = logging.getLogger().level
        import torch
        import yaml
        import flyvis
        from flyvis.datasets.rendering import BoxEye
        from flyvis.network import Network
        logging.getLogger().setLevel(level)  # flyvis configures logging on import
        self.torch = torch
        directory = network_dir(network)
        config = yaml.safe_load((directory / "_meta.yaml").read_text())["config"]["network"]
        self.network = Network(**config)
        self.network.eval()
        # Weights only: the checkpoint is plain tensors, so nothing in it is executed.
        state = torch.load(directory / "best_chkpt", map_location="cpu", weights_only=True)["network"]
        self.network.load_state_dict(state)
        for parameter in self.network.parameters():
            parameter.requires_grad_(False)
        self.dt, self.name, self.flyvis_version = dt, network, flyvis.__version__
        nodes = self.network.connectome.nodes
        node_types = np.array([t.decode() if isinstance(t, bytes) else str(t) for t in nodes.type[:]])
        self.types = sorted(set(node_types))
        self.type_of_node = np.searchsorted(self.types, node_types)
        if retina is None:
            from flygym.vision.retina import Retina
            retina = Retina()
        centroids = ommatidia_centroids(retina.ommatidia_id_map)
        mirrored = centroids.copy()
        mirrored[:, 1] = retina.ommatidia_id_map.shape[1] - 1 - mirrored[:, 1]
        receptors = BoxEye(extent=15, kernel_size=13).receptor_centers.cpu().numpy()
        # FlyGym's right-eye image has the front of the visual field on its left; FlyVis's lattice has it on the
        # other side (checked with moving edges: T4a and T5a must prefer front-to-back motion, Maisak et al.
        # 2013). So the right eye is mirrored, and the left eye, already a mirror image, is not.
        self.order = {"right": column_order(mirrored, receptors), "left": column_order(centroids, receptors)}
        self.retina = retina
        self.reset()

    def _pool(self, activity) -> np.ndarray:
        a = np.maximum(activity.detach().cpu().numpy(), 0)  # (2, nodes)
        pooled = np.full((a.shape[0], len(self.types)), -np.inf)
        for eye in range(a.shape[0]):
            np.maximum.at(pooled[eye], self.type_of_node, a[eye])
        return pooled

    def reset(self):
        """Grey (0.5) for one simulated second, FlyVis's default steady state."""
        with self.torch.no_grad():
            self.state = self.network.steady_state(1.0, self.dt, batch_size=2)
        self.baseline = self._pool(self.state.nodes.activity)
        self.responses = np.zeros_like(self.baseline)

    def columns(self, luminance_left: np.ndarray, luminance_right: np.ndarray) -> np.ndarray:
        """(2, 721) FlyVis inputs from per-ommatidium luminance in FlyGym order."""
        return np.stack([np.asarray(luminance_left)[self.order["left"]], np.asarray(luminance_right)[self.order["right"]]])

    def step(self, luminance_left: np.ndarray, luminance_right: np.ndarray, steps: int = 1) -> np.ndarray:
        """Advance `steps` × dt with the given frame held; returns (2, types) pooled responses above grey."""
        frames = self.torch.tensor(self.columns(luminance_left, luminance_right), dtype=self.torch.float32)
        frames = frames[:, None, None, :].repeat(1, steps, 1, 1)
        with self.torch.no_grad():
            self.network.stimulus.zero(2, steps)
            self.network.stimulus.add_input(frames)
            self.state = self.network(self.network.stimulus(), self.dt, state=self.state, as_states=True)[-1]
        self.responses = np.clip(self._pool(self.state.nodes.activity) - self.baseline, 0, None)
        return self.responses

    def type_activity(self, eye: str, cell_type: str) -> np.ndarray:
        """Every column's activity of one type in one eye, in FlyVis column order (for tests and inspection)."""
        nodes = np.flatnonzero(self.type_of_node == self.types.index(cell_type))
        return self.state.nodes.activity[0 if eye == "left" else 1, nodes].detach().cpu().numpy()

    def luminance(self, raw_eye_image: np.ndarray) -> np.ndarray:
        """Per-ommatidium luminance in [0, 1] from one raw RGB eye image."""
        grey = raw_eye_image.astype(np.float32).mean(axis=-1)
        grey3 = np.repeat(np.clip(grey, 0, 255).astype(np.uint8)[..., None], 3, axis=-1)
        return self.retina.raw_image_to_hex_pxls(grey3).sum(axis=-1).astype(np.float64)  # already in [0, 1]

    def describe(self) -> dict:
        return {"model": "FlyVis (Lappalainen et al. 2024)", "flyvis_version": self.flyvis_version, "network": self.name,
                "dt_s": self.dt, "cell_types": len(self.types), "columns_per_eye": 721,
                "pooling": "max over columns of rectified activity minus its grey steady-state value",
                "labels": {"network_connectivity": "data-derived (FIB-25/FIB-19 medulla), task-trained parameters",
                           "column_mapping": "engineered", "luminance": "engineered", "pooling": "engineered"}}
