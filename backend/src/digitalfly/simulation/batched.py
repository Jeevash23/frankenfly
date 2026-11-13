"""Batched FlyGym worlds on a GPU with MuJoCo Warp (FlyGym 2.1's `flygym.warp.GPUSimulation`). Experimental.

What this measures: the app's FlyGym body (the same fly, adhesion, flat ground and leg contacts as FlyGymBody) in
N worlds stepped together on the GPU, driven by a recorded command sequence, against CPU MuJoCo driven by the same
sequence. It reports throughput (world steps per second) and fidelity (how far each engine's thorax ends up from
the CPU reference after the same commands).

Why it is not wired into the toolkit's trials: every DigitalFly trial is a closed loop at 10 kHz. Each physics step,
FlyGym's hybrid turning controller reads ground-contact forces on the legs (stumbling and retraction corrections),
tarsus heights and the heading, and the brain reads the body every 10 ms. GPUSimulation exposes joint, body and
actuator state but no contact forces, its CPG controller exists only per world on the CPU, and MuJoCo Warp
computes in float32 without the noslip solver (FlyGym strips it), so its trajectories differ from the CPU
engine's, which recorded runs and replay depend on. So batched worlds stay a measurement until the controller and
the contact readout run batched on the GPU. See docs/RESEARCH.md, "Batched worlds (experimental)".
"""
import time
import numpy as np

PHYSICS_DT = .0001


def available() -> tuple[bool, str]:
    import importlib.util
    missing = [name for name in ("warp", "mujoco_warp") if importlib.util.find_spec(name) is None]
    if missing:
        return False, f"{' and '.join(missing)} not installed: use the GPU environment (./scripts/setup.sh --with gpu)."
    try:
        import warp as wp
        wp.config.quiet = True
        wp.init()
        if not wp.is_cuda_available():
            return False, "Warp finds no CUDA device."
    except Exception as exc:
        return False, f"Warp failed to start: {type(exc).__name__}: {exc}"
    return True, "MuJoCo Warp on " + wp.get_cuda_device().name


def build_world():
    """The FlyGym world of simulation.engines.FlyGymBody, without its cameras and visual target."""
    from flygym.anatomy import ContactBodiesPreset
    from flygym.compose import FlatGroundWorld
    from flygym.utils.math import Rotation3D
    from flygym_demo.complex_terrain import make_locomotion_fly
    fly = make_locomotion_fly(name="specimen", add_adhesion=True, colorize=False)
    world = FlatGroundWorld()
    world.add_fly(fly, [0, 0, .8], Rotation3D("quat", [1, 0, 0, 0]),
                  bodysegs_with_ground_contact=ContactBodiesPreset.TIBIA_TARSUS_ONLY, add_ground_contact_sensors=False)
    return world, fly


def record_commands(seconds: float, motor=(1.2, 1.0), seed: int = 0):
    """Run the app's CPU body (fast hybrid turning controller, FlyGym's own physics) with a constant descending
    command; return the joint targets and adhesion it sent each physics step, the thorax path every 10 ms and the
    wall time of the physics alone."""
    from digitalfly.simulation.engines import FlyGymBody
    body = FlyGymBody(seed, render=False)
    try:
        from flygym_demo.complex_terrain import apply_locomotion_action
        steps = round(seconds / PHYSICS_DT)
        joints = np.zeros((steps, len(body.order)), dtype=np.float32)
        adhesion = np.zeros((steps, 6), dtype=np.float32)
        path, physics = [], 0.
        for k in range(steps):
            action = body.controller.step(np.asarray(motor, dtype=float), body._observation())
            joints[k], adhesion[k] = action.joint_angles, action.adhesion_onoff
            apply_locomotion_action(body.sim, body.fly.name, action)
            start = time.perf_counter()
            body.sim.step()
            physics += time.perf_counter() - start
            if k % 100 == 99:
                path.append(body.sim.mj_data.xpos[body.thorax_id, :2].copy())
        return joints, adhesion, np.array(path), physics
    finally:
        body.close()


