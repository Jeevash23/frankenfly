"""Bounded upstream-style smoke test, before using the application adapter.

Adapted from FlyGym 2.1.0 tutorial 4d (Apache-2.0, NeLy-EPFL).
https://neuromechfly.org/tutorials/4d_turning_controller/
"""
import json
import os
from pathlib import Path
import platform
import time

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache/matplotlib"))
os.environ.setdefault("FLYGYM_ASSET_CACHE_DIR", str(ROOT / "data/flygym-assets"))

import numpy as np
import psutil
from PIL import Image
from flygym import Simulation
from flygym.anatomy import BodySegment, ContactBodiesPreset
from flygym.compose import FlatGroundWorld
from flygym.utils.math import Rotation3D
from flygym_demo.complex_terrain import (
    HybridTurningController, HybridControllerObservation, LocomotionAction,
    PreprogrammedSteps, apply_locomotion_action, make_locomotion_fly,
)


def smoke():
    fly = make_locomotion_fly(name="specimen", add_adhesion=True, colorize=True)
    camera = fly.add_tracking_camera(
        name="body_cam", pos_offset=(-0.5, -7.5, 3.5),
        rotation=Rotation3D("euler", (1.13, 0, 0)), fovy=40,
    )
    world = FlatGroundWorld()
    world.add_fly(fly, [0, 0, 0.8], Rotation3D("quat", [1, 0, 0, 0]),
                  bodysegs_with_ground_contact=ContactBodiesPreset.TIBIA_TARSUS_ONLY,
                  add_ground_contact_sensors=False)
    started = time.perf_counter()
    sim = Simulation(world, timestep=0.0001)
    try:
        renderer = sim.set_renderer([camera], camera_res=(360, 640),
                                    buffer_frames=True, output_fps=10, playback_speed=1)
        steps = PreprogrammedSteps()
        order = fly.get_actuated_jointdofs_order("position")
        ctrl = HybridTurningController(timestep=sim.timestep, preprogrammed_steps=steps,
                                       output_dof_order=order)
        sim.reset()
        ctrl.reset(seed=42)
        apply_locomotion_action(sim, fly.name, LocomotionAction(
            joint_angles=steps.default_pose_by_dof_order(order),
            adhesion_onoff=np.ones(6, dtype=bool)))
        sim.warmup()
        idx = fly.get_bodysegs_order().index(BodySegment("c_thorax"))
        initial = sim.get_body_positions(fly.name)[idx].copy()
        sim.render_as_needed()
        before = time.perf_counter()
        for i in range(10000):
            obs = HybridControllerObservation.from_sim(sim, fly.name)
            action = ctrl.step(np.array([1.0, 1.0]) if i < 5000 else np.array([0.5, 1.2]), obs)
            apply_locomotion_action(sim, fly.name, action)
            sim.step()
            if i % 1000 == 0:
                assert np.isfinite(sim.mj_data.qpos).all()
                sim.render_as_needed()
        elapsed = time.perf_counter() - before
        final = sim.get_body_positions(fly.name)[idx].copy()
        assert np.linalg.norm(final[:2] - initial[:2]) > 0.1, "No locomotion detected"
        assert np.isfinite(sim.mj_data.qvel).all()
        sim.render_as_needed()
        frames = renderer.frames[camera.name]
        assert frames and frames[-1].std() > 2, "Blank renderer output"
        Image.fromarray(frames[-1]).save(ROOT / "docs/evidence/flygym-smoke.png")
        result = {"platform": platform.platform(), "python": platform.python_version(),
                  "flygym": "2.1.0", "physics_dt_s": sim.timestep, "physics_steps": 10000,
                  "simulated_s": 1.0, "wall_s": elapsed, "real_time_factor": 1 / elapsed,
                  "initial_mm": initial.tolist(), "final_mm": final.tolist(),
                  "displacement_mm": (final-initial).tolist(), "render_size": [640, 360],
                  "frames": len(frames), "rss_mb": psutil.Process().memory_info().rss / 1e6,
                  "total_wall_s": time.perf_counter() - started, "finite": True}
    finally:
        sim.close()
    result["closed"] = True
    (ROOT / "docs/evidence/flygym-smoke.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    smoke()
