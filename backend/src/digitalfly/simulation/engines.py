"""Body adapters. All body poses originate here in Python.

FlyGym construction follows the verified 2.1.0 turning tutorial (Apache-2.0).
Physics, renderer creation, rendering and cleanup must use one owning thread.
"""
from io import BytesIO
from pathlib import Path
import os
import subprocess
import sys
import numpy as np
from digitalfly.api.models import Pose, Stimulus, SensorState, Interventions

ROOT = Path(__file__).resolve().parents[4]
PHYSICS_DT = .0001
CONTROL_DT = .01
NEURAL_DT = .001
LEGS = ["lf", "lm", "lh", "rf", "rm", "rh"]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache/matplotlib"))
os.environ.setdefault("FLYGYM_ASSET_CACHE_DIR", str(ROOT / "data/flygym-assets"))

GL_FIXES = ("start with --toy; or run under a virtual display: MUJOCO_GL=glfw xvfb-run -a ./scripts/start.sh; "
            "or install EGL or OSMesa (Debian/Ubuntu: sudo apt install libegl1, or sudo apt install libosmesa6)")
_GL_PROBE = ("import mujoco\n"
             "m = mujoco.MjModel.from_xml_string('<mujoco><worldbody><light/></worldbody></mujoco>')\n"
             "r = mujoco.Renderer(m, 8, 8)\nr.update_scene(mujoco.MjData(m))\nr.render()\nr.close()\n")
_gl = {}  # this process's choice: {"backend": name, or None when none works, "tried": {backend: reason}}


