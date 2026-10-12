"""Render the README demo animation from the real simulation.

Every frame comes from the same MuJoCo tracking camera that the workbench shows. The fly
walks to the green target, follows it when it jumps, then stops when its descending units
are silenced. Only the caption bar is drawn on top. Requires an OpenGL context.

    backend/.venv/bin/python scripts/make_demo_gif.py
"""
import argparse
from io import BytesIO
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
from PIL import Image, ImageDraw, ImageFont
from digitalfly.api.models import Interventions, RunConfig, Stimulus
from digitalfly.simulation.experiment import Experiment

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--output", type=Path, default=ROOT / "docs/images/demo.gif")
parser.add_argument("--width", type=int, default=560)
args = parser.parse_args()

# Targets sit in front of the tracking camera so they stay in view.
START = Stimulus(x=10, y=12, intensity=1)
# (step, action, caption): one control step is 10 ms of simulated time.
SCHEDULE = [
    (0, None, "Walking to the green target"),
    (120, Stimulus(x=10.9, y=25.6, intensity=1), "The target jumps: the fly turns and follows"),
    (180, Interventions(silence="descending"), "Descending neurons silenced: it stops short"),
]
END_STEP, FRAME_EVERY = 280, 5  # 2.8 s, one frame per 50 ms, played back in real time


def font(size):
    for candidate in ["/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    return ImageFont.load_default()


def captioned(frame: Image.Image, caption: str, t: float) -> Image.Image:
    bar = 30
    canvas = Image.new("RGB", (frame.width, frame.height + bar), "#2c4538")
    canvas.paste(frame, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((12, frame.height + 7), caption, fill="#f5f4ef", font=font(15))
    stamp = f"t = {t:.1f} s"
    draw.text((frame.width - 12 - draw.textlength(stamp, font=font(13)), frame.height + 9), stamp, fill="#b9c8b7", font=font(13))
    return canvas


exp = Experiment(RunConfig(engine="flygym", seed=42, stimulus=START), render=True)
frames = []
try:
    assert exp.status == "paused", exp.error
    assert exp.body.renderer is not None, exp.body.render_error
    caption = SCHEDULE[0][2]
    for step in range(END_STEP + 1):
        for when, action, text in SCHEDULE:
            if when == step:
                caption = text
                if isinstance(action, Stimulus):
                    exp.set_stimulus(action)
                elif isinstance(action, Interventions):
                    exp.set_interventions(action)
        if step % FRAME_EVERY == 0:
            frames.append(captioned(Image.open(BytesIO(exp.body.frame())).convert("RGB"), caption, exp.t))
        if step < END_STEP:
            exp.advance()
finally:
    exp.close()

scale = args.width / frames[0].width
frames = [f.resize((args.width, round(f.height * scale)), Image.Resampling.LANCZOS) for f in frames]
# One shared palette keeps colors stable from frame to frame.
sample = Image.new("RGB", (frames[0].width, frames[0].height * 4))
for i, f in enumerate(frames[:: max(1, len(frames) // 4)][:4]):
    sample.paste(f, (0, i * f.height))
palette = sample.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
indexed = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
args.output.parent.mkdir(parents=True, exist_ok=True)
indexed[0].save(args.output, save_all=True, append_images=indexed[1:], duration=1000 * FRAME_EVERY // 100,
                loop=0, optimize=True, disposal=1)
print(f"{args.output.relative_to(ROOT)}: {len(frames)} frames, {args.output.stat().st_size / 1e6:.2f} MB")
