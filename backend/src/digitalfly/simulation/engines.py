"""Body adapters. All body poses originate here in Python.

FlyGym construction follows the verified 2.1.0 turning tutorial (Apache-2.0).
Physics, renderer creation, rendering and cleanup must use one owning thread.
"""
from io import BytesIO
from pathlib import Path
import os
import numpy as np
from digitalfly.api.models import Pose, Stimulus, SensorState, Interventions

ROOT = Path(__file__).resolve().parents[4]
PHYSICS_DT = .0001
CONTROL_DT = .01
NEURAL_DT = .001
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache/matplotlib"))
os.environ.setdefault("FLYGYM_ASSET_CACHE_DIR", str(ROOT / "data/flygym-assets"))


class FlyGymBody:
    name = "flygym"

    def __init__(self, seed: int, render: bool = True, sensor_model: str = "geometric"):
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
        try:
            self.fly = make_locomotion_fly(name="specimen", add_adhesion=True, colorize=True)
            if sensor_model == "vision":
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
            self.controller = HybridTurningController(timestep=PHYSICS_DT,
                preprogrammed_steps=self.steps, output_dof_order=self.order)
            self.thorax_id = self.sim.mj_model.body("specimen/c_thorax").id
            self.target_id = self.sim.mj_model.geom("visual_target").id
            self.segment_ids = [[self.sim.mj_model.body(f"specimen/{leg}_{part}").id
                                 for part in ["coxa", "trochanterfemur", "tibia", "tarsus1", "tarsus5"]]
                                for leg in ["lf", "lm", "lh", "rf", "rm", "rh"]]
            self.reset(seed)
            if render:
                try:
                    import mujoco
                    self.renderer = mujoco.Renderer(self.sim.mj_model, height=288, width=640)
                except Exception as exc:
                    self.render_error = f"Offscreen rendering unavailable: {type(exc).__name__}: {exc}. Arena uses actual backend poses."
        except Exception:
            self.close()
            raise

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
        self.validate()

    def set_stimulus(self, stimulus: Stimulus):
        import mujoco
        self.sim.mj_model.geom_pos[self.target_id] = [stimulus.x, stimulus.y, 2]
        # This landmark is visual only, so moving it never teleports/collides with the body.
        self.sim.mj_model.geom_rgba[self.target_id] = [.08, min(1, .08+.67*stimulus.intensity), .12, 1 if stimulus.intensity else 0]
        mujoco.mj_forward(self.sim.mj_model, self.sim.mj_data)
        self._visual_input = None

    def sensors(self, stimulus: Stimulus, interventions: Interventions) -> SensorState:
        from digitalfly.neural.model import encode
        diagnostic = encode(self.pose(), stimulus, interventions)
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
        from flygym_demo.complex_terrain import HybridControllerObservation, apply_locomotion_action
        previous = self.sim.mj_data.xpos[self.thorax_id, :2].copy()
        for _ in range(round(CONTROL_DT / PHYSICS_DT)):
            obs = HybridControllerObservation.from_sim(self.sim, self.fly.name)
            action = self.controller.step(motor, obs)
            apply_locomotion_action(self.sim, self.fly.name, action)
            self.sim.step()
        self.validate()
        self.velocity = float(np.linalg.norm(self.sim.mj_data.xpos[self.thorax_id, :2] - previous) / CONTROL_DT)
        self._vision_age += 1

    def body_signals(self):
        from flygym.anatomy import BodySegment
        legs = ["lf", "lm", "lh", "rf", "rm", "rh"]
        segments = [BodySegment(f"{leg}_{part}") for leg in legs for part in ["tibia", "tarsus1", "tarsus2", "tarsus3", "tarsus4", "tarsus5"]]
        forces = self.sim.get_bodysegment_contact_forces(self.fly.name, segments, ground_only=True).reshape(6, 6, 3)
        magnitude = np.linalg.norm(forces.sum(axis=1), axis=1)
        return {"leg_order": legs, "ground_contact_force": magnitude.tolist(),
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

    def pose(self) -> Pose:
        data = self.sim.mj_data
        x, y, z = data.xpos[self.thorax_id]
        mat = data.xmat[self.thorax_id].reshape(3, 3)
        return Pose(x=float(x), y=float(y), z=float(z),
                    yaw=float(np.arctan2(mat[1, 0], mat[0, 0])), velocity=self.velocity,
                    legs=[data.xpos[ids].tolist() for ids in self.segment_ids])

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

    def pose(self) -> Pose:
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
