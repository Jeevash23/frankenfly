"""Optional PyTorch backend for the connectome model: `connectome_parameters.backend = "torch"`.

The default backend ("cpu": NumPy and SciPy, neural/connectome.py) is unchanged. This one keeps the network
state on a CUDA GPU, with PyTorch sparse CSR weights in float64 like the CPU path, and computes the same equations:

  rate      one sparse matrix-vector product and the same element-wise update per 1 ms step. It matches the CPU
            path within float rounding: the sparse sums add the same terms in another order.
  spiking   the Shiu et al. 2024 LIF network in Brian2's schedule, as connectome.SpikingState. A spike reaches its
            targets 1.8 ms (18 substeps) later, so within a run of at most 18 substeps no neuron affects another:
            each neuron is integrated through the whole run on its own (one fused Triton kernel on a GPU), and one
            sparse matrix product per run puts the run's spikes, with their weights, in the delay queue. Poisson
            input comes from Philox generators instead of NumPy's, so spike trains differ from the CPU path's for the
            same seed; they agree in distribution (scripts/benchmark.py --check).

The host reads the device only when it needs numbers (readouts, once per control interval in the app), so the GPU
runs ahead of Python between reads. A non-finite state is therefore reported at the next read, or within 100 steps,
rather than at the step that produced it. Nothing here is imported, and PyTorch is not loaded, unless a run asks
for the torch backend.
"""
import math
import os
from functools import lru_cache
import numpy as np
from scipy import sparse

DEVICE_VARIABLE = "DIGITALFLY_TORCH_DEVICE"  # "cpu" runs this code on PyTorch's CPU device (tests); the app needs CUDA
CHECK_EVERY = 100  # steps between finiteness checks when nothing is read in between
RECORD_FLUSH = 100  # steps between copies of recorded spikes to the host


@lru_cache(maxsize=1)
def _status() -> tuple[bool, str, str | None]:
    import importlib.util
    if importlib.util.find_spec("torch") is None:
        return False, ("PyTorch is not installed in this environment. Install the GPU environment "
                       "(./scripts/setup.sh --with gpu) and start the app with it (./scripts/start.sh --gpu)."), None
    try:
        import torch
    except Exception as exc:  # a broken install must not break the app
        return False, f"PyTorch failed to import: {type(exc).__name__}: {exc}", None
    forced = os.environ.get(DEVICE_VARIABLE)
    if forced:
        return True, f"PyTorch {torch.__version__} on {forced} ({DEVICE_VARIABLE})", forced
    if not torch.cuda.is_available():
        build = "a CPU-only build" if torch.version.cuda is None else f"built for CUDA {torch.version.cuda}, but no GPU is usable"
        return False, (f"PyTorch {torch.__version__} is {build}. The torch backend needs an NVIDIA GPU and the GPU "
                       "environment (./scripts/setup.sh --with gpu, then ./scripts/start.sh --gpu)."), None
    props = torch.cuda.get_device_properties(0)
    return True, (f"PyTorch {torch.__version__}, CUDA {torch.version.cuda}, {props.name}, "
                  f"{props.total_memory / 2 ** 30:.1f} GiB"), "cuda"


def available() -> tuple[bool, str]:
    """(whether the torch backend can run here, a one-line description or the reason it cannot)."""
    ok, reason, _ = _status()
    return ok, reason


def device() -> str:
    """The torch device to use, or a ValueError (422 or 409 from the API) that says why there is none."""
    ok, reason, name = _status()
    if not ok:
        raise ValueError(f"The torch brain backend is unavailable: {reason}")
    return name


def fused_kernel(torch_device) -> bool:
    """Whether spiking dynamics use the fused Triton kernel (CUDA with Triton; DIGITALFLY_TORCH_EAGER=1 turns it off)."""
    if torch_device.type != "cuda" or os.environ.get("DIGITALFLY_TORCH_EAGER"):
        return False
    try:
        from digitalfly.neural import gpu_kernels  # noqa: F401
    except Exception:
        return False
    return True


def _csr(torch, matrix: sparse.spmatrix, torch_device):
    matrix = sparse.csr_matrix(matrix)
    matrix.sum_duplicates()
    matrix.sort_indices()
    with torch.sparse.check_sparse_tensor_invariants(enable=False):
        return torch.sparse_csr_tensor(torch.from_numpy(matrix.indptr.astype(np.int64)),
                                       torch.from_numpy(matrix.indices.astype(np.int64)),
                                       torch.from_numpy(matrix.data.astype(np.float64)), size=matrix.shape,
                                       dtype=torch.float64, device=torch_device)


