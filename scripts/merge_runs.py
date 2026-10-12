"""Join several finished runs of consecutive day ranges (e.g. the week folders from
solstorm_start_weeks.sh) into one results folder, as if it had been one run, so
publish_run.py can publish it as one run.

    python scripts/merge_runs.py <out> <parent folder of the parts>
    python scripts/merge_runs.py <out> <part> <part> ...

Every CSV is concatenated in day order with one header (the files are per hour,
so nothing is summed); run.log files are concatenated with a line per part;
ipopt_logs/ folders are combined. run_info.json is combined: days, first/last
day, AC hours solved/total (summed), started (earliest), finished (latest),
runtime_min = wall time from the first start to the last finish, cpu_min = the
parts' runtimes added up, merged_from = the part folders. The parts must agree
on commit, branch, res_input, linear solver and config, or the merge stops
(--force to merge anyway). Gaps and overlapping days stop it too.
"""
import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

SAME = ("commit", "branch", "res_input", "linear_solver", "power_flow", "crossborder_split", "label")
FMT = "%Y-%m-%d %H:%M:%S"


def parts_from(args):
    paths = [Path(p) for p in args.parts]
    if len(paths) == 1 and not (paths[0] / "summary.csv").exists():
        paths = sorted(p for p in paths[0].iterdir() if p.is_dir())
    done = [p for p in paths if (p / "summary.csv").exists() and (p / "run_info.json").exists()]
    unfinished = [p.name for p in paths if p not in done]
    if unfinished:
        sys.exit(f"{len(unfinished)} part(s) not finished (no summary.csv/run_info.json): {', '.join(unfinished)}")
    if not done:
        sys.exit("no finished parts found")
    infos = {p: json.loads((p / "run_info.json").read_text(encoding="utf-8")) for p in done}
    return sorted(done, key=lambda p: infos[p]["first_day"]), infos


def check(parts, infos, force):
    problems = []
    first = infos[parts[0]]
    for p in parts[1:]:
        for k in SAME:
            if infos[p].get(k) != first.get(k):
                problems.append(f"{p.name}: {k} = {infos[p].get(k)!r}, {parts[0].name} has {first.get(k)!r}")
        if (p / "config_used.toml").read_bytes() != (parts[0] / "config_used.toml").read_bytes():
            problems.append(f"{p.name}: config_used.toml differs from {parts[0].name}")
    days = [d for p in parts for d in infos[p]["days"]]
    if len(days) != len(set(days)):
        problems.append("overlapping days between parts")
    expect = dt.date.fromisoformat(days[0])
    for d in sorted(set(days)):
        if dt.date.fromisoformat(d) != expect:
            problems.append(f"gap: {expect} .. {dt.date.fromisoformat(d) - dt.timedelta(days=1)} missing")
        expect = dt.date.fromisoformat(d) + dt.timedelta(days=1)
    for msg in problems:
        print("  problem:", msg)
    if problems and not force:
        sys.exit("parts do not fit together (use --force to merge anyway)")
    return days


def merge_csv(name, parts, out):
    header = None
    with open(out / name, "wb") as dst:
        for p in parts:
            src_path = p / name
            if not src_path.exists():
                print(f"  {name}: missing in {p.name}")
                continue
            with open(src_path, "rb") as src:
                h = src.readline()
                if header is None:
                    header = h
                    dst.write(h)
                elif h != header:
                    sys.exit(f"{name}: header in {p.name} differs from the first part")
                shutil.copyfileobj(src, dst, 16 * 1024 * 1024)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", help="new results folder for the joined run (must not exist)")
    ap.add_argument("parts", nargs="+", help="the part folders, or one parent folder holding them")
    ap.add_argument("--force", action="store_true", help="merge even if the parts disagree or leave gaps")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists():
        sys.exit(f"{out} already exists")
    parts, infos = parts_from(args)
    print(f"Joining {len(parts)} parts: {parts[0].name} .. {parts[-1].name}")
    days = check(parts, infos, args.force)
    out.mkdir(parents=True)

    csvs = sorted({f.name for p in parts for f in p.glob("*.csv")})
    for name in csvs:
        merge_csv(name, parts, out)
    print(f"  {len(csvs)} CSV files joined")

    with open(out / "run.log", "wb") as dst:
        for p in parts:
            dst.write(f"\n===== part {p.name} =====\n".encode())
            if (p / "run.log").exists():
                dst.write((p / "run.log").read_bytes())
    for p in parts:
        if (p / "ipopt_logs").is_dir():
            shutil.copytree(p / "ipopt_logs", out / "ipopt_logs", dirs_exist_ok=True)
    for extra in ("config_used.toml", "run_info_diff.patch"):
        if (parts[0] / extra).exists():
            shutil.copy2(parts[0] / extra, out / extra)

    info = dict(infos[parts[0]])
    started = min(dt.datetime.strptime(infos[p]["started"], FMT) for p in parts)
    finished = max(dt.datetime.strptime(infos[p]["finished"], FMT) for p in parts)
    info.update(
        days=days, first_day=days[0], last_day=days[-1],
        ac_hours_solved=sum(int(infos[p].get("ac_hours_solved", 0)) for p in parts),
        ac_hours_total=sum(int(infos[p].get("ac_hours_total", 0)) for p in parts),
        started=started.strftime(FMT), finished=finished.strftime(FMT),
        runtime_min=round((finished - started).total_seconds() / 60, 1),
        cpu_min=round(sum(float(infos[p].get("runtime_min", 0)) for p in parts), 1),
        uncommitted_files=sorted({f for p in parts for f in infos[p].get("uncommitted_files", [])}),
        host=", ".join(sorted({str(infos[p].get("host", "")) for p in parts})),
        merged_from=[p.name for p in parts], n_parts=len(parts),
    )
    (out / "run_info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  {len(days)} days ({days[0]} .. {days[-1]}), AC hours {info['ac_hours_solved']}/{info['ac_hours_total']}, "
          f"wall {info['runtime_min']} min, cpu {info['cpu_min']} min")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
