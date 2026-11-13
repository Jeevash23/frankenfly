"""The Triton kernels of the torch backend's spiking dynamics (CUDA only; neural/gpu.py imports them lazily).

_lif_run advances a block of neurons through a whole run of substeps (at most 18, the synaptic delay), in the order
of connectome.SpikingState: refractory countdown, state update, silencing, threshold, delayed input, Poisson input,
reset, and marks each spike in a (substeps × neurons) array. Random numbers are Philox (counter-based) with one
counter per (substep, neuron): they depend only on the run's seed, the substep and the neuron, never on how the
substeps were grouped into runs.

_deliver then adds each spike's outgoing weights to the delay-queue slot due 1.8 ms after it, touching only the
spiking neurons' connections (the spikes are listed with torch.nonzero_static, which needs no host wait). The queue counts synapses in fixed point (sign × synapses × 2^8 × output scale × 2^20,
int64), so the atomic additions give the same sum in any order and a run repeats exactly for its seed; the weight
per synapse multiplies when the slot is delivered.

Float parameters go in as their 64-bit patterns: Triton would pass a Python float as float32. The state arrays have
room for a whole number of blocks, so no lane is ever masked (partial blocks gave wrong results with Triton 3.7.1).
"""
import struct
import torch
import triton
import triton.language as tl

BLOCK = 256
EDGE_BLOCK = 64
PROGRAMS = 512
SYNAPSE_BITS = 8  # synapse counts in units of 1/256 (whole counts are exact)
SCALE_BITS = 20  # output scale in units of 2^-20
UNIT = 2.0 ** -(SYNAPSE_BITS + SCALE_BITS)


def f64(value: float) -> int:
    """The bit pattern of a float64, for _f inside a kernel."""
    return struct.unpack("<q", struct.pack("<d", float(value)))[0]


@triton.jit
def _f(bits):
    return bits.to(tl.int64).to(tl.float64, bitcast=True)


@triton.jit
def _lif_run(v_ptr, g_ptr, blocked_ptr, rate_ptr, refractory_ptr, queue_ptr, carry_ptr, side_ptr, chance_ptr,
             act_chance_ptr, silenced_ptr, spiked_ptr,
             n, run, step0, slots, seed, seed2, chance_left, chance_right, unit,
             v_rest, v_reset, v_threshold, decay_membrane, decay_synapse, kick, rate_decay, rate_jump,
             PER_NEURON: tl.constexpr, ACTIVATED: tl.constexpr, CARRY: tl.constexpr, BLOCK: tl.constexpr):
    chance_left, chance_right, unit = _f(chance_left), _f(chance_right), _f(unit)
    v_rest, v_reset, v_threshold = _f(v_rest), _f(v_reset), _f(v_threshold)
    decay_membrane, decay_synapse, kick = _f(decay_membrane), _f(decay_synapse), _f(kick)
    rate_decay, rate_jump = _f(rate_decay), _f(rate_jump)
    i = tl.program_id(0) * BLOCK + tl.arange(0, BLOCK)
    v = tl.load(v_ptr + i)
    g = tl.load(g_ptr + i)
    blocked = tl.load(blocked_ptr + i)
    rate = tl.load(rate_ptr + i)
    refractory = tl.load(refractory_ptr + i)
    silenced = tl.load(silenced_ptr + i) != 0
    if PER_NEURON:
        chance = tl.load(chance_ptr + i)
    else:
        side = tl.load(side_ptr + i)
        chance = tl.where(side == 1, chance_left, tl.where(side == 2, chance_right, 0.))
    if ACTIVATED:
        act_chance = tl.load(act_chance_ptr + i)
    for j in range(run):
        t = step0 + j
        blocked = tl.maximum(blocked - 1, 0)
        free = blocked == 0
        freef = free.to(tl.float64)
        dv = (v_rest - v + g) * decay_membrane * freef
        dg = g * decay_synapse * freef
        v = v + dv
        g = g - dg
        v = tl.where(silenced, v_reset, v)
        g = tl.where(silenced, 0., g)
        spike = free & (v > v_threshold)
        tl.store(spiked_ptr + j * n + i, spike.to(tl.int8))
        slot = t % slots
        g = g + tl.load(queue_ptr + slot * n + i).to(tl.float64) * unit
        tl.store(queue_ptr + slot * n + i, tl.zeros([BLOCK], dtype=tl.int64))
        if CARRY:  # spikes queued before a parameter edit, with the weights they were sent with
            g = g + tl.load(carry_ptr + slot * n + i)
            tl.store(carry_ptr + slot * n + i, tl.zeros([BLOCK], dtype=tl.float64))
        offset = t.to(tl.int64) * n + i
        v = tl.where(tl.rand(seed, offset).to(tl.float64) < chance, v + kick, v)
        if ACTIVATED:
            v = tl.where(tl.rand(seed2, offset).to(tl.float64) < act_chance, v + kick, v)
        v = tl.where(spike, v_reset, v)
        g = tl.where(spike, 0., g)
        blocked = tl.where(spike, refractory, blocked)
        rate = rate * rate_decay
        rate = tl.where(spike, rate + rate_jump, rate)
    tl.store(v_ptr + i, v)
    tl.store(g_ptr + i, g)
    tl.store(blocked_ptr + i, blocked)
    tl.store(rate_ptr + i, rate)