def _seed(seed: int) -> int:
    """A 63-bit generator seed from the run seed."""
    return int(np.random.SeedSequence([int(seed), 0x5B1, 0x70C]).generate_state(1, np.uint64)[0] >> np.uint64(1))


class _Device:
    """What both states share: the device, cached device copies of host arrays, a host mirror of one vector, and the
    deferred finiteness check."""

    def _setup(self, device_name: str):
        import torch
        self.torch, self.device = torch, torch.device(device_name)
        self._cache, self._mirror_version, self._mirror = {}, -1, None
        self.version, self._unchecked = 0, 0
        self._bad = torch.zeros((), dtype=torch.bool, device=self.device)

    def _to_device(self, array: np.ndarray, slot=None):
        """A device copy of a host array, cached by identity: a Manipulation's arrays never change, and the FlyVis
        drive is replaced rather than edited, so it keeps one slot of its own."""
        key = id(array) if slot is None else slot
        hit = self._cache.get(key)
        if hit is None or hit[0] is not array:
            if len(self._cache) > 32:
                self._cache = {}
            hit = self._cache[key] = (array, self.torch.from_numpy(np.ascontiguousarray(array)).to(self.device))
        return hit[1]

    def _note(self, state):
        """After a step: remember whether the state went non-finite, without waiting for the device."""
        self._bad |= ~self.torch.isfinite(state).all()
        self.version += 1
        self._unchecked += 1
        if self._unchecked >= CHECK_EVERY:
            self._check()

    def _check(self):
        self._unchecked = 0
        if bool(self._bad):
            raise FloatingPointError("Nonfinite neural state; simulation paused.")

    def _read(self, tensor) -> np.ndarray:
        if self._mirror_version != self.version:
            self._check()
            self._mirror, self._mirror_version = tensor.cpu().numpy(), self.version
        return self._mirror


class TorchRate(_Device):
    """Rate dynamics on a torch device: r += dt/tau × (clip(W (s ⊙ r) + input, 0, 1) − r), as ConnectomeCircuit."""

    def __init__(self, n: int, device_name: str):
        self._setup(device_name)
        self.n = n
        self.rates = self.torch.zeros(n, dtype=self.torch.float64, device=self.device)

    def configure(self, matrix: sparse.spmatrix, input_left: np.ndarray, input_right: np.ndarray):
        """New weights and input populations; the rates carry over."""
        torch = self.torch
        self.W = _csr(torch, matrix, self.device)
        self.left = torch.zeros(self.n, dtype=torch.float64, device=self.device)
        self.right = torch.zeros(self.n, dtype=torch.float64, device=self.device)
        self.left[torch.from_numpy(input_left).to(self.device)] = 1
        self.right[torch.from_numpy(input_right).to(self.device)] = 1

    def load(self, rates: np.ndarray):
        self.rates.copy_(self.torch.from_numpy(np.asarray(rates, dtype=np.float64)))
        self.version += 1

    def values(self) -> np.ndarray:
        """The rates on the host (copied when they changed since the last read)."""
        return self._read(self.rates)

    def zero(self):
        self.rates.zero_()
        self._bad.zero_()
        self.version += 1

    def clamp(self, silenced: np.ndarray, activated: np.ndarray, activation: np.ndarray):
        if len(silenced):
            self.rates[self._to_device(silenced)] = 0
        if len(activated):
            self.rates[self._to_device(activated)] = self._to_device(activation)
        self.version += 1

    def advance(self, left: float, right: float, visual: np.ndarray | None, silenced: np.ndarray,
                activated: np.ndarray, activation: np.ndarray, scale: np.ndarray | None, gain: float, rate: float):
        """One Euler step; `rate` = dt / tau. The arithmetic and its order follow ConnectomeCircuit.advance."""
        torch, rates = self.torch, self.rates
        self.clamp(silenced, activated, activation)
        drive = torch.mv(self.W, rates if scale is None else rates * self._to_device(scale))
        if visual is not None:
            drive.add_(self._to_device(visual, "visual"), alpha=gain)
        else:
            drive.add_(self.left, alpha=gain * left).add_(self.right, alpha=gain * right)
        drive.clamp_(0, 1)
        rates.add_(drive.sub_(rates).mul_(rate))
        self.clamp(silenced, activated, activation)
        self._note(rates)


