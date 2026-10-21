"""DigitalFly research toolkit from the command line: trials, sweeps, bias curves, ablation scans and paths.

    backend/.venv/bin/python scripts/toolkit.py trials --set neural_model=connectome --vary connectome_parameters.dynamics=rate,spiking
    backend/.venv/bin/python scripts/toolkit.py bias --set circuit=fafb783-steering
    backend/.venv/bin/python scripts/toolkit.py ablation --top 20 --workers 8
    backend/.venv/bin/python scripts/toolkit.py paths --source LC10a --target DNa02
    backend/.venv/bin/python scripts/toolkit.py jump --set neural_model=connectome --set seed=3 --duration 60 --jump-seed 11
    backend/.venv/bin/python scripts/toolkit.py compare --recording fly.csv --run runs/<run folder>
    backend/.venv/bin/python scripts/toolkit.py circuits

--set and --vary take dotted RunConfig names (for bias, ablation and paths: ConnectomeParameters names,
with or without the "connectome_parameters." prefix). Values are read as JSON when they parse
(numbers, true/false, ["lists"]) and as text otherwise. Results are printed as Markdown and saved as
JSON (plus CSV for tables) under runs/toolkit/ (ignored by git) unless --out names a file; every
report records its provenance (git commit, command line, circuits and their SHA-256, package
versions). `circuits` only prints the list. `trials` also appends each finished trial to a .jsonl
and the .csv while it runs; a trial that fails becomes a row with an error, and --resume skips the
trials already saved. Every result describes this simulation, not fly behavior.
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
from digitalfly import toolkit  # noqa: E402
from digitalfly.api.models import ConnectomeParameters  # noqa: E402
from digitalfly.neural.connectome import list_circuits, trace_paths  # noqa: E402

PREFIX = "connectome_parameters."
# Settings that `trials` also builds from --seeds, --bearings and --distances.
POSITION_KEYS = {"stimulus", "stimulus.x", "stimulus.y"}
DEFAULTS = {"bearings": "0,45,-45,90,-90,180", "distances": "12,30", "seeds": "1-5"}


def value(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def settings(pairs):
    result = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            sys.exit(f"Use KEY=VALUE, not {pair!r}.")
        result[key.strip()] = value(raw)
    return result


def axes(pairs):
    result = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep:
            sys.exit(f"Use KEY=V1,V2 for --vary, not {pair!r}.")
        result[key.strip()] = [value(v) for v in raw.split(",")] if not raw.startswith("[[") else value(raw)
    return result


def numbers(text, kind=float):
    out = []
    for part in text.split(","):
        if "-" in part[1:] and kind is int:
            start, end = part.split("-")
            out += list(range(int(start), int(end) + 1))
        else:
            out.append(kind(part))
    return out


def parameters(pairs) -> ConnectomeParameters:
    return ConnectomeParameters.model_validate({k.removeprefix(PREFIX): v for k, v in settings(pairs).items()})


def output_stem(name, out):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    base = Path(out) if out else ROOT / "runs/toolkit" / f"{stamp}-{name}"
    base.parent.mkdir(parents=True, exist_ok=True)
    return base.with_suffix("") if base.suffix in {".csv", ".json", ".jsonl"} else base


def shown(path):
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def write_csv(path, rows):
    """Rows as CSV, leaving out list and dict values; returns the columns."""
    flat = [{k: v for k, v in r.items() if not isinstance(v, (list, dict))} for r in rows]
    fields = list(dict.fromkeys(k for r in flat for k in r))
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(flat)
    return fields


def save(stem, rows, report, circuits=()):
    report = {**report, "provenance": toolkit.provenance(circuits)}
    stem.with_suffix(".json").write_text(json.dumps(report, indent=1, default=str))
    if rows:
        write_csv(stem.with_suffix(".csv"), rows)
    print(f"\nSaved {shown(stem)}.json" + (f" and {shown(stem)}.csv" if rows else ""))


class TrialLog:
    """Trial rows appended to <stem>.jsonl and <stem>.csv as they finish, so a failing or interrupted sweep keeps
    every finished trial. With resume, rows already in the JSONL without an error are reused by config hash."""

    def __init__(self, stem, resume):
        self.jsonl, self.csv = stem.with_suffix(".jsonl"), stem.with_suffix(".csv")
        self.saved, self.rows, self.fields = {}, [], []
        if resume and self.jsonl.is_file():
            for line in self.jsonl.read_text().splitlines():
                row = json.loads(line) if line.strip() else {}
                if row.get("config_hash") and not row.get("error"):
                    self.saved[row["config_hash"]] = row
        elif not resume:
            self.jsonl.unlink(missing_ok=True)
        self.rows = list(self.saved.values())
        if self.rows:
            self.fields = write_csv(self.csv, self.rows)
        else:
            self.csv.unlink(missing_ok=True)

    def add(self, row):
        with self.jsonl.open("a") as handle:
            handle.write(json.dumps(row, default=str) + "\n")
        self.rows.append(row)
        flat = {k: v for k, v in row.items() if not isinstance(v, (list, dict))}
        if not self.fields or set(flat) - set(self.fields):  # a new column: rewrite with the wider header
            self.fields = write_csv(self.csv, self.rows)
            return
        with self.csv.open("a", newline="") as handle:
            csv.DictWriter(handle, fieldnames=self.fields).writerow(flat)


def interval(ci, fmt="{:.1f}", scale=1, unit=""):
    return "n/a" if ci is None else f"{fmt.format(ci[0] * scale)} to {fmt.format(ci[1] * scale)}{unit}"


def percent(ci):
    return interval(ci, "{:.0f}", 100, "%")


def trials(args):
    fixed, varied = settings(args.set), axes(args.vary)
    named = set(fixed) | set(varied)
    own_seed, own_position = "seed" in named, bool(named & POSITION_KEYS)
    if own_seed and args.seeds is not None:
        sys.exit("--set/--vary already set seed; leave out --seeds, or the seed setting.")
    if own_position and (args.bearings is not None or args.distances is not None):
        sys.exit("--set/--vary already set the target position; leave out --bearings/--distances, or that setting.")
    if args.resume and not args.out:
        sys.exit("--resume needs --out naming the earlier output.")
    base = toolkit.configure({"engine": args.engine}, **fixed)
    seeds = [None] if own_seed else numbers(args.seeds or DEFAULTS["seeds"], int)
    positions = [None] if own_position else [(b, d) for b in numbers(args.bearings or DEFAULTS["bearings"])
                                             for d in numbers(args.distances or DEFAULTS["distances"])]
    configs, keys = [], list(varied)
    for config in toolkit.grid(base, **varied) if varied else [base]:
        for position in positions:
            for seed in seeds:
                extra = {} if seed is None else {"seed": seed}
                if position is not None:  # keeps the configured intensity
                    extra["stimulus"] = toolkit.target(*position, intensity=config.stimulus.intensity)
                configs.append(toolkit.configure(config, **extra))
    run = {"duration_s": args.duration}
    stem = output_stem("trials", args.out)
    log = TrialLog(stem, args.resume)
    hashes = [toolkit.config_hash(c, **run) for c in configs]
    todo = [k for k, h in enumerate(hashes) if h not in log.saved]
    print(f"Running {len(todo)} trials of {args.duration:g} simulated s on {args.workers} worker(s)"
          + (f"; {len(configs) - len(todo)} already saved in {shown(log.jsonl)}" if len(todo) < len(configs) else "")
          + f"; finished trials go to {shown(log.jsonl)} …", flush=True)

    def finished(index, row):
        log.add({"trial": todo[index], **row})
        if row["error"]:
            print(f"Trial {todo[index]} failed: {row['error']}", file=sys.stderr, flush=True)
    new = dict(zip(todo, toolkit.run_trials([configs[k] for k in todo], workers=args.workers, on_result=finished, **run)))
    rows = [{"trial": k, **{x: y for x, y in (new[k] if k in new else log.saved[h]).items() if x != "trial"}}
            for k, h in enumerate(hashes)]
    # Seeds are replicates: statistics pool them and pair conditions on them.
    group_keys = [k.split(".")[-1] for k in keys if k != "seed"] or ["neural_model"]
    for row, config in zip(rows, configs):
        for key in keys:
            node = config.model_dump()
            for part in key.split("."):
                node = node[part]
            row[key.split(".")[-1]] = json.dumps(node) if isinstance(node, (list, dict)) else node
    summary = toolkit.summarize(rows, group_keys)
    print("\n| " + " | ".join(group_keys) + " | Reached ≤2 mm (95% CI) | First turn toward (lateral targets, 95% CI) | "
          "Final distance: median; mean (95% CI) | Mean speed |")
    print("|" + " --- |" * (len(group_keys) + 4))
    for c in summary["conditions"]:
        ok = c["trials"] - c["errors"]
        final, speed = c["final_distance_mm"], c["mean_speed_mm_s"]
        print("| " + " | ".join(str(v) for v in c["condition"].values())
              + f" | {c['reached']}/{ok} ({percent(c['reached_ci95'])})"
              + (f", {c['errors']} failed" if c["errors"] else "")
              + f" | {c['first_turn_toward']}/{c['lateral_trials']} ({percent(c['first_turn_toward_ci95'])})"
              + (f" | {final['median']:.1f}; {final['mean']:.1f} ({interval(final['ci95'], unit=' mm')})"
                 f" | {speed['mean']:.1f} mm/s |" if ok else " | — | — |"))
    if summary["paired_differences"]:
        base_name = ", ".join(map(str, summary["paired_differences"][0]["baseline"].values()))
        print(f"\nPaired with {base_name} (same seeds and targets): condition − baseline.\n")
        print("| " + " | ".join(group_keys) + " | Pairs | Δ reached (95% CI) | Δ final distance, mm (95% CI) |")
        print("|" + " --- |" * (len(group_keys) + 3))
        for p in summary["paired_differences"]:
            reached, final = p["reached"], p["final_distance_mm"]
            print("| " + " | ".join(str(v) for v in p["condition"].values()) + f" | {p['pairs']} | "
                  + (f"{reached['mean_difference']:+.2f} ({interval(reached['ci95'], '{:+.2f}')}) | "
                     f"{final['mean_difference']:+.1f} ({interval(final['ci95'], '{:+.1f}')}) |" if p["pairs"] else "— | — |"))
    errors = sum(bool(r["error"]) for r in rows)
    circuits = [c.connectome_parameters.circuit for c in configs if c.neural_model == "connectome"]
    save(stem, rows, {"command": "trials", "base": base.model_dump(), "vary": varied, "duration_s": args.duration,
                      "seeds": seeds if not own_seed else "from --set/--vary", "errors": errors, "statistics": summary,
                      "scope": "Simulated behavior; no biological validation.", "trials": rows}, circuits)
    if errors:
        sys.exit(f"{errors} of {len(rows)} trials failed (see the error column); they are left out of the statistics. "
                 "Rerun with --resume and the same --out to retry only those.")


def bias(args):
    p = parameters(args.set)
    curve = toolkit.bias_curve(p, levels=numbers(args.levels), differences=numbers(args.differences), ms=args.ms,
                               average_ms=args.average_ms, seed=args.seed)
    print(f"Circuit {p.circuit}, {p.dynamics} dynamics. Positive turn = rightward.\n")
    print("| Mean input | Right − left input | Turn command |\n| --- | --- | --- |")
    for row in curve["rows"]:
        print(f"| {row['level']:g} | {row['right_minus_left']:+g} | {row['turn']:+.4f} |")
    if curve["mirror_asymmetry"] is not None:
        print(f"\nMirror asymmetry {curve['mirror_asymmetry']:.3f} (0 for a left-right symmetric circuit).")
    save(output_stem("bias", args.out), curve["rows"], {"command": "bias", "parameters": p.model_dump(), **curve}, [p.circuit])


def ablation(args):
    p = parameters(args.set)
    types = [t for t in args.types.split(",") if t] if args.types else []
    types += args.type  # repeatable, for names that contain commas
    scan = toolkit.ablation_scan(p, left=args.left, right=args.right, ms=args.ms, cell_types=types or None,
                                 workers=args.workers, average_ms=args.average_ms, seed=args.seed)
    print(f"Circuit {scan['circuit']}, {scan['dynamics']} dynamics, sensors {args.left:g}/{args.right:g}: "
          f"intact turn {scan['intact_turn']:+.4f} ({scan['types_scanned']} types silenced one at a time).\n")
    print("| Silenced cell type | Neurons (left/right) | Turn | Change |\n| --- | --- | --- | --- |")
    for row in scan["rows"][:args.top]:
        print(f"| {row['cell_type']} | {row['neurons']} ({row['left']}/{row['right']}) | {row['turn']:+.4f} | {row['change']:+.4f} |")
    print("\nPositive change: the type was pushing the fly to the left.")
    save(output_stem("ablation", args.out), scan["rows"], {"command": "ablation", "parameters": p.model_dump(), **scan},
         [p.circuit])


def paths(args):
    p = parameters(args.set)
    result = trace_paths(p, args.source, args.target, args.hops, args.limit)
    print(f"Strongest paths from {args.source} to {args.target} in {result['circuit']} (≤{args.hops} steps):\n")
    print("| Path | Strength | Net sign |\n| --- | --- | --- |")
    for path in result["paths"]:
        print(f"| {' → '.join(path['cell_types'])} | {path['strength']:.4g} | {'+' if path['net_sign'] > 0 else '−'} |")
    print(f"\n{result['rule']}")
    rows = [{"path": " → ".join(path["cell_types"]), "steps": len(path["cell_types"]) - 1, "strength": path["strength"],
             "net_sign": path["net_sign"]} for path in result["paths"]]
    save(output_stem("paths", args.out), rows, {"command": "paths", "parameters": p.model_dump(), **result}, [p.circuit])


def jump(args):
    config = toolkit.configure({"engine": args.engine}, **settings(args.set))
    print(f"Recording {args.duration:g} simulated s with the target jumping every {args.every:g} s …", flush=True)
    result = toolkit.jumping_target_run(config, duration_s=args.duration, every_s=args.every, distance_mm=args.distance,
                                        max_bearing_deg=args.max_bearing, seed=args.jump_seed,
                                        export_dir=Path(args.export_dir) if args.export_dir else None)
    run = Path(result["path"])
    print(f"Exported {result['samples']} samples to {shown(run)}. Fit it with: scripts/toolkit.py compare --run {shown(run)}")
    circuits = [config.connectome_parameters.circuit] if config.neural_model == "connectome" else []
    save(output_stem("jump", args.out), [], {"command": "jump", "config": config.model_dump(), "duration_s": args.duration,
                                             "every_s": args.every, "distance_mm": args.distance,
                                             "max_bearing_deg": args.max_bearing, "jump_seed": args.jump_seed,
                                             "run": {**result, "path": str(shown(run))}}, circuits)


def compare(args):
    from digitalfly import compare as cmp
    model = cmp.model_recording(args.run, args.readout) if args.run else None
    fly, conversion = None, None
    if args.recording:
        if args.recording.endswith(".mat"):
            fly, conversion = cmp.rayshubskiy_recording(args.recording, args.readout or "DNa02", positive_yaw=args.positive_yaw,
                                                        exclude_stimulus=not args.include_stimulus)
            stim = conversion["stimulus"]
            print(f"Converted {conversion['source']}: {conversion['duration_s']:.0f} s, spikes left {conversion['spikes']['left']:,} "
                  f"({conversion['mean_rate_hz']['left']:.1f}/s), right {conversion['spikes']['right']:,} "
                  f"({conversion['mean_rate_hz']['right']:.1f}/s); the file's positive yaw taken as {args.positive_yaw}ward. "
                  f"Stimulus on {conversion['stimulus_fraction']:.1%} of the time; "
                  + (f"{stim['excluded_fraction']:.1%} of the samples left out of the fits (stimulus on, or within "
                     f"{stim['margin_s']:g} s after)." if stim["excluded"] else "stimulus epochs included (--include-stimulus).")
                  + "\n")
            if args.save_recording:
                cmp.save_recording(fly, args.save_recording)
        else:
            fly = cmp.load_recording(args.recording, args.readout or "DNa02")
    if not model and not fly:
        sys.exit("Give --recording (a fly recording: CSV, NPZ or a Rayshubskiy .mat) and/or --run (an exported run folder).")
    sources = {"fly": fly, "model": model}
    fits = {k: cmp.fit_turning(r, args.max_lag) if r else None for k, r in sources.items()}
    def filter_fit(recording):
        try:
            return cmp.fit_filter(recording, args.max_lag)
        except ValueError:  # too short for a cross-validated filter
            return None
    filters = {k: filter_fit(r) if r else None for k, r in sources.items()}
    rates = {k: cmp.rate_summary(r) if r else None for k, r in sources.items()}
    print("| Source | Readout | Best single lag | Gain at that lag | r² | Linear filter: held-out r² |")
    print("| --- | --- | --- | --- | --- | --- |")
    for label in sources:
        fit, filt = fits[label], filters[label]
        if fit:
            held_out = f"{filt['heldout_r2']:.3f}" if filt else "too short"
            print(f"| {label}: {fit['source']} | {fit['readout']} | {fit['lag_s'] * 1000:.0f} ms | "
                  f"{fit['gain']:.4g} {fit['gain_units']} | {fit['r2']:.3f} | {held_out} |")
    print("\n| Source | Units | Left: mean, median, 99th percentile | Right: mean, median, 99th percentile |\n| --- | --- | --- | --- |")
    for label, summary in rates.items():
        if summary:
            sides = [f"{s['mean']:.3g}, {s['median']:.3g}, {s['p99']:.3g}" if s else "n/a"
                     for s in (summary["left"], summary["right"])]
            print(f"| {label} | {summary['units']} | {sides[0]} | {sides[1]} |")
    result = {"fits": fits, "filters": filters, "rates": rates, "conversion": conversion}
    if args.run:
        neural = json.loads((Path(args.run) / "metadata.json").read_text())["neural"]
        result["run"] = {"path": args.run, "circuit": neural.get("circuit"), "circuit_sha256": neural.get("circuit_sha256")}
    if fly and model:
        result["comparison"] = cmp.compare(fly, model, args.max_lag)
        c = result["comparison"]
        print(f"\nSame sign: {c['same_sign']}. Model lag − fly lag: {c['lag_difference_s'] * 1000:+.0f} ms. {c['note']}")
    save(output_stem("compare", args.out), [], {"command": "compare", "rotation": "rightward positive, deg/s", **result})


def circuits(args):
    print("| Circuit | Where | Neurons | Connections | Cell types | Seeds | Readout |\n| --- | --- | --- | --- | --- | --- | --- |")
    for c in list_circuits():
        if "error" in c:
            print(f"| {c['name']} | unreadable: {c['error']} | | | | | |")
            continue
        print(f"| {c['name']} | {'committed' if c['committed'] else 'local'} | {c['neurons']:,} | {c['connections']:,} | "
              f"{c['cell_types']:,} | {', '.join(c['seeds'])} | {', '.join(c['readout_types']) or '—'} |")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    t = commands.add_parser("trials", help="Closed-loop trials over targets, seeds and varied settings")
    t.add_argument("--duration", type=float, default=10.0, help="Simulated seconds per trial (default 10)")
    t.add_argument("--bearings", help=f"Target bearings in degrees; positive = left (default {DEFAULTS['bearings']})")
    t.add_argument("--distances", help=f"Target distances in mm (default {DEFAULTS['distances']})")
    t.add_argument("--seeds", help=f"Seeds, e.g. 1-5 or 1,7,9 (default {DEFAULTS['seeds']})")
    t.add_argument("--vary", action="append", default=[], help="KEY=V1,V2: one grid axis (repeatable)")
    t.add_argument("--resume", action="store_true", help="Skip trials already saved without an error in --out's .jsonl")
    t.set_defaults(handler=trials)
    b = commands.add_parser("bias", help="Open-loop turn commands over sensor inputs, and the mirror test")
    b.add_argument("--levels", default=".25,.5,.75,1")
    b.add_argument("--differences", default="-.4,-.2,0,.2,.4", help="Right − left sensor values; write --differences=-.2,0,.2")
    b.set_defaults(handler=bias)
    a = commands.add_parser("ablation", help="Silence each cell type in turn and rank the change in turning")
    a.add_argument("--left", type=float, default=.5)
    a.add_argument("--right", type=float, default=.5)
    a.add_argument("--types", help="Comma-separated cell types to scan (default: all except the readout)")
    a.add_argument("--type", action="append", default=[], help="One cell type to scan; repeat it, and use it for names with commas")
    a.add_argument("--top", type=int, default=25)
    a.set_defaults(handler=ablation)
    for sub in (b, a):
        sub.add_argument("--ms", type=int, default=500, help="Milliseconds of clamped input before reading the turn")
        sub.add_argument("--average-ms", type=int, default=0, help="Average the turn over this final window (spiking)")
        sub.add_argument("--seed", type=int, default=0)
    p = commands.add_parser("paths", help="Strongest cell-type paths between two types")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--hops", type=int, default=4)
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(handler=paths)
    j = commands.add_parser("jump", help="Record and export a run whose target jumps to a random side (for compare)")
    j.add_argument("--duration", type=float, default=60.0, help="Simulated seconds, below the 300 s recording limit (default 60)")
    j.add_argument("--every", type=float, default=2.0, help="Seconds between jumps (default 2)")
    j.add_argument("--distance", type=float, default=10.0, help="Target distance after each jump, mm (default 10)")
    j.add_argument("--max-bearing", type=float, default=120.0, help="Largest jump from the heading, degrees (default 120)")
    j.add_argument("--jump-seed", type=int, default=0, help="Seed of the jumps; the model's seed is --set seed=N")
    j.add_argument("--export-dir", help="Folder for the exported run (default runs/)")
    j.set_defaults(handler=jump)
    c = commands.add_parser("circuits", help="List committed and local circuits")
    c.set_defaults(handler=circuits)
    m = commands.add_parser("compare", help="Fit turning to right − left readout activity in a recording and/or a run")
    m.add_argument("--recording", help="Fly recording: CSV/NPZ (columns in digitalfly/compare.py) or a Rayshubskiy et al. 2025 dual .mat")
    m.add_argument("--positive-yaw", choices=["right", "left"], default="right",
                   help="Which way the .mat file's positive yaw turns (default right, inferred; see the research guide)")
    m.add_argument("--include-stimulus", action="store_true",
                   help="Keep the .mat file's optogenetic stimulus epochs in the fits (default: leave them out)")
    m.add_argument("--save-recording", help="Also write the converted .mat recording as a CSV here")
    m.add_argument("--run", help="Exported DigitalFly run folder (runs/<id>)")
    m.add_argument("--readout", help="Readout cell type (default: the run's first readout, or DNa02)")
    m.add_argument("--max-lag", type=float, default=.5, help="Largest lag of turning behind the neurons, s")
    m.add_argument("--out", help="Output file stem (.json is written)")
    m.set_defaults(handler=compare)
    for sub in (t, j):
        sub.add_argument("--engine", choices=["toy", "flygym"], default="toy")
    for sub in (t, b, a, p, j):
        sub.add_argument("--set", action="append", default=[], help="KEY=VALUE setting (repeatable)")
    for sub in (t, a):
        sub.add_argument("--workers", type=int, default=1, help="Parallel processes (default 1)")
    for sub in (t, b, a, p):
        sub.add_argument("--out", help="Output file stem (.csv and .json are written)")
    j.add_argument("--out", help="Output file stem for the report (.json); the run itself goes to --export-dir")
    args = parser.parse_args()
    try:
        args.handler(args)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        sys.exit(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