def probe_gl(backend: str, timeout: float = 60) -> str | None:
    """None if MuJoCo renders offscreen with this MUJOCO_GL backend, else the reason it does not. Runs in a
    child process, because MuJoCo and PyOpenGL fix their backend when first imported."""
    try:
        result = subprocess.run([sys.executable, "-c", _GL_PROBE], env={**os.environ, "MUJOCO_GL": backend},
                                capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"{type(exc).__name__}: {exc}"
    errors = [line for line in result.stderr.strip().splitlines() if line.strip()]
    return None if result.returncode == 0 else (errors[-1] if errors else f"exit code {result.returncode}")


def select_gl() -> str | None:
    """MuJoCo's OpenGL backend, chosen once per process before MuJoCo is imported. An explicit MUJOCO_GL is
    always kept. Otherwise, on Linux, the first that renders: GLFW when there is a display (MuJoCo's default),
    then EGL, then OSMesa. None when none does: physics still runs, without rendering (see gl_help)."""
    if "backend" not in _gl:
        explicit = os.environ.get("MUJOCO_GL")
        _gl.update(backend=explicit or "default", explicit=explicit, tried={})
        if not explicit and sys.platform.startswith("linux") and "mujoco" not in sys.modules:
            display = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
            _gl["backend"] = None
            for backend in ["glfw"] * bool(display) + ["egl", "osmesa"]:
                _gl["tried"][backend] = probe_gl(backend)
                if _gl["tried"][backend] is None:
                    _gl["backend"] = os.environ["MUJOCO_GL"] = backend
                    break
    return _gl["backend"]


def gl_help() -> str:
    tried = ", ".join(name.upper() if name != "osmesa" else "OSMesa" for name in _gl.get("tried", {}))
    return (f"No OpenGL backend works on this computer (tried {tried or 'none'}"
            f"{'' if 'glfw' in _gl.get('tried', {}) else '; GLFW needs a display'}). To fix: {GL_FIXES}.")


class ContactForces:
    """Ground-contact forces on fixed body segments, computed exactly as FlyGym 2.1.0's
    Simulation.get_bodysegment_contact_forces(ground_only=True), with its per-call segment
    and geometry lookups done once. Same contacts, same order, same arithmetic."""

    def __init__(self, sim, fly_name, segments):
        geom_ids = sim._internal_geomid_by_bodyseg_by_fly[fly_name]
        self.output = {int(geom_ids[segment]): i for i, segment in enumerate(segments)}
        self.requested = np.zeros(sim.mj_model.ngeom, dtype=bool)
        self.requested[list(self.output)] = True
        self.ground = np.zeros(sim.mj_model.ngeom, dtype=bool)
        self.ground[np.asarray(sim._internal_ground_geom_ids, dtype=np.int64)] = True
        self.sim, self.fly_name, self.segments = sim, fly_name, segments

    def __call__(self):
        import mujoco
        sim = self.sim
        data = sim.mj_data
        forces = np.zeros((len(self.segments), 3), dtype=float)
        ncon = data.ncon
        if ncon == 0:
            return forces
        contacts = data.contact
        geom1, geom2 = contacts.geom1[:ncon], contacts.geom2[:ncon]
        if geom1.min() < 0 or geom2.min() < 0:  # flex contacts: use the upstream routine
            return sim.get_bodysegment_contact_forces(self.fly_name, self.segments, ground_only=True)
        requested1, requested2 = self.requested[geom1], self.requested[geom2]
        active = (requested1 | requested2) & ~contacts.exclude[:ncon].astype(bool)
        active &= (requested1 & self.ground[geom2]) | (requested2 & self.ground[geom1])
        wrench = np.zeros(6, dtype=float)
        for contact_id in np.where(active)[0]:
            mujoco.mj_contactForce(sim.mj_model, data, int(contact_id), wrench)
            world_force = contacts.frame[contact_id].reshape(3, 3).T @ wrench[:3]
            g1, g2 = int(geom1[contact_id]), int(geom2[contact_id])
            if g1 in self.output:
                forces[self.output[g1]] -= world_force
            if g2 in self.output:
                forces[self.output[g2]] += world_force
        return forces


def fast_turning_controller(timestep, preprogrammed_steps, output_dof_order):
    """FlyGym 2.1.0's HybridTurningController with its per-step bookkeeping precomputed.

    Each physics step the upstream controller rebuilds 42 JointDOF objects and looks
    them up in a dict to order its output. This subclass gathers the same values by
    precomputed index and precomputes the phase-gain breakpoints. Every arithmetic
    operation is the upstream one, in the same order; a FlyGym test checks that the body
    state stays bitwise identical to the upstream controller's.
    """
    from flygym_demo.complex_terrain import HybridTurningController, LocomotionAction
    from flygym_demo.complex_terrain.common import dof_spec_to_jointdof
    from flygym_demo.complex_terrain.hybrid_controller import _CORRECTION_VECTORS, _RIGHT_LEG_CORRECTION_SIGN

    class FastTurningController(HybridTurningController):
        def __post_init__(self):
            super().__post_init__()
            steps = self.preprogrammed_steps
            order = {dof: i for i, dof in enumerate(self.output_dof_order)}
            self._output_index = [[order.get(dof_spec_to_jointdof(leg, spec)) for spec in steps.dofs_per_leg]
                                  for leg in self.legs]
            if any(i is None for row in self._output_index for i in row) or \
                    sorted(i for row in self._output_index for i in row) != list(range(len(self.output_dof_order))):
                raise ValueError("Controller DOFs do not match the requested output order.")
            self._gain_points = {}
            for leg in self.legs:
                swing_start, swing_end = steps.swing_period[leg]
                self._gain_points[leg] = np.array([swing_start, np.mean([swing_start, swing_end]),
                    swing_end + self.swing_extension, np.mean([swing_end, 2 * np.pi]), 2 * np.pi])
            self._gain_values = np.array([0.0, 0.8, 0.0, -0.1, 0.0])
            self._correction = {leg: _CORRECTION_VECTORS[leg[1]] * _RIGHT_LEG_CORRECTION_SIGN
                                if leg.startswith("r") else _CORRECTION_VECTORS[leg[1]] for leg in self.legs}

        def step(self, descending_signal, obs):
            # HybridTurningController.step, unchanged.
            descending_signal = np.asarray(descending_signal, dtype=float)
            if descending_signal.shape != (2,):
                raise ValueError("descending_signal must have shape (2,).")
            self.cpg_network.intrinsic_amps = np.repeat(np.abs(descending_signal[:, np.newaxis]), 3, axis=1).ravel()
            intrinsic_freqs = self._base_intrinsic_freqs.copy()
            intrinsic_freqs[:3] *= 1 if descending_signal[0] >= 0 else -1
            intrinsic_freqs[3:] *= 1 if descending_signal[1] >= 0 else -1
            self.cpg_network.intrinsic_freqs = intrinsic_freqs
            # HybridController.step with precomputed lookups.
            leg_to_correct_retraction = self._select_retraction_leg(obs)
            if leg_to_correct_retraction is not None:
                if self.retraction_correction[leg_to_correct_retraction] > self.retraction_persistence_initiation_threshold:
                    self.retraction_persistence_counter[leg_to_correct_retraction] = 1
            self._update_persistence_counter()
            stumbling_mask = self._get_stumbling_mask(obs)
            self.cpg_network.step()
            joint_angles = np.empty(len(self.output_dof_order), dtype=float)
            adhesion_onoff = []
            net_corrections = np.zeros(6, dtype=float)
            for leg_idx, leg in enumerate(self.legs):
                self._update_retraction_correction(leg_idx, leg_to_correct_retraction)
                self._update_stumbling_correction(leg_idx, stumbling_mask[leg_idx])
                if self.retraction_correction[leg_idx] > 0:
                    net_correction = self.retraction_correction[leg_idx]
                    self.stumbling_correction[leg_idx] = 0
                else:
                    net_correction = self.stumbling_correction[leg_idx]
                phase = self.cpg_network.curr_phases[leg_idx]
                magnitude = self.cpg_network.curr_magnitudes[leg_idx]
                leg_angles = self.preprogrammed_steps.get_joint_angles(leg, phase, magnitude)
                net_correction = np.clip(net_correction, 0, self.max_correction)
                phase_gain = float(np.interp(phase % (2 * np.pi), self._gain_points[leg], self._gain_values))
                leg_angles = leg_angles + net_correction * phase_gain * self._correction[leg]
                net_corrections[leg_idx] = net_correction * phase_gain
                joint_angles[self._output_index[leg_idx]] = leg_angles
                adhesion_onoff.append(self._get_adhesion_onoff(leg, phase) if self.enable_adhesion else False)
            adhesion_onoff = np.array(adhesion_onoff, dtype=bool)
            self.last_info = {
                "net_corrections": net_corrections.copy(),
                "retraction_correction": self.retraction_correction.copy(),
                "stumbling_correction": self.stumbling_correction.copy(),
                "stumbling_mask": stumbling_mask.copy(),
                "leg_to_correct_retraction": leg_to_correct_retraction,
            }
            return LocomotionAction(joint_angles=joint_angles, adhesion_onoff=adhesion_onoff)

    return FastTurningController(timestep=timestep, preprogrammed_steps=preprogrammed_steps,
                                 output_dof_order=output_dof_order)


class FlyGymBody:
    name = "flygym"

    def __init__(self, seed: int, render: bool = True, sensor_model: str = "geometric", upstream: bool = False):
        backend = select_gl()
        if backend is None and sensor_model in ("vision", "flyvis"):
            raise RuntimeError(f"Compound-eye vision renders the eyes with OpenGL. {gl_help()}")
        try:
            import mujoco  # noqa: F401
        except Exception as exc:
            if not _gl["explicit"]:
                raise
            raise RuntimeError(f"MuJoCo could not load MUJOCO_GL={_gl['explicit']}: {type(exc).__name__}: {exc}. Unset MUJOCO_GL "
                               f"to let DigitalFly choose a working backend, or: {GL_FIXES}.") from exc
        from flygym import Simulation
        from flygym.anatomy import ContactBodiesPreset
        from flygym.compose import FlatGroundWorld
        from flygym.utils.math import Rotation3D
        from flygym_demo.complex_terrain import make_locomotion_fly, PreprogrammedSteps, HybridTurningController
        self.sim = None
        self.renderer = None
        self.render_error = None
        self.sensor_model = sensor_model
        self.vision = {}
        self.eye_frame = None
        self._vision_age = 0
        self._visual_input = None
        self.flyvis = None
        self._luminance = None
        try:
            self.fly = make_locomotion_fly(name="specimen", add_adhesion=True, colorize=True)
            if sensor_model in ("vision", "flyvis"):
                self.fly.add_vision()
            self.camera = self.fly.add_tracking_camera(
                name="body_cam", pos_offset=(-.5, -7.5, 3.5),
                rotation=Rotation3D("euler", (1.04, 0, 0)), fovy=35)
            world = FlatGroundWorld()
            # Visual styling only; collision, friction and mass remain upstream defaults.
            texture = world.mjcf_root.texture("checker")
            texture.rgb1 = (.76, .78, .74)
            texture.rgb2 = (.82, .83, .79)
            world.mjcf_root.material("grid").reflectance = 0
            import mujoco
            world.mjcf_root.worldbody.add_geom(name="visual_target", type=mujoco.mjtGeom.mjGEOM_CYLINDER,
                size=(1, 2, 0), pos=(12, 8, 2), rgba=(.08, .75, .12, 1), contype=0, conaffinity=0)
            world.add_fly(self.fly, [0, 0, .8], Rotation3D("quat", [1, 0, 0, 0]),
                          bodysegs_with_ground_contact=ContactBodiesPreset.TIBIA_TARSUS_ONLY,
                          add_ground_contact_sensors=False)
            self.sim = Simulation(world, timestep=PHYSICS_DT)
            self.steps = PreprogrammedSteps()
            self.order = self.fly.get_actuated_jointdofs_order("position")
            # upstream=True keeps FlyGym's own controller and observation code, for equivalence checks.
            self.upstream = upstream
            self.controller = (HybridTurningController if upstream else fast_turning_controller)(
                timestep=PHYSICS_DT, preprogrammed_steps=self.steps, output_dof_order=self.order)
            self.thorax_id = self.sim.mj_model.body("specimen/c_thorax").id
            self.target_id = self.sim.mj_model.geom("visual_target").id
            self.segment_ids = [[self.sim.mj_model.body(f"specimen/{leg}_{part}").id
                                 for part in ["coxa", "trochanterfemur", "tibia", "tarsus1", "tarsus5"]]
                                for leg in LEGS]
            self._prepare_lookups()
            if sensor_model == "flyvis":
                from digitalfly.vision.flyvis_eyes import FlyVisEyes
                self.flyvis = FlyVisEyes(retina=self.sim.retina)
            self.reset(seed)
            if render and backend is None:
                self.render_error = f"Offscreen rendering unavailable. Arena uses actual backend poses. {gl_help()}"
            elif render:
                try:
                    import mujoco
                    self.renderer = mujoco.Renderer(self.sim.mj_model, height=288, width=640)
                except Exception as exc:
                    self.render_error = f"Offscreen rendering unavailable: {type(exc).__name__}: {exc}. Arena uses actual backend poses."
        except Exception:
            self.close()
            raise

    def _prepare_lookups(self):
        """Segment indices that FlyGym otherwise recomputes on every physics step."""
        from flygym.anatomy import BodySegment, LEGS as CONTROLLER_LEGS
        from flygym_demo.complex_terrain.hybrid_controller import _DETECTED_STUMBLING_LINKS
        fly = self.sim.world.fly_lookup[self.fly.name]
        segment = type(fly).BODY_SEGMENT_CLASS
        order = fly.get_bodysegs_order()
        body_ids = self.sim._internal_bodyids_by_fly[self.fly.name]
        self._thorax_body = body_ids[order.index(segment("c_thorax"))]
        self._tarsus_bodies = [body_ids[order.index(segment(f"{leg}_tarsus5"))] for leg in CONTROLLER_LEGS]
        self._stumbling_forces = ContactForces(self.sim, self.fly.name, [
            segment(f"{leg}_{link}") for leg in CONTROLLER_LEGS for link in _DETECTED_STUMBLING_LINKS])
        self._stumbling_shape = (len(CONTROLLER_LEGS), len(_DETECTED_STUMBLING_LINKS), 3)
        self._leg_forces = ContactForces(self.sim, self.fly.name, [
            BodySegment(f"{leg}_{part}") for leg in LEGS
            for part in ["tibia", "tarsus1", "tarsus2", "tarsus3", "tarsus4", "tarsus5"]])

    def _observation(self):
        """HybridControllerObservation.from_sim's values, read through the precomputed indices."""
        from flygym_demo.complex_terrain import HybridControllerObservation
        if self.upstream:
            return HybridControllerObservation.from_sim(self.sim, self.fly.name)
        data = self.sim.mj_data
        return HybridControllerObservation(
            thorax_z=float(data.xpos[self._thorax_body, 2]),
            tarsus5_z=np.array([data.xpos[i, 2] for i in self._tarsus_bodies], dtype=float),
            stumbling_contact_forces=self._stumbling_forces().reshape(self._stumbling_shape),
            fly_heading=data.xmat[self._thorax_body].reshape(3, 3)[:, 0].copy())

    def reset(self, seed: int):
        import mujoco
        from flygym_demo.complex_terrain import LocomotionAction, apply_locomotion_action
        self.sim.reset()
        self.controller.reset(seed=seed)
        apply_locomotion_action(self.sim, self.fly.name, LocomotionAction(
            joint_angles=self.steps.default_pose_by_dof_order(self.order),
            adhesion_onoff=np.ones(6, dtype=bool)))
        self.sim.warmup(duration_s=.05)
        self.sim.mj_data.time = 0
        mujoco.mj_forward(self.sim.mj_model, self.sim.mj_data)
        self.velocity = 0.
        self._visual_input = None
        self._vision_age = 0
        self.vision = {}
        self.eye_frame = None
        self._luminance = None
        self._flyvis_adapt = self.flyvis is not None  # on the first look, once the target is placed
        self.validate()

    def _render_eyes(self, stimulus):
        """Render both eye cameras; keep per-ommatidium luminance (FlyVis) and the display frame."""
        from PIL import Image
        raw = self.sim.get_raw_vision(self.fly.name)
        self._luminance = (self.flyvis.luminance(raw[0]), self.flyvis.luminance(raw[1]))
        self._vision_age = 0
        self.vision = {"ommatidia_per_eye": self.sim.retina.num_ommatidia_per_eye,
            "left": np.round(self._luminance[0], 5).tolist(), "right": np.round(self._luminance[1], 5).tolist(),
            "sample_interval_s": .05, "sample_time_s": float(self.sim.mj_data.time),
            "encoder": "FlyVis (Lappalainen et al. 2024) on per-ommatidium luminance; pooled per cell type and eye"}
        combined = np.concatenate([raw[0], raw[1]], axis=1)
        image = Image.fromarray(combined)
        image.thumbnail((640, 365))
        out = BytesIO(); image.save(out, format="JPEG", quality=85)
        self.eye_frame = out.getvalue()

    def set_stimulus(self, stimulus: Stimulus):
        import mujoco
        self.sim.mj_model.geom_pos[self.target_id] = [stimulus.x, stimulus.y, 2]
        # This landmark is visual only, so moving it never teleports/collides with the body.
        self.sim.mj_model.geom_rgba[self.target_id] = [.08, min(1, .08+.67*stimulus.intensity), .12, 1 if stimulus.intensity else 0]
        mujoco.mj_forward(self.sim.mj_model, self.sim.mj_data)
        self._visual_input = None
        self._luminance = None

    def sensors(self, stimulus: Stimulus, interventions: Interventions) -> SensorState:
        from digitalfly.neural.model import encode
        diagnostic = encode(self.pose(legs=False), stimulus, interventions)
        if self.sensor_model == "flyvis":
            if self._luminance is None or self._vision_age >= 5:
                self._render_eyes(stimulus)
            if self._flyvis_adapt:
                # Adapt FlyVis to the starting scene for 0.5 s, so a run does not begin with a flash.
                self.flyvis.reset()
                self.flyvis.step(*self._luminance, steps=50)
                self._flyvis_adapt = False
            # The circuit reads self.flyvis.responses through its bridge; these are display summaries.
            left, right = (float(v) for v in self.flyvis.responses.mean(axis=1))
            return diagnostic.model_copy(update={"left": 0 if interventions.zero_left else left,
                "right": 0 if interventions.zero_right else right, "raw_left": left, "raw_right": right})
        if self.sensor_model != "vision":
            return diagnostic
        if self._visual_input is None or self._vision_age >= 5:
            from PIL import Image
            # Read actual eye-camera pixels; only this image pipeline supplies neural inputs.
            raw = self.sim.get_raw_vision(self.fly.name)
            rgb = raw.astype(np.float32) / 255
            green = np.clip(rgb[..., 1] - np.maximum(rgb[..., 0], rgb[..., 2]), 0, 1)
            retina = self.sim.retina
            # Pool an explicitly engineered green contrast feature through upstream ommatidia.
            features = np.stack([retina.raw_image_to_hex_pxls(
                np.repeat((eye * 255).astype(np.uint8)[..., None], 3, axis=-1)).sum(axis=-1) for eye in green])
            self._visual_input = np.clip(features.mean(axis=1) * 20, 0, 1)
            self._vision_age = 0
            self.vision = {"ommatidia_per_eye": retina.num_ommatidia_per_eye,
                "left": np.round(features[0], 5).tolist(), "right": np.round(features[1], 5).tolist(),
                "sample_interval_s": .05, "sample_time_s": float(self.sim.mj_data.time),
                "encoder": "20 × mean green contrast across 721 ommatidia per eye; clipped to [0, 1]"}
            combined = np.concatenate([raw[0], raw[1]], axis=1)
            image = Image.fromarray(combined)
            image.thumbnail((640, 365))
            out = BytesIO(); image.save(out, format="JPEG", quality=85)
            self.eye_frame = out.getvalue()
        left, right = self._visual_input.tolist()
        return diagnostic.model_copy(update={"left": 0 if interventions.zero_left else left,
            "right": 0 if interventions.zero_right else right, "raw_left": left, "raw_right": right})

    def advance(self, motor: np.ndarray):
        from flygym_demo.complex_terrain import apply_locomotion_action
        previous = self.sim.mj_data.xpos[self.thorax_id, :2].copy()
        for _ in range(round(CONTROL_DT / PHYSICS_DT)):
            action = self.controller.step(motor, self._observation())
            apply_locomotion_action(self.sim, self.fly.name, action)
            self.sim.step()
        self.validate()
        self.velocity = float(np.linalg.norm(self.sim.mj_data.xpos[self.thorax_id, :2] - previous) / CONTROL_DT)
        if self.flyvis is not None:
            self.flyvis.step(*self._luminance)  # 10 ms of FlyVis with the latest eye images
        self._vision_age += 1

    def body_signals(self):
        if self.upstream:
            segments = self._leg_forces.segments
            forces = self.sim.get_bodysegment_contact_forces(self.fly.name, segments, ground_only=True)
        else:
            forces = self._leg_forces()
        magnitude = np.linalg.norm(forces.reshape(6, 6, 3).sum(axis=1), axis=1)
        return {"leg_order": LEGS, "ground_contact_force": magnitude.tolist(),
            "contact": (magnitude > .01).tolist(), "contact_threshold": .01,
            "cpg_phase_rad": (self.controller.cpg_network.curr_phases % (2*np.pi)).tolist(),
            "joint_position_rad": self.sim.get_joint_angles(self.fly.name).tolist(),
            "force_unit": "uN", "source": "MuJoCo contacts and joint state; upstream CPG phase"}

    def validate(self):
        data = self.sim.mj_data
        if not np.isfinite(data.qpos).all() or not np.isfinite(data.qvel).all():
            raise FloatingPointError("MuJoCo produced nonfinite body state.")
        if np.max(np.abs(data.qvel)) > 1e6:
            raise FloatingPointError("MuJoCo velocity exceeded numerical guard.")
        # MuJoCo can auto-reset a failed step to finite values; catch its warning counters too.
        import mujoco
        for warning in [mujoco.mjtWarning.mjWARN_BADQPOS, mujoco.mjtWarning.mjWARN_BADQVEL, mujoco.mjtWarning.mjWARN_BADQACC]:
            if data.warning[warning].number:
                raise FloatingPointError(f"MuJoCo numerical warning: {warning.name}")

    def planar(self) -> tuple[float, float, float]:
        """x, y and yaw exactly as pose() computes them, without building leg geometry."""
        data = self.sim.mj_data
        x, y, _ = data.xpos[self.thorax_id]
        mat = data.xmat[self.thorax_id].reshape(3, 3)
        return float(x), float(y), float(np.arctan2(mat[1, 0], mat[0, 0]))

    def pose(self, legs: bool = True) -> Pose:
        data = self.sim.mj_data
        x, y, z = data.xpos[self.thorax_id]
        mat = data.xmat[self.thorax_id].reshape(3, 3)
        return Pose(x=float(x), y=float(y), z=float(z),
                    yaw=float(np.arctan2(mat[1, 0], mat[0, 0])), velocity=self.velocity,
                    legs=[data.xpos[ids].tolist() for ids in self.segment_ids] if legs else [])

    def frame(self) -> bytes | None:
        if self.renderer is None:
            return None
        from PIL import Image
        self.renderer.update_scene(self.sim.mj_data, camera=self.camera.name)
        array = self.renderer.render()
        output = BytesIO()
        Image.fromarray(array).save(output, format="JPEG", quality=85)
        return output.getvalue()

    def close(self):
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
        if self.sim is not None:
            self.sim.close()
            self.sim = None


class ToyBody:
    """Explicit kinematic demonstration; no simulated joints or contact physics."""
    name = "toy"
    renderer = None
    render_error = None
    sensor_model = "geometric"
    vision = {}
    eye_frame = None

    def __init__(self, seed: int, render: bool = False, sensor_model: str = "geometric"):
        self.reset(seed)

    def reset(self, seed: int):
        self.rng = np.random.default_rng(seed)
        self.x = self.y = self.velocity = 0.
        self.yaw = float(self.rng.uniform(-.03, .03))

    def advance(self, motor: np.ndarray):
        self.velocity = float(np.mean(motor) * 12)
        self.yaw += float(motor[1] - motor[0]) * 4 * CONTROL_DT
        self.yaw = float(np.arctan2(np.sin(self.yaw), np.cos(self.yaw)))
        self.x += np.cos(self.yaw) * self.velocity * CONTROL_DT
        self.y += np.sin(self.yaw) * self.velocity * CONTROL_DT
        if not np.isfinite([self.x, self.y, self.yaw]).all():
            raise FloatingPointError("Toy body produced nonfinite state.")

    def planar(self) -> tuple[float, float, float]:
        return float(self.x), float(self.y), self.yaw

    def pose(self, legs: bool = True) -> Pose:
        return Pose(x=float(self.x), y=float(self.y), z=.7, yaw=self.yaw, velocity=self.velocity)

    def frame(self):
        return None

    def set_stimulus(self, stimulus):
        pass

    def sensors(self, stimulus, interventions):
        from digitalfly.neural.model import encode
        return encode(self.pose(), stimulus, interventions)

    def body_signals(self):
        return {}

    def close(self):
        pass