def default_pose(fly) -> np.ndarray:
    from flygym_demo.complex_terrain import PreprogrammedSteps
    return PreprogrammedSteps().default_pose_by_dof_order(fly.get_actuated_jointdofs_order("position"))


def replay_cpu(joints, adhesion) -> tuple[np.ndarray, float]:
    """CPU MuJoCo (FlyGym's Simulation, the app's engine) driven open loop by recorded commands, after
    FlyGymBody.reset's start: neutral keyframe, default leg pose with adhesion, 50 ms of settling."""
    import mujoco
    from flygym import Simulation
    from flygym.compose.fly import ActuatorType
    world, fly = build_world()
    sim = Simulation(world, timestep=PHYSICS_DT)
    sim.reset()
    sim.set_actuator_inputs(fly.name, ActuatorType.POSITION, default_pose(fly))
    sim.set_leg_adhesion_states(fly.name, np.ones(6))
    sim.warmup(duration_s=.05)
    sim.mj_data.time = 0
    mujoco.mj_forward(sim.mj_model, sim.mj_data)
    thorax = sim.mj_model.body("specimen/c_thorax").id
    path = []
    start = time.perf_counter()
    for k in range(len(joints)):
        sim.set_actuator_inputs(fly.name, ActuatorType.POSITION, joints[k].astype(np.float64))
        sim.set_leg_adhesion_states(fly.name, adhesion[k].astype(np.float64))
        sim.step()
        if k % 100 == 99:
            path.append(sim.mj_data.xpos[thorax, :2].copy())
    return np.array(path), time.perf_counter() - start