@triton.jit
def _deliver(spikes_ptr, total_ptr, colptr_ptr, post_ptr, weight_ptr, scale_ptr, queue_ptr, n, step0, delay, slots,
             PROGRAMS: tl.constexpr, EDGE_BLOCK: tl.constexpr):
    total = tl.load(total_ptr)
    for s in range(tl.program_id(0), total, PROGRAMS):
        code = tl.load(spikes_ptr + s)  # substep of the run × n + neuron
        neuron = code % n
        row = ((step0 + code // n + delay) % slots) * n
        scale = tl.load(scale_ptr + neuron)
        start = tl.load(colptr_ptr + neuron)
        end = tl.load(colptr_ptr + neuron + 1)
        for e in range(start, end, EDGE_BLOCK):
            offs = e + tl.arange(0, EDGE_BLOCK)
            keep = offs < end
            post = tl.load(post_ptr + offs, mask=keep, other=0)
            weight = tl.load(weight_ptr + offs, mask=keep, other=0)
            tl.atomic_add(queue_ptr + row + post, weight * scale, mask=keep)


def integrate(state, run, silenced_mask, neuron_chance, side_chance, spiked):
    """Advance a TorchSpikingState by `run` substeps and queue the run's spikes. `spiked` (run × n, int8) receives
    the spikes; returns their number (a 0-d device tensor)."""
    L = state.LIF
    per_neuron = neuron_chance is not None
    left, right = (0., 0.) if per_neuron else (float(side_chance[0]), float(side_chance[1]))
    n = state.size  # a whole number of blocks (TorchSpikingState pads), so no lane is masked
    _lif_run[(triton.cdiv(n, BLOCK),)](
        state.v, state.g, state.blocked, state._rate_hz, state.refractory, state.queue_units, state.queue,
        state.side, neuron_chance if per_neuron else state.v, state.activation_chance, silenced_mask, spiked,
        n, run, state.step_index, state.slots, state.seed, state.seed2, f64(left), f64(right), f64(state.unit),
        f64(L["v_rest_mv"]), f64(L["v_reset_mv"]), f64(L["v_threshold_mv"]), f64(state.decay_membrane),
        f64(state.decay_synapse), f64(state.kick), f64(state.rate_decay), f64(state.rate_jump),
        PER_NEURON=per_neuron, ACTIVATED=state.activated_any, CARRY=state.carry_steps > 0, BLOCK=BLOCK)
    total = spiked.sum()
    spikes = torch.nonzero_static(spiked.view(-1), size=run * n, fill_value=-1)  # in order; no host wait
    _deliver[(PROGRAMS,)](spikes, total, state.colptr, state.post, state.weight_units, state.scale_units,
                          state.queue_units, n, state.step_index, state.delay, state.slots,
                          PROGRAMS=PROGRAMS, EDGE_BLOCK=EDGE_BLOCK)
    state.step_index += run
    state.carry_steps = max(0, state.carry_steps - run)
    return total
