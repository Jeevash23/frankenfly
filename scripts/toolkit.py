"""DigitalFly research toolkit from the command line: trials, sweeps, bias curves, ablation scans and paths.

    backend/.venv/bin/python scripts/toolkit.py trials --set neural_model=connectome --vary connectome_parameters.dynamics=rate,spiking
    backend/.venv/bin/python scripts/toolkit.py bias --set circuit=fafb783-steering
    backend/.venv/bin/python scripts/toolkit.py ablation --top 20 --workers 8
    backend/.venv/bin/python scripts/toolkit.py paths --source LC10a --target DNa02
    backend/.venv/bin/python scripts/toolkit.py jump --set neural_model=connectome --set seed=3 --duration 60 --jump-seed 11
    backend/.venv/bin/python scripts/toolkit.py compare --recording fly.csv --run runs/<run folder>
    backend/.venv/bin/python scripts/toolkit.py compare --recording fly1.mat --recording fly2.mat --run runs/<a> --run runs/<b>
    backend/.venv/bin/python scripts/toolkit.py circuits
    backend/.venv/bin/python scripts/toolkit.py nwb runs/<run folder> [--out run.nwb]
    backend/.venv/bin/python scripts/toolkit.py manifest runs/<run folder>
    backend/.venv/bin/python scripts/toolkit.py methods runs/<a> [runs/<b> ...]

--set and --vary take dotted RunConfig names (for bias, ablation and paths: ConnectomeParameters names,
with or without the "connectome_parameters." prefix). Values are read as JSON when they parse
(numbers, true/false, ["lists"]) and as text otherwise; --vary splits its values at commas, unless they
are one JSON list of lists, objects or null (stimulus=[{"x":5,"y":5},{"x":5,"y":-5}]). Dotted names
also fill an unset group (connectome_parameters.readout_weights.DNa02=2). Results are printed as
Markdown and saved as JSON (plus CSV for tables) under runs/toolkit/ (ignored by git) unless --out
names a file (dots in its name are kept: --out gain-1.5 writes gain-1.5.json); every
report records its provenance (git commit, command line, circuits and their SHA-256, package
versions). `circuits` only prints the list. `trials` also appends each finished trial to a .jsonl
and the .csv while it runs; a trial that fails becomes a row with an error, and --resume skips the
trials already saved. `nwb` writes a saved run as NWB (needs backend/requirements-nwb.lock) and validates it;
`manifest` prints a run's RO-Crate provenance manifest; `methods` drafts a methods paragraph for one run, or for
several (a comparison). Every result describes this simulation, not fly behavior.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from pydantic import ValidationError

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
        if not raw.startswith(("[[", "[{", "[null")):
            result[key.strip()] = [value(v) for v in raw.split(",")]
            continue
        try:  # one JSON list whose items (lists, objects or null) are the values: commas inside them do not split
            result[key.strip()] = json.loads(raw)
        except ValueError as exc:
            sys.exit(f"--vary {key.strip()}: {raw!r} is not a JSON list ({exc}).")
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
    return toolkit.with_ending(base, "")  # drops a .csv, .json or .jsonl ending; other dots stay (gain-1.5)


def shown(path):
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


# Rows as CSV; trial rows appended to .jsonl and .csv as they finish (resumable). Both live in digitalfly.toolkit.
write_csv, TrialLog = toolkit.write_csv, toolkit.TrialLog


def save(stem, rows, report, circuits=()):
    report = {**report, "provenance": toolkit.provenance(circuits)}
    toolkit.with_ending(stem, ".json").write_text(json.dumps(report, indent=1, default=str))
    if rows:
        write_csv(toolkit.with_ending(stem, ".csv"), rows)
    print(f"\nSaved {shown(stem)}.json" + (f" and {shown(stem)}.csv" if rows else ""))


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
    clipped = [r["motor_clipped_fraction"] for r in rows if r.get("motor_clipped_fraction") is not None]
    if clipped:
        print(f"\nConnectome trials: the motor command left [0, 1] and was clipped in {sum(clipped) / len(clipped):.0%} "
              f"of control intervals on average (at most {max(clipped):.0%}; column motor_clipped_fraction).")
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
    if (args.value is None) != (args.mode == "silence"):
        sys.exit("--mode scale and --mode activate need --value; silencing takes none.")
    types = [t for t in args.types.split(",") if t] if args.types else []
    types += args.type  # repeatable, for names that contain commas
    value = args.value or 0.
    scan = toolkit.ablation_scan(p, left=args.left, right=args.right, ms=args.ms, cell_types=types or None,
                                 workers=args.workers, average_ms=args.average_ms, seed=args.seed, mode=args.mode,
                                 value=value, side=args.side)
    done = {"silence": "silenced", "scale": f"scaled ×{value:g}",
            "activate": f"activated at {value:g} Hz" if p.dynamics == "spiking" else f"clamped at rate {value:g}"}[args.mode]
    done += "" if args.side == "both" else f" on the {args.side}"
    print(f"Circuit {scan['circuit']}, {scan['dynamics']} dynamics, sensors {args.left:g}/{args.right:g}: "
          f"intact turn {scan['intact_turn']:+.4f} ({scan['types_scanned']} types {done} one at a time"
          + (f"; {len(scan['skipped'])} without {args.side} neurons skipped" if scan["skipped"] else "") + ").\n")
    heading = "Silenced cell type" if args.mode == "silence" and args.side == "both" else f"Cell type, {done}"
    print(f"| {heading} | Neurons (left/right) | Turn | Change |\n| --- | --- | --- | --- |")
    for row in scan["rows"][:args.top]:
        result = (f"{row['turn']:+.4f} | {row['change']:+.4f}" if row["error"] is None else f"failed: {row['error']} | —")
        print(f"| {row['cell_type']} | {row['neurons']} ({row['left']}/{row['right']}) | {result} |")
    print("\nPositive change: the type was pushing the fly to the left." if args.mode == "silence" and args.side == "both"
          else f"\n{scan['note']}")
    save(output_stem("ablation", args.out), scan["rows"], {"command": "ablation", "parameters": p.model_dump(), **scan},
         [p.circuit])
    if scan["errors"]:
        sys.exit(f"{scan['errors']} of {scan['types_scanned']} cell types failed (see the error column); the others are saved.")


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


def mean_sd(stats, fmt="{:.3f}", scale=1, unit="", with_range=False):
    if stats is None:
        return "n/a"
    text = f"{fmt.format(stats['mean'] * scale)} ± {fmt.format(stats['sd'] * scale)}{unit}"
    return text + (f" ({fmt.format(stats['min'] * scale)}–{fmt.format(stats['max'] * scale)}{unit})" if with_range else "")


def compare(args):
    from digitalfly import compare as cmp
    if args.save_recording and len(args.recording) > 1:
        sys.exit("--save-recording converts one recording; give a single --recording with it.")
    models = [cmp.model_recording(run, args.readout) for run in args.run]
    flies, conversions = [], []
    for path in args.recording:
        conversion = None
        if path.endswith(".mat"):
            fly, conversion = cmp.rayshubskiy_recording(path, args.readout or "DNa02", positive_yaw=args.positive_yaw,
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
            fly = cmp.load_recording(path, args.readout or "DNa02")
        flies.append(fly)
        conversions.append(conversion)
    if not models and not flies:
        sys.exit("Give --recording (a fly recording: CSV, NPZ or a Rayshubskiy .mat) and/or --run (an exported run folder).")
    # One fly or run keeps the plain label ("fly", "model"); several are numbered ("fly 1", "fly 2", ...).
    labels = {group: [group] if len(items) <= 1 else [f"{group} {k}" for k in range(1, len(items) + 1)]
              for group, items in (("fly", flies), ("model", models))}
    sources = {}
    for group, items in (("fly", flies), ("model", models)):
        sources.update(zip(labels[group], items or [None]))
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
    across = {group: cmp.summarize_fits([fits[k] for k in names], [filters[k] for k in names])
              for group, names in labels.items() if len(names) > 1}
    if across:
        print("\n| Across | Recordings | Best single lag: mean ± SD (range) | Gain: mean ± SD | r²: mean ± SD | "
              "Held-out r²: mean ± SD (recordings) |\n| --- | --- | --- | --- | --- | --- |")
        for group, s in across.items():
            gain = f"{mean_sd(s['gain'], '{:.4g}')} {s['gain_units']}" if s["gain"] else s["gain_units"]
            held_out = f"{mean_sd(s['heldout_r2'])} ({s['heldout_r2']['n']})" if s["heldout_r2"] else "too short"
            print(f"| {group} | {s['recordings']} | {mean_sd(s['lag_s'], '{:.0f}', 1000, ' ms', True)} | {gain} | "
                  f"{mean_sd(s['r2'])} | {held_out} |")
    print("\n| Source | Units | Left: mean, median, 99th percentile | Right: mean, median, 99th percentile |\n| --- | --- | --- | --- |")
    for label, summary in rates.items():
        if summary:
            sides = [f"{s['mean']:.3g}, {s['median']:.3g}, {s['p99']:.3g}" if s else "n/a"
                     for s in (summary["left"], summary["right"])]
            print(f"| {label} | {summary['units']} | {sides[0]} | {sides[1]} |")
    result = {"fits": fits, "filters": filters, "rates": rates}
    if len(flies) > 1:
        result["conversions"] = dict(zip(labels["fly"], conversions))
    else:
        result["conversion"] = conversions[0] if conversions else None
    runs = {}
    for label, run in zip(labels["model"], args.run):
        neural = json.loads((Path(run) / "metadata.json").read_text())["neural"]
        runs[label] = {"path": run, "circuit": neural.get("circuit"), "circuit_sha256": neural.get("circuit_sha256")}
    if len(runs) == 1:
        result["run"] = runs["model"]
    elif runs:
        result["runs"] = runs
    if across:
        result["across"] = across
    if len(flies) == 1 and len(models) == 1:
        result["comparison"] = cmp.compare(flies[0], models[0], args.max_lag)
        c = result["comparison"]
        print(f"\nSame sign: {c['same_sign']}. Model lag − fly lag: {c['lag_difference_s'] * 1000:+.0f} ms. {c['note']}")
    elif flies and models:
        result["comparison"] = cmp.compare_groups([fits[k] for k in labels["fly"]], [fits[k] for k in labels["model"]])
        c = result["comparison"]
        print(f"\nSame sign in every fit: {c['same_sign']}. Mean model lag − mean fly lag: "
              f"{c['lag_difference_s'] * 1000:+.0f} ms. {c['note']}")
    save(output_stem("compare", args.out), [], {"command": "compare", "rotation": "rightward positive, deg/s", **result})


def circuits(args):
    print("| Circuit | Where | Neurons | Connections | Cell types | Seeds | Readout |\n| --- | --- | --- | --- | --- | --- | --- |")
    for c in list_circuits():
        if "error" in c:
            print(f"| {c['name']} | unreadable: {c['error']} | | | | | |")
            continue
        print(f"| {c['name']} | {'committed' if c['committed'] else 'local'} | {c['neurons']:,} | {c['connections']:,} | "
              f"{c['cell_types']:,} | {', '.join(c['seeds'])} | {', '.join(c['readout_types']) or '—'} |")


def _run_folder(text) -> Path:
    path = Path(text)
    if not (path / "metadata.json").is_file():
        raise FileNotFoundError(f"{text} is not a saved run folder (it has no metadata.json).")
    return path


def nwb(args):
    from digitalfly import nwb as nwb_export
    run = _run_folder(args.run)
    path = nwb_export.export_run(run, Path(args.out) if args.out else None)
    problems = nwb_export.validate(path)
    print(f"Wrote {shown(path)} ({path.stat().st_size / 1e6:.2f} MB).")
    if problems:
        sys.exit("pynwb's validator reported:\n" + "\n".join(problems))
    print("pynwb's validator found no problems.")


def manifest(args):
    from digitalfly import provenance
    print(json.dumps(provenance.run_manifest(_run_folder(args.run)), indent=2))


def methods(args):
    from digitalfly import provenance
    runs = [_run_folder(r) for r in args.runs]
    if len(runs) == 1:
        print(provenance.run_methods(runs[0]))
        return
    manifests = [provenance.run_manifest(r, hash_files=False) for r in runs]
    conditions = {}
    for run in runs:
        meta = json.loads((run / "metadata.json").read_text())
        if (meta.get("trial") or {}).get("condition") is not None:
            conditions[meta["run_id"]] = str(meta["trial"]["condition"])
    print(provenance.comparison_paragraph(manifests, conditions or None))


# ---------------------------------------------------------------------------------------------------------------------
# Assumption sensitivity (`robustness`) and the readout table (`readouts`), from digitalfly.robustness:
#   scripts/toolkit.py readouts                                   # "What the circuits compute": DNa02 R − L at 0.6 s
#   scripts/toolkit.py robustness --set circuit=fafb783-steering  # bias conclusions over sign rule, threshold, dynamics
#   scripts/toolkit.py robustness --vary circuit=fafb783-dna02,fafb783-dna02-balanced --vary seed=1,2,3 --analyses bias,reach

def assumption_axes(pairs):
    """--vary for robustness: as for trials (a JSON list of objects or null is one axis: readout_weights=[null,{…}]);
    names are ConnectomeParameters fields with or without the prefix, or seed."""
    return {key.removeprefix(PREFIX): found if isinstance(found, list) else [found] for key, found in axes(pairs).items()}


def cell(value):
    return "—" if value is None else f"{value:+.3f}" if isinstance(value, float) else str(value)


def robustness(args):
    from digitalfly import robustness as rb
    base, grid = parameters(args.set), assumption_axes(args.vary) or rb.DEFAULT_AXES
    analyses = [a.strip() for a in args.analyses.split(",") if a.strip()]
    if set(analyses) - set(rb.ANALYSES) or not analyses:
        sys.exit(f"Choose --analyses from {', '.join(rb.ANALYSES)}.")
    if args.resume and not args.out:
        sys.exit("--resume needs --out naming the earlier output.")
    settings = {"tolerance": args.tolerance}
    if args.ms:
        settings.update(ms=args.ms, average_ms=args.average_ms)
    if "reach" in analyses:
        settings.update(reach_seeds=numbers(args.reach_seeds, int), reach_duration_s=args.reach_duration)
    variants = rb.variants(base, grid, seed=args.seed)
    stem = output_stem("robustness", args.out)
    log = TrialLog(stem, args.resume)
    hashes = [rb.variant_hash(v, analyses, settings) for v in variants]
    todo = [k for k, h in enumerate(hashes) if h not in log.saved]
    print(f"Evaluating {len(todo)} of {len(variants)} variants ({', '.join(analyses)}) on {args.workers} worker(s); "
          f"finished variants go to {shown(log.jsonl)} …", flush=True)

    def finished(index, row):
        log.add({**row, "variant": todo[index]})
        print(f"Variant {todo[index]} " + (f"failed: {row['error']}" if row["error"] else "done"), flush=True)
    new = dict(zip(todo, rb.run([variants[k] for k in todo], analyses, workers=args.workers, on_result=finished, **settings)))
    rows = [{**(new[k] if k in new else log.saved[h]), "variant": k} for k, h in enumerate(hashes)]
    names = list(grid)
    columns = []
    if "bias" in analyses:
        columns += [("equal_input_turn", "Equal input"), ("turn_target_right", "Target right (0.3 / 0.7)"),
                    ("turn_target_left", "Target left (0.7 / 0.3)"), ("mirror_asymmetry", "Mirror asymmetry")]
    if "readouts" in analyses:
        columns += [(f"turn_at_{b:g}", rb.target_label(b)) for b in rb.BEARINGS]
    if "reach" in analyses:
        columns += [("reached", "Reached"), ("first_turns_toward", "First turn toward")]
    print(f"\nCircuit {base.circuit} unless varied. Turn commands (positive = rightward); variant 0 is the baseline.\n")
    print("| # | " + " | ".join(names + [label for _, label in columns]) + " |")
    print("|" + " --- |" * (len(names) + len(columns) + 1))
    for row in rows:
        settings_cells = [str(row.get(n)) for n in names]
        if row["error"]:
            print(f"| {row['variant']} | " + " | ".join(settings_cells) + f" | failed: {row['error']} |")
            continue
        values = []
        for key, _ in columns:
            if key == "reached":
                values.append(f"{row['reached']}/{row['reach_trials']}")
            elif key == "first_turns_toward":
                values.append(f"{row['first_turns_toward']}/{row['lateral_trials']}")
            elif key == "mirror_asymmetry" and row.get(key) is not None:
                values.append(f"{row[key]:.3f}")
            else:
                values.append(cell(row.get(key)))
        print(f"| {row['variant']} | " + " | ".join(settings_cells + values) + " |")
    result = rb.report(rows, names, base=base.model_dump(), grid=grid, analyses=analyses, settings=settings)
    print("\n| Conclusion | Baseline | Same in | Differs in |\n| --- | --- | --- | --- |")
    for item in result["survival"]:
        differs = ", ".join(f"#{k}" for k in item["differs_in"]) or "—"
        if item["differs_only_with"]:
            differs += " (exactly the variants with " + ", ".join(f"{a}={v}" for a, v in item["differs_only_with"].items()) + ")"
        print(f"| {item['description']} | {item['baseline']} | {item['holds']}/{item['variants']} | {differs} |")
    print(f"\nA turn within ±{args.tolerance:g} counts as none. {rb.SCOPE}")
    circuits = list(dict.fromkeys(v["parameters"].circuit for v in variants))
    save(stem, rows, result, circuits)
    if result["errors"]:
        sys.exit(f"{result['errors']} of {len(rows)} variants failed (see the error column); they are left out of the "
                 "comparison. Rerun with --resume and the same --out to retry only those.")


def readouts(args):
    from digitalfly import robustness as rb
    p = parameters(args.set)
    table = rb.readout_table(p, numbers(args.bearings), args.distance, ms=args.ms, average_ms=args.average_ms,
                             seed=args.seed, tolerance=args.tolerance)
    types = table["readout_types"]
    print(f"Circuit {p.circuit}, {p.dynamics} dynamics. Open loop: the fly held at the origin, the target held still "
          f"{args.distance:g} mm away, geometric sensor; activity after {args.ms} ms"
          + (f" (averaged over the last {args.average_ms} ms)" if args.average_ms else "") + ". Positive = rightward.\n")
    print("| Target | Sensor left / right | " + " | ".join(f"{t} R − L" for t in types) + " | Turn command | Turn command means |")
    print("|" + " --- |" * (len(types) + 4))
    for row in table["rows"]:
        means = row["direction"].capitalize() + {True: ", toward", False: ", away", None: ""}[row["toward"]]
        print(f"| {row['target']} | {row['sensor_left']:.3f} / {row['sensor_right']:.3f} | "
              + " | ".join(f"{row['right_minus_left'][t]:+.3f}" for t in types) + f" | {row['turn']:+.3f} | {means} |")
    rows = [{**{k: v for k, v in r.items() if k != "right_minus_left"},
             **{f"{t} right_minus_left": r["right_minus_left"][t] for t in types}} for r in table["rows"]]
    save(output_stem("readouts", args.out), rows, {"command": "readouts", "parameters": p.model_dump(), **table}, [p.circuit])


def add_assumption_commands(commands):
    r = commands.add_parser("robustness", help="Rerun bias, readout and reach analyses across modelling assumptions")
    r.add_argument("--vary", action="append", default=[],
                   help="KEY=V1,V2: one assumption axis (repeatable); default: other_transmitters × synapse_threshold × dynamics")
    r.add_argument("--analyses", default="bias", help="Comma-separated: bias, readouts, reach (default bias)")
    r.add_argument("--tolerance", type=float, default=.01, help="Turn commands within ±this count as no turn")
    r.add_argument("--ms", type=int, default=0, help="Clamp length for every open-loop analysis (default: as published)")
    r.add_argument("--average-ms", type=int, default=0, help="With --ms: average over this final window")
    r.add_argument("--seed", type=int, default=0, help="Seed of the open-loop analyses unless seed is an axis")
    r.add_argument("--reach-seeds", default="1-3", help="Seeds of the reach trials (toy body, ±45° and ±90° at 12 mm)")
    r.add_argument("--reach-duration", type=float, default=5.0, help="Simulated seconds per reach trial (default 5)")
    r.add_argument("--workers", type=int, default=1, help="Parallel processes, one variant each (default 1)")
    r.add_argument("--resume", action="store_true", help="Skip variants already saved without an error in --out's .jsonl")
    r.set_defaults(handler=robustness)
    o = commands.add_parser("readouts", help="Readout R − L and turn command for a target held at fixed bearings")
    o.add_argument("--bearings", default="45,90,0,-45,-90", help="Target bearings, degrees; positive = left")
    o.add_argument("--distance", type=float, default=12.0, help="Target distance, mm (default 12)")
    o.add_argument("--ms", type=int, default=600, help="Milliseconds of held input before reading (default 600)")
    o.add_argument("--average-ms", type=int, default=0, help="Average over this final window (spiking)")
    o.add_argument("--seed", type=int, default=0)
    o.add_argument("--tolerance", type=float, default=.01, help="Turn commands within ±this mean no turn")
    o.set_defaults(handler=readouts)
    for sub in (r, o):
        sub.add_argument("--set", action="append", default=[], help="KEY=VALUE ConnectomeParameters setting (repeatable)")
        sub.add_argument("--out", help="Output file stem (.csv and .json are written)")
# ---------------------------------------------------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    t = commands.add_parser("trials", help="Closed-loop trials over targets, seeds and varied settings")
    t.add_argument("--duration", type=float, default=10.0,
                   help="Simulated seconds per trial (default 10; trials keep no recording, so any length works)")
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
    a = commands.add_parser("ablation", help="Silence (or scale, or activate) each cell type in turn and rank the change in turning")
    a.add_argument("--left", type=float, default=.5)
    a.add_argument("--right", type=float, default=.5)
    a.add_argument("--types", help="Comma-separated cell types to scan (default: all except the readout)")
    a.add_argument("--type", action="append", default=[], help="One cell type to scan; repeat it, and use it for names with commas")
    a.add_argument("--mode", choices=["silence", "scale", "activate"], default="silence",
                   help="silence (default); scale: output × --value (0-2); activate: --value Hz (spiking) or clamped rate 0-1 (rate)")
    a.add_argument("--value", type=float, help="The scale factor or activation for --mode scale or activate")
    a.add_argument("--side", choices=["both", "left", "right"], default="both",
                   help="Manipulate both sides (default) or one; types without neurons on that side are skipped")
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
    j.add_argument("--duration", type=float, default=60.0,
                   help="Simulated seconds, at most 299.99: the exported run is recorded (default 60)")
    j.add_argument("--every", type=float, default=2.0, help="Seconds between jumps (default 2)")
    j.add_argument("--distance", type=float, default=10.0, help="Target distance after each jump, mm (default 10)")
    j.add_argument("--max-bearing", type=float, default=120.0, help="Largest jump from the heading, degrees (default 120)")
    j.add_argument("--jump-seed", type=int, default=0, help="Seed of the jumps; the model's seed is --set seed=N")
    j.add_argument("--export-dir", help="Folder for the exported run (default runs/)")
    j.set_defaults(handler=jump)
    c = commands.add_parser("circuits", help="List committed and local circuits")
    c.set_defaults(handler=circuits)
    w = commands.add_parser("nwb", help="Write a saved run as NWB and check it with pynwb's validator")
    w.add_argument("run", help="Saved run folder (runs/<id>)")
    w.add_argument("--out", help="NWB file to write (default: <run folder>/<run key>.nwb)")
    w.set_defaults(handler=nwb)
    f = commands.add_parser("manifest", help="Print a saved run's RO-Crate provenance manifest")
    f.add_argument("run", help="Saved run folder (runs/<id>)")
    f.set_defaults(handler=manifest)
    d = commands.add_parser("methods", help="Draft a methods paragraph for a run, or for several runs (a comparison)")
    d.add_argument("runs", nargs="+", help="Saved run folders (runs/<id>)")
    d.set_defaults(handler=methods)
    m = commands.add_parser("compare", help="Fit turning to right − left readout activity in recordings and/or runs")
    m.add_argument("--recording", action="append", default=[],
                   help="Fly recording: CSV/NPZ (columns in digitalfly/compare.py) or a Rayshubskiy et al. 2025 dual .mat; "
                        "repeat it for several flies (adds their mean and spread)")
    m.add_argument("--positive-yaw", choices=["right", "left"], default="right",
                   help="Which way the .mat file's positive yaw turns (default right, inferred; see the research guide)")
    m.add_argument("--include-stimulus", action="store_true",
                   help="Keep the .mat file's optogenetic stimulus epochs in the fits (default: leave them out)")
    m.add_argument("--save-recording", help="Also write the converted .mat recording as a CSV here")
    m.add_argument("--run", action="append", default=[], help="Exported DigitalFly run folder (runs/<id>); repeatable")
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
    add_assumption_commands(commands)
    args = parser.parse_args()
    try:
        args.handler(args)
    except ValidationError as exc:  # a setting out of range, in one line per problem
        sys.exit("; ".join(f"Invalid setting {'.'.join(map(str, e['loc']))}: " * bool(e["loc"])
                           + e["msg"].removeprefix("Value error, ") for e in exc.errors()))
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        sys.exit(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