class TorchSpikingState(_Device):
    """connectome.SpikingState on a torch device, with the same interface, constants and substep schedule.

    With the fused kernels, device arrays have room for a whole number of kernel blocks: the extra neurons rest
    forever (no input, no connections, never silenced or spiking) and are never shown."""

    def __init__(self, data, active: np.ndarray, signs: np.ndarray, parameters, inputs: tuple[np.ndarray, np.ndarray],
                 device_name: str):
        from digitalfly.neural.connectome import LIF
        self._setup(device_name)
        torch, self.LIF = self.torch, LIF
        n = len(data.ids)
        self.data, self.n, self.inputs = data, n, inputs
        self.fused = fused_kernel(self.device)
        if self.fused:
            from digitalfly.neural.gpu_kernels import BLOCK
            self.size = -(-n // BLOCK) * BLOCK
        else:
            self.size = n
        dt = LIF["dt_ms"]
        self.substeps = round(1 / dt)
        self.delay = round(LIF["delay_ms"] / dt)
        self.slots = self.delay + 1
        refractory = np.full(n, round(LIF["refractory_ms"] / dt), dtype=np.int32)
        for side in inputs:
            refractory[side] = 0  # as for Poisson targets in Shiu et al.'s code
        self.base_refractory = self._vec(refractory)
        self.refractory = self.base_refractory
        self.decay_membrane, self.decay_synapse = dt / LIF["tau_membrane_ms"], dt / LIF["tau_synapse_ms"]
        side = np.zeros(n, dtype=np.int8)
        side[inputs[0]], side[inputs[1]] = 1, 2
        self.side = self._vec(side)
        self.manipulation = None
        self.scale = self._vec(np.ones(n))
        self.scale_units = self._vec(np.full(n, 1 << 20, dtype=np.int64))
        self.carry_steps = 0
        self.queue_units = None
        self.activation_chance = self._vec(np.zeros(n))
        self.activated_any = False
        self.silenced_mask = self._vec(np.zeros(n, dtype=np.int8))
        self._silenced_key = b""
        self._record_mask = self._record_index = None
        self._recorded, self._recorded_count, self._pending = [], 0, []
        self._drive = self._drive_chance = None
        self.configure(active, signs, parameters)
        self.reset(0)

    def _vec(self, values: np.ndarray, fill=0):
        """A device vector of `size` from n host values (padding with `fill`)."""
        padded = np.full(self.size, fill, dtype=values.dtype)
        padded[:self.n] = values
        return self.torch.from_numpy(padded).to(self.device)

    def configure(self, active: np.ndarray, signs: np.ndarray, parameters):
        """Weights and constants. Spikes already in the delay queue keep the weights they were sent with."""
        p, data, size, torch = parameters.spiking, self.data, self.size, self.torch
        pre, post = data.pre[active], data.post[active]
        if self.fused:
            from digitalfly.neural.gpu_kernels import SYNAPSE_BITS, UNIT
            if self.queue_units is not None:  # queued spikes keep their weights: move them to the float queue
                self.queue += self.queue_units.double() * self.unit
                self.queue_units.zero_()
                self.carry_steps = self.slots
            units = np.rint(signs[pre] * data.synapses[active] * 2 ** SYNAPSE_BITS).astype(np.int64)
            matrix = sparse.csc_matrix((units, (post, pre)), shape=(size, size), dtype=np.int64)
            matrix.sum_duplicates()
            matrix.sort_indices()
            self.colptr = torch.from_numpy(matrix.indptr.astype(np.int64)).to(self.device)
            self.post = torch.from_numpy(matrix.indices.astype(np.int32)).to(self.device)
            self.weight_units = torch.from_numpy(matrix.data.astype(np.int64)).to(self.device)
            self.unit = p.synapse_weight_mv * UNIT
        else:
            weights = signs[pre] * data.synapses[active] * p.synapse_weight_mv
            self.W = _csr(torch, sparse.csr_matrix((weights, (post, pre)), shape=(size, size)), self.device)
        self.parameters = parameters
        self.kick = self.LIF["poisson_scale"] * p.synapse_weight_mv
        self.rate_decay = math.exp(-self.LIF["dt_ms"] / p.rate_window_ms)
        self.rate_jump = 1000 / p.rate_window_ms
        self._drive = None  # the FlyVis chances depend on the input gain and rate

    def manipulate(self, manipulation):
        """Interventions from the next substep, as SpikingState.manipulate."""
        if manipulation is self.manipulation:
            return
        self.manipulation = manipulation
        scale = np.ones(self.n) if manipulation.scale is None else manipulation.scale.astype(np.float64)
        self.scale = self._vec(scale)
        self.scale_units = self._vec(np.rint(scale * (1 << 20)).astype(np.int64))
        chance = np.zeros(self.n)
        chance[manipulation.activated] = np.minimum(1., manipulation.activation * self.LIF["dt_ms"] / 1000)
        self.activation_chance = self._vec(chance)
        self.activated_any = bool(len(manipulation.activated))
        self.refractory = self.base_refractory
        driven = manipulation.activated[manipulation.activation > 0]
        if len(driven):
            self.refractory = self.base_refractory.clone()
            self.refractory[self.torch.from_numpy(driven).to(self.device)] = 0

    def reset(self, seed: int):
        torch, size = self.torch, self.size
        self.v = torch.full((size,), self.LIF["v_rest_mv"], dtype=torch.float64, device=self.device)
        self.g = torch.zeros(size, dtype=torch.float64, device=self.device)
        self.blocked = torch.zeros(size, dtype=torch.int32, device=self.device)
        self.queue = torch.zeros((self.slots, size), dtype=torch.float64, device=self.device)
        if self.fused:  # synapse units queued by the delivery kernel; one run's spikes
            self.queue_units = torch.zeros((self.slots, size), dtype=torch.int64, device=self.device)
            self.spiked = torch.zeros((self.delay, size), dtype=torch.int8, device=self.device)
        self.carry_steps = 0
        self._rate_hz = torch.zeros(size, dtype=torch.float64, device=self.device)
        self._bad.zero_()
        self.step_index = 0
        self.seed, self.seed2 = _seed(seed), _seed(seed + (1 << 40))  # Poisson input; activation
        self.generator = torch.Generator(device=self.device)
        self.generator.manual_seed(self.seed)
        self.version += 1

    # Host views of what SpikingState keeps as arrays, refreshed when read after a step.
    @property
    def rate_hz(self) -> np.ndarray:
        return self._read(self._rate_hz)[:self.n]

    def membrane(self) -> np.ndarray:
        """Membrane potentials on the host (mV)."""
        self._check()
        return self.v[:self.n].cpu().numpy()

    @property
    def record_mask(self):
        return self._record_mask

    @record_mask.setter
    def record_mask(self, mask):
        self._flush_recorded()
        self._record_mask = mask
        self._record_index = None if mask is None else \
            self.torch.from_numpy(np.flatnonzero(mask).astype(np.int64)).to(self.device)

    @property
    def recorded(self) -> list:
        self._flush_recorded()
        return self._recorded

    @recorded.setter
    def recorded(self, value: list):
        self._pending, self._recorded = [], value

    @property
    def recorded_count(self) -> int:
        self._flush_recorded()
        return self._recorded_count

    @recorded_count.setter
    def recorded_count(self, value: int):
        self._recorded_count = value

    def rest(self, neurons: np.ndarray):
        """Silenced neurons to rest at once (apply_silencing): v = v_reset, g = 0, firing rate 0."""
        if len(neurons):
            index = self._to_device(neurons)
            self.v[index], self.g[index], self._rate_hz[index] = self.LIF["v_reset_mv"], 0, 0
            self.version += 1

    def quiet(self, neurons: np.ndarray):
        """Silenced neurons' firing rate reads 0 after a step."""
        if len(neurons):
            self._rate_hz[self._to_device(neurons)] = 0
            self.version += 1

    def _silenced(self, silenced: np.ndarray):
        key = silenced.tobytes()
        if key != self._silenced_key:
            self.silenced_mask.zero_()
            if len(silenced):
                self.silenced_mask[self.torch.from_numpy(silenced.astype(np.int64)).to(self.device)] = 1
            self._silenced_key = key
        return self.silenced_mask

    def _input_chance(self, left: float, right: float, drive: np.ndarray | None):
        """Poisson chance per substep: one per side from the sensors (as SpikingState), or per neuron from FlyVis."""
        p, dt = self.parameters, self.LIF["dt_ms"]
        if drive is None:
            return None, [min(1., p.input_gain * value * p.spiking.input_rate_hz * dt / 1000) for value in (left, right)]
        if self._drive is not drive:
            chance = np.where(drive > 0, np.minimum(1., p.input_gain * drive * p.spiking.input_rate_hz * dt / 1000), 0.)
            self._drive, self._drive_chance = drive, self._vec(chance)
        return self._drive_chance, None

    def advance(self, left: float, right: float, silenced: np.ndarray, drive: np.ndarray | None = None,
                substeps: int | None = None):
        """`substeps` 0.1 ms substeps (by default ten: 1 ms), in runs of at most 18. Returns the number of spikes as a
        0-d device tensor: int() it to wait for the device."""
        total = self.substeps if substeps is None else substeps
        silenced_mask = self._silenced(silenced)
        neuron_chance, side_chance = self._input_chance(left, right, drive)
        count = self.torch.zeros((), dtype=self.torch.int64, device=self.device)
        done = 0
        while done < total:
            run = min(self.delay, total - done)
            self._run(run, silenced_mask, len(silenced) > 0, neuron_chance, side_chance, count)
            done += run
        self._note(self.v)
        if len(self._pending) >= RECORD_FLUSH:
            self._flush_recorded()
        return count

    def _run(self, run, silenced_mask, any_silenced, neuron_chance, side_chance, count):
        """Integrate every neuron through `run` substeps, then queue the run's spikes for delivery 1.8 ms later."""
        torch, size = self.torch, self.size
        start = self.step_index
        if self.fused:
            from digitalfly.neural.gpu_kernels import integrate
            spiked = self.spiked[:run]
            count.add_(integrate(self, run, silenced_mask, neuron_chance, side_chance, spiked))
        else:
            spiked = torch.empty((run, size), dtype=torch.bool, device=self.device)
            out = torch.empty((run, size), dtype=torch.float64, device=self.device)
            self._integrate_eager(run, silenced_mask, any_silenced, neuron_chance, side_chance, out, spiked, count)
            self._deliver(run, out)
        if self._record_index is not None:  # the recorded neurons' spikes stay on the device until read
            self._pending.append((start, spiked[:, self._record_index].bool()))

    def _integrate_eager(self, run, silenced_mask, any_silenced, neuron_chance, side_chance, out, spiked, count):
        """The same substeps in plain PyTorch operations, on any device (without Triton)."""
        torch, L, size = self.torch, self.LIF, self.size
        v, g, blocked, rate_hz = self.v, self.g, self.blocked, self._rate_hz
        silenced = silenced_mask.bool()
        if neuron_chance is None:
            poisson = side_chance[0] > 0 or side_chance[1] > 0
            chance = torch.zeros(size, dtype=torch.float64, device=self.device)
            chance.masked_fill_(self.side == 1, side_chance[0]).masked_fill_(self.side == 2, side_chance[1])
        else:
            poisson, chance = self._drive is not None and bool((self._drive > 0).any()), neuron_chance
        for j in range(run):
            blocked.sub_(1).clamp_(min=0)
            free = blocked == 0
            dv = (L["v_rest_mv"] - v).add_(g).mul_(self.decay_membrane)
            dg = g * self.decay_synapse
            dv.mul_(free)
            dg.mul_(free)
            v.add_(dv)
            g.sub_(dg)
            if any_silenced:
                v.masked_fill_(silenced, L["v_reset_mv"])
                g.masked_fill_(silenced, 0)
            spikes = free & (v > L["v_threshold_mv"])
            torch.mul(spikes, self.scale, out=out[j])
            spiked[j] = spikes
            slot = self.step_index % self.slots
            g.add_(self.queue[slot])
            self.queue[slot].zero_()
            if poisson:
                v.add_((torch.rand(size, generator=self.generator, device=self.device, dtype=torch.float64)
                        < chance).double(), alpha=self.kick)
            if self.activated_any:
                v.add_((torch.rand(size, generator=self.generator, device=self.device, dtype=torch.float64)
                        < self.activation_chance).double(), alpha=self.kick)
            v.masked_fill_(spikes, L["v_reset_mv"])
            g.masked_fill_(spikes, 0)
            torch.where(spikes, self.refractory, blocked, out=blocked)
            rate_hz.mul_(self.rate_decay).add_(spikes.double(), alpha=self.rate_jump)
            count.add_(spikes.sum())
            self.step_index += 1

    def _deliver(self, run: int, spikes):
        """Each spike of the run adds its (scaled) weights to the slot due 1.8 ms after it: one sparse product
        (the eager path; the fused path's kernel visits only the spiking neurons' connections)."""
        torch = self.torch
        delivered = torch.sparse.mm(self.W, spikes.T.contiguous())  # neurons × run
        rows = torch.arange(run, device=self.device).add_(self.step_index - run + self.delay).remainder_(self.slots)
        self.queue.index_add_(0, rows, delivered.T)

    def _flush_recorded(self):
        """Copy recorded spikes to the host as SpikingState keeps them: (substep since the reset, neuron indices)."""
        pending, self._pending = self._pending, []
        if not pending or self._record_index is None:
            return
        index = self._record_index.cpu().numpy()
        hits = self.torch.cat([h for _, h in pending]).cpu().numpy()  # one copy for all pending runs
        steps = np.concatenate([np.arange(start, start + len(h)) for start, h in pending])
        for k in np.flatnonzero(hits.any(axis=1)):
            neurons = index[hits[k]]
            self._recorded.append((int(steps[k]), neurons))
            self._recorded_count += len(neurons)