def replay_gpu(joints, adhesion, worlds: int, graph: bool = True) -> tuple[np.ndarray, float, dict]:
    """`worlds` MuJoCo Warp worlds, all driven by the recorded commands. Returns world 0's thorax path, the wall
    time of the stepping (commands already on the GPU) and the device memory used."""
    import warp as wp
    import mujoco_warp as mjw
    from flygym.compose.fly import ActuatorType
    from flygym.warp import GPUSimulation
    wp.config.quiet = True
    kernels = _kernels()
    world, fly = build_world()
    sim = GPUSimulation(world, worlds, timestep=PHYSICS_DT)
    # The same start on the CPU side (MuJoCo, without noslip as MuJoCo Warp), then copied to every world.
    import mujoco
    from flygym import Simulation
    Simulation.reset(sim)
    Simulation.set_actuator_inputs(sim, fly.name, ActuatorType.POSITION, default_pose(fly))
    Simulation.set_leg_adhesion_states(sim, fly.name, np.ones(6))
    for _ in range(round(.05 / PHYSICS_DT)):
        mujoco.mj_step(sim.mj_model, sim.mj_data)
    sim.mj_data.time = 0
    mujoco.mj_forward(sim.mj_model, sim.mj_data)
    sim.mjw_model, sim.mjw_data = sim._mj_structs_to_mjw_structs()
    position = sim._wp_intern_actuatorids_by_type_by_fly[ActuatorType.POSITION][fly.name]
    adhesive = sim._wp_intern_adhesionactuatorids_by_fly[fly.name]
    commands = wp.array(np.concatenate([joints, adhesion], axis=1), dtype=wp.float32)
    targets = wp.array(np.concatenate([position.numpy(), adhesive.numpy()]).astype(np.int32), dtype=wp.int32)
    thorax = sim.mj_model.body("specimen/c_thorax").id
    counter = wp.zeros(1, dtype=wp.int32)

    def interval():  # one 10 ms control interval: 100 physics steps, each with its recorded command
        for _ in range(100):
            wp.launch(kernels["broadcast"], dim=(worlds, targets.shape[0]),
                      inputs=[commands, counter, targets, sim.mjw_data.ctrl])
            mjw.step(sim.mjw_model, sim.mjw_data)
            wp.launch(kernels["advance"], dim=1, inputs=[counter])
    if graph:  # record the interval's ~10^4 kernel launches once as a CUDA graph, then replay it
        with wp.ScopedCapture() as capture:
            interval()
        counter.zero_()
    path = []
    wp.synchronize()
    start = time.perf_counter()
    for _ in range(len(joints) // 100):
        wp.capture_launch(capture.graph) if graph else interval()
        path.append(sim.mjw_data.xpos.numpy()[0, thorax, :2].copy())  # as the brain would read the body
    wp.synchronize()
    elapsed = time.perf_counter() - start
    memory = {"warp_mempool_mb": wp.get_mempool_used_mem_current("cuda:0") / 2 ** 20}
    return np.array(path), elapsed, memory


_KERNELS = {}


def _kernels() -> dict:
    """Warp kernels: write step `counter` of the recorded commands into every world's controls; count steps."""
    if not _KERNELS:
        import warp as wp

        @wp.kernel
        def broadcast(commands: wp.array2d(dtype=wp.float32), counter: wp.array(dtype=wp.int32),
                      targets: wp.array(dtype=wp.int32), ctrl: wp.array2d(dtype=wp.float32)):
            w, j = wp.tid()
            ctrl[w, targets[j]] = commands[counter[0], j]

        @wp.kernel
        def advance(counter: wp.array(dtype=wp.int32)):
            counter[0] = counter[0] + 1
        _KERNELS.update(broadcast=broadcast, advance=advance)
    return _KERNELS


def compare_worlds(counts=(1, 16, 64, 256), seconds: float = .5) -> dict:
    """Throughput and fidelity of batched GPU worlds against CPU MuJoCo, after recording `seconds` of walking."""
    ok, reason = available()
    if not ok:
        return {"available": False, "skipped": reason, "rows": []}
    joints, adhesion, closed_path, closed_physics = record_commands(seconds)
    steps = len(joints)
    cpu_path, cpu_time = replay_cpu(joints, adhesion)
    rows = [{"engine": "CPU MuJoCo (open-loop replay)", "worlds": 1, "physics_steps": steps,
             "wall_s": cpu_time, "world_steps_per_s": steps / cpu_time,
             "real_time_factor_per_world": seconds / cpu_time,
             "thorax_end_mm": cpu_path[-1].tolist(), "distance_from_cpu_end_mm": 0.}]
    for worlds in counts:
        replay_gpu(joints[:200], adhesion[:200], worlds)  # compile the kernels
        path, elapsed, memory = replay_gpu(joints, adhesion, worlds)
        rows.append({"engine": "MuJoCo Warp (GPUSimulation)", "worlds": worlds, "physics_steps": steps,
                     "wall_s": elapsed, "world_steps_per_s": worlds * steps / elapsed,
                     "real_time_factor_per_world": seconds / elapsed, **memory,
                     "thorax_end_mm": path[-1].tolist(),
                     "distance_from_cpu_end_mm": float(np.linalg.norm(path[-1] - cpu_path[-1])),
                     "max_distance_from_cpu_mm": float(np.linalg.norm(path - cpu_path, axis=1).max())})
    travelled = float(np.linalg.norm(cpu_path[-1] - cpu_path[0]))
    return {"available": True, "device": reason, "simulated_s": seconds, "physics_dt_s": PHYSICS_DT,
            "commands": "recorded from the app's FlyGym body with descending command [1.2, 1.0] (a right turn), seed 0",
            "closed_loop_physics_s": closed_physics, "cpu_replay_matches_closed_loop_mm":
                float(np.linalg.norm(cpu_path - closed_path, axis=1).max()),
            "cpu_path_length_mm": travelled, "rows": rows,
            "note": "Throughput excludes the controller (commands are replayed). Distances compare world 0's thorax "
                    "with CPU MuJoCo after the same commands; all worlds receive the same commands."}
