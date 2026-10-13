"""DigitalFly research toolkit from the command line: trials, sweeps, bias curves, ablation scans and paths.

    backend/.venv/bin/python scripts/toolkit.py trials --set neural_model=connectome --vary connectome_parameters.dynamics=rate,spiking
    backend/.venv/bin/python scripts/toolkit.py bias --set circuit=fafb783-steering
    backend/.venv/bin/python scripts/toolkit.py ablation --top 20 --workers 8
    backend/.venv/bin/python scripts/toolkit.py paths --source LC10a --target DNa02
    backend/.venv/bin/python scripts/toolkit.py circuits

--set and --vary take dotted RunConfig names (for bias, ablation and paths: ConnectomeParameters names,
with or without the "connectome_parameters." prefix). Values are read as JSON when they parse
(numbers, true/false, ["lists"]) and as text otherwise. Results are printed as Markdown and saved as
CSV and JSON under runs/toolkit/ (ignored by git) unless --out names a file. Every result describes
this simulation, not fly behavior.
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
from digitalfly import toolkit  # noqa: E402
from digitalfly.api.models import ConnectomeParameters  # noqa: E402
from digitalfly.neural.connectome import list_circuits, trace_paths  # noqa: E402

PREFIX = "connectome_parameters."


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


def save(name, rows, report, out):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    base = Path(out) if out else ROOT / "runs/toolkit" / f"{stamp}-{name}"
    base.parent.mkdir(parents=True, exist_ok=True)
    stem = base.with_suffix("") if base.suffix in {".csv", ".json"} else base
    stem.with_suffix(".json").write_text(json.dumps(report, indent=1, default=str))
    if rows:
        flat = [{k: v for k, v in r.items() if not isinstance(v, (list, dict))} for r in rows]
        fields = list(dict.fromkeys(k for r in flat for k in r))
        with stem.with_suffix(".csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(flat)
    shown = stem.relative_to(ROOT) if stem.is_relative_to(ROOT) else stem
    print(f"\nSaved {shown}.json" + (f" and {shown}.csv" if rows else ""))


def trials(args):
    base = toolkit.configure({"engine": args.engine}, **settings(args.set))
    varied = axes(args.vary)
    configs, keys = [], list(varied)
    for config in toolkit.grid(base, **varied) if varied else [base]:
        for bearing in numbers(args.bearings):
            for distance in numbers(args.distances):
                for seed in numbers(args.seeds, int):
                    configs.append(toolkit.configure(config, seed=seed, stimulus=toolkit.target(bearing, distance)))
    print(f"Running {len(configs)} trials of {args.duration:g} simulated s on {args.workers} worker(s) …", flush=True)
    rows = toolkit.run_trials(configs, workers=args.workers, duration_s=args.duration)
    group_keys = [k.split(".")[-1] for k in keys] or ["neural_model"]
    for row, config in zip(rows, configs):
        for key in keys:
            node = config.model_dump()
            for part in key.split("."):
                node = node[part]
            row[key.split(".")[-1]] = json.dumps(node) if isinstance(node, (list, dict)) else node
    groups = {}
    for row in rows:
        groups.setdefault(tuple(row[k] for k in group_keys), []).append(row)
    print("\n| " + " | ".join(group_keys) + " | Reached ≤2 mm | First turn toward (lateral targets) | Final distance (median) | Mean speed |")
    print("|" + " --- |" * (len(group_keys) + 4))
    for key, group in groups.items():
        lateral = [r for r in group if r["first_turn_toward"] is not None or abs(r["target_bearing_deg"]) % 180]
        toward = sum(r["first_turn_toward"] is True for r in lateral)
        print("| " + " | ".join(map(str, key)) + f" | {sum(r['reached'] for r in group)}/{len(group)} | {toward}/{len(lateral)} | "
              f"{np.median([r['final_distance_mm'] for r in group]):.1f} mm | {np.mean([r['mean_speed_mm_s'] for r in group]):.1f} mm/s |")
    save("trials", rows, {"command": "trials", "base": base.model_dump(), "vary": varied, "duration_s": args.duration,
                          "scope": "Simulated behavior; no biological validation.", "trials": rows}, args.out)


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
    save("bias", curve["rows"], {"command": "bias", "parameters": p.model_dump(), **curve}, args.out)


def ablation(args):
    p = parameters(args.set)
    types = [t for t in args.types.split(",") if t] if args.types else None
    scan = toolkit.ablation_scan(p, left=args.left, right=args.right, ms=args.ms, cell_types=types,
                                 workers=args.workers, average_ms=args.average_ms, seed=args.seed)
    print(f"Circuit {scan['circuit']}, {scan['dynamics']} dynamics, sensors {args.left:g}/{args.right:g}: "
          f"intact turn {scan['intact_turn']:+.4f} ({scan['types_scanned']} types silenced one at a time).\n")
    print("| Silenced cell type | Neurons (left/right) | Turn | Change |\n| --- | --- | --- | --- |")
    for row in scan["rows"][:args.top]:
        print(f"| {row['cell_type']} | {row['neurons']} ({row['left']}/{row['right']}) | {row['turn']:+.4f} | {row['change']:+.4f} |")
    print("\nPositive change: the type was pushing the fly to the left.")
    save("ablation", scan["rows"], {"command": "ablation", "parameters": p.model_dump(), **scan}, args.out)


def paths(args):
    result = trace_paths(parameters(args.set), args.source, args.target, args.hops, args.limit)
    print(f"Strongest paths from {args.source} to {args.target} in {result['circuit']} (≤{args.hops} steps):\n")
    print("| Path | Strength | Net sign |\n| --- | --- | --- |")
    for p in result["paths"]:
        print(f"| {' → '.join(p['cell_types'])} | {p['strength']:.4g} | {'+' if p['net_sign'] > 0 else '−'} |")
    print(f"\n{result['rule']}")


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
    t.add_argument("--engine", choices=["toy", "flygym"], default="toy")
    t.add_argument("--duration", type=float, default=10.0, help="Simulated seconds per trial (default 10)")
    t.add_argument("--bearings", default="0,45,-45,90,-90,180", help="Target bearings in degrees; positive = left")
    t.add_argument("--distances", default="12,30", help="Target distances in mm")
    t.add_argument("--seeds", default="1-5", help="Seeds, e.g. 1-5 or 1,7,9")
    t.add_argument("--vary", action="append", default=[], help="KEY=V1,V2: one grid axis (repeatable)")
    t.set_defaults(run=trials)
    b = commands.add_parser("bias", help="Open-loop turn commands over sensor inputs, and the mirror test")
    b.add_argument("--levels", default=".25,.5,.75,1")
    b.add_argument("--differences", default="-.4,-.2,0,.2,.4", help="Right − left sensor values; write --differences=-.2,0,.2")
    b.set_defaults(run=bias)
    a = commands.add_parser("ablation", help="Silence each cell type in turn and rank the change in turning")
    a.add_argument("--left", type=float, default=.5)
    a.add_argument("--right", type=float, default=.5)
    a.add_argument("--types", help="Comma-separated cell types to scan (default: all except the readout)")
    a.add_argument("--top", type=int, default=25)
    a.set_defaults(run=ablation)
    for sub in (b, a):
        sub.add_argument("--ms", type=int, default=500, help="Milliseconds of clamped input before reading the turn")
        sub.add_argument("--average-ms", type=int, default=0, help="Average the turn over this final window (spiking)")
        sub.add_argument("--seed", type=int, default=0)
    p = commands.add_parser("paths", help="Strongest cell-type paths between two types")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--hops", type=int, default=4)
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(run=paths)
    c = commands.add_parser("circuits", help="List committed and local circuits")
    c.set_defaults(run=circuits)
    for sub in (t, b, a, p):
        sub.add_argument("--set", action="append", default=[], help="KEY=VALUE setting (repeatable)")
    for sub in (t, a):
        sub.add_argument("--workers", type=int, default=1, help="Parallel processes (default 1)")
    for sub in (t, b, a):
        sub.add_argument("--out", help="Output file stem (.csv and .json are written)")
    args = parser.parse_args()
    try:
        args.run(args)
    except (ValueError, FileNotFoundError) as exc:
        sys.exit(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
