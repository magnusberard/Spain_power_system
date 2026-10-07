"""Publish a finished run to the results viewer (github.com/Leide0022/spain-model-runs).

Reads the run's CSVs in results/<run>/ (piece by piece: a month is ~600 MB, a year many GB) and
writes a small package into a local clone of spain-model-runs: runs/<id>/meta.json, data.js
(prices, generation mix, solve status, map geometry) and one file per month with the hourly map
data. Real data comes from that repo's reference/ folder, so no raw OMIE/ENTSO-E downloads are
needed. The big CSVs never leave this PC.

    python scripts/publish_run.py results/2024_by_month/2024-08 --name "August, baseline" --note "first August run"
    python scripts/publish_run.py results/my_run --name "..." --push      # also commit and push the package

The run is labelled from results/<run>/run_info.json, which run_market_chain.jl writes. For runs
made before that existed, give --ran-by and --commit; the package then says the info was filled
in by hand. Options: --id (folder name; default from the name and days), --runs-repo (default
../spain-model-runs next to this repo), --force (replace an existing package).

Package format version 1; the viewer reads it with viewer.js in spain-model-runs.
"""
import argparse
import base64
import datetime as dt
import getpass
import json
import re
import subprocess
import sys
from math import cos, radians
from pathlib import Path

import numpy as np
import pandas as pd

SCHEMA = 1
MODEL_REPO = Path(__file__).resolve().parents[1]
STAGES = ["DA", "ID2", "ID3", "CID", "BAL"]
CHUNK = 500_000
KX, KY = 111.32 * cos(radians(40.0)), 111.32       # map projection in km; the same as the viewer

# model (fuel, technology) -> OMIE's day-ahead technology groups
OMIE_CATS = ["Nuclear", "Coal", "CCGT", "Hydro", "Wind", "Solar", "CHP group", "Imports"]
OMIE_OF = {
    ("Nuclear", "Nuclear"): "Nuclear", ("Coal", "Coal"): "Coal",
    ("Gas", "Combined_cycle"): "CCGT", ("Gas", "Gas_turbine"): "CCGT", ("Oil", "Combined_cycle"): "CCGT",
    ("Hydro", "reservoir"): "Hydro", ("Hydro", "run_of_river"): "Hydro", ("Hydro", "pumped_storage"): "Hydro",
    ("Wind", "Onshore"): "Wind", ("Wind", "Offshore"): "Wind",
    ("Solar", "PV"): "Solar", ("Solar", "Solar Thermal"): "Solar",
    ("Gas", "CHP"): "CHP group", ("Biomass", "CHP_Waste"): "CHP group", ("Biomass", "Biomass"): "CHP group",
    ("Hydro", "mini_hydro"): "CHP group", ("CrossBorder", "Interconnector"): "Imports",
}
# model (fuel, technology) -> ENTSO-E's fuel types (CHP gas is gas, mini-hydro is hydro)
PHYS_CATS = ["Nuclear", "Coal", "Gas", "Hydro", "Wind", "Solar", "Bio & other", "Imports"]
PHYS_OF = {
    ("Nuclear", "Nuclear"): "Nuclear", ("Coal", "Coal"): "Coal",
    ("Gas", "Combined_cycle"): "Gas", ("Gas", "Gas_turbine"): "Gas", ("Gas", "CHP"): "Gas",
    ("Oil", "Combined_cycle"): "Bio & other",
    ("Hydro", "reservoir"): "Hydro", ("Hydro", "run_of_river"): "Hydro",
    ("Hydro", "pumped_storage"): "Hydro", ("Hydro", "mini_hydro"): "Hydro",
    ("Wind", "Onshore"): "Wind", ("Wind", "Offshore"): "Wind",
    ("Solar", "PV"): "Solar", ("Solar", "Solar Thermal"): "Solar",
    ("Biomass", "Biomass"): "Bio & other", ("Biomass", "CHP_Waste"): "Bio & other",
    ("CrossBorder", "Interconnector"): "Imports",
}
# plant map groups; the synthetic CHP/waste/mini-hydro blocks, load shedding and the slack are left out
PLANT_OF = {
    ("Nuclear", "Nuclear"): "Nuclear", ("Coal", "Coal"): "Coal",
    ("Gas", "Combined_cycle"): "Gas", ("Gas", "Gas_turbine"): "Gas", ("Oil", "Combined_cycle"): "Gas",
    ("Hydro", "reservoir"): "Hydro", ("Hydro", "run_of_river"): "Hydro", ("Hydro", "pumped_storage"): "Hydro",
    ("Wind", "Onshore"): "Wind", ("Wind", "Offshore"): "Wind",
    ("Solar", "PV"): "Solar", ("Solar", "Solar Thermal"): "Solar",
    ("Biomass", "Biomass"): "Biomass", ("CrossBorder", "Interconnector"): "Imports",
}
TECH_NAME = {"Combined_cycle": "combined cycle", "Gas_turbine": "gas turbine", "reservoir": "reservoir",
             "run_of_river": "run-of-river", "pumped_storage": "pumped storage", "Onshore": "onshore",
             "Offshore": "offshore", "PV": "PV", "Solar Thermal": "solar thermal", "Interconnector": "interconnector",
             "Nuclear": "nuclear", "Coal": "coal", "Biomass": "biomass"}


def proj(lon, lat):
    return round(float(lon) * KX, 1), round(-float(lat) * KY, 1)


def b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def r1(values):
    return [None if v is None or not np.isfinite(v) else round(float(v), 1) for v in values]


def git(repo, *args, check=False):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{p.stderr.strip()}")
    return p.stdout.strip()


# ---------------------------------------------------------------- reading the run
class Hours:
    """Maps (date, hour) of the run's study days to 0..H-1."""

    def __init__(self, days):
        self.days = list(days)
        self.day_i = {d: k for k, d in enumerate(self.days)}
        self.H = 24 * len(self.days)

    def of(self, frame):
        return frame["date"].map(self.day_i).to_numpy() * 24 + frame["hour"].to_numpy()


def read_run_info(rdir, args, hours, status):
    path = rdir / "run_info.json"
    if path.exists():
        info = json.loads(path.read_text(encoding="utf-8"))
        info["reconstructed"] = False
    else:
        print("  no run_info.json (run made before it existed): using --ran-by/--commit, marked as filled in by hand")
        info = dict(ran_by=args.ran_by or "", commit=args.commit or "", branch=args.branch or "",
                    commit_message="", uncommitted_files=[], reconstructed=True)
    info.setdefault("ac_hours_solved", int(status.sum()))
    info.setdefault("ac_hours_total", hours.H)
    return info


def stream_dispatch(path, unit_col, hours, unit_index, n_units):
    """Hourly MW per unit (clipped at 0 for output, signed for changes) from a dispatch CSV."""
    out = np.zeros((n_units, hours.H))
    signed = np.zeros((n_units, hours.H))
    seen = np.zeros(hours.H, dtype=bool)
    for ch in pd.read_csv(path, chunksize=CHUNK, usecols=["date", "hour", unit_col, "dispatch_mw"]):
        ch = ch[ch.date.isin(hours.day_i)]
        hi = hours.of(ch)
        seen[np.unique(hi)] = True
        ui = ch[unit_col].map(unit_index)
        ok = ui.notna().to_numpy()
        u, h, v = ui.to_numpy()[ok].astype(int), hi[ok], ch.dispatch_mw.to_numpy()[ok]
        np.add.at(signed, (u, h), v)
        np.add.at(out, (u, h), np.clip(v, 0, None))
    return out, signed, seen


def unit_table(rdir):
    """Units as the redispatch reports them (name, fuel, technology, bus, capacity)."""
    for ch in pd.read_csv(rdir / "gen_dispatch.csv", chunksize=20_000):
        first = ch[(ch.date == ch.date.iloc[0]) & (ch.hour == ch.hour.iloc[0])]
        return first[["unit_name", "fuel", "technology", "bus_i", "capacity_mw"]].reset_index(drop=True)


def bus_ids(rdir):
    """PowerModels bus number -> bus id, from the branch results."""
    bf = pd.read_csv(rdir / "branch_flows.csv", nrows=5000, usecols=["from_bus", "to_bus", "from_bus_id", "to_bus_id"])
    return dict(zip(bf.from_bus, bf.from_bus_id)) | dict(zip(bf.to_bus, bf.to_bus_id))


def corridors(rdir):
    """Grid lines and transformers, merged per substation pair (parallel circuits together)."""
    bus = pd.read_csv(MODEL_REPO / "Data/Bus_Data.csv", encoding="utf-8-sig").set_index("bus_id")
    lines = pd.read_csv(MODEL_REPO / "Data/lines.csv").set_index("line_id")
    trafos = pd.read_csv(MODEL_REPO / "Data/transformers_reactance.csv").set_index("transformer_id")
    first = pd.read_csv(rdir / "branch_flows.csv", nrows=5000)
    first = first[(first.date == first.date.iloc[0]) & (first.hour == first.hour.iloc[0])]
    corr, of, key_idx = [], {}, {}
    for b in first.itertuples(index=False):
        trafo = b.branch_name.startswith("TR_")
        a, z = sorted([b.from_bus_id, b.to_bus_id])
        key = (a, z, trafo)
        if key not in key_idx:
            key_idx[key] = len(corr)
            if trafo:
                kv = f"{int(trafos.loc[b.branch_name, 'voltage_bus0'])}/{int(trafos.loc[b.branch_name, 'voltage_bus1'])}"
                km = 0.0
            else:
                known = b.branch_name in lines.index
                kv = int(lines.loc[b.branch_name, "voltage"]) if known else None
                km = round(float(lines.loc[b.branch_name, "length"]), 1) if known else None
            corr.append(dict(names=[], kv=kv, km=km, a=proj(bus.loc[a, "x"], bus.loc[a, "y"]),
                             b=proj(bus.loc[z, "x"], bus.loc[z, "y"]), ab=[a, z], cls=b.asset_class,
                             t="trafo" if trafo else "line", lim=0.0))
        i = key_idx[key]
        corr[i]["names"].append(b.branch_name)
        corr[i]["lim"] += float(b.limit_mw)
        of[b.branch_name] = i
    for c in corr:
        c["lim"] = round(c["lim"])
    xs = [c["a"][0] for c in corr] + [c["b"][0] for c in corr]
    ys = [c["a"][1] for c in corr] + [c["b"][1] for c in corr]
    pad = 25
    frame = [round(min(xs) - pad, 1), round(min(ys) - pad, 1), round(max(xs) - min(xs) + 2 * pad, 1), round(max(ys) - min(ys) + 2 * pad, 1)]
    return corr, of, frame


def line_loading(rdir, hours, corr_of, n):
    """Highest loading (%) per corridor and hour; 255 = no result (failed AC hour)."""
    load = np.full((n, hours.H), -1.0)
    for ch in pd.read_csv(rdir / "branch_flows.csv", chunksize=CHUNK, usecols=["date", "hour", "branch_name", "loading_pct"]):
        ch = ch[ch.date.isin(hours.day_i)]
        np.maximum.at(load, (ch.branch_name.map(corr_of).to_numpy(), hours.of(ch)), ch.loading_pct.to_numpy())
    return np.where(load >= 0, np.clip(np.rint(load), 0, 254), 255).astype(np.uint8)


def real_reference(runs_repo, hours):
    ref = runs_repo / "reference"
    idx = pd.MultiIndex.from_tuples([(d, h) for d in hours.days for h in range(24)], names=["date", "hour"])
    real = pd.read_csv(ref / "real_hourly_2024.csv.gz").set_index(["date", "hour"]).reindex(idx)
    real_sites = pd.read_csv(ref / "real_sites_2024.csv.gz").set_index(["date", "hour"]).reindex(idx)
    sites = json.loads((ref / "sites.json").read_text(encoding="utf-8"))
    return real, real_sites, sites


# ---------------------------------------------------------------- building the package
def build(rdir, runs_repo, args):
    summ = pd.read_csv(rdir / "summary.csv")
    hours = Hours(sorted(summ.date.unique()))
    H = hours.H
    status = np.zeros(H, dtype=np.uint8)
    shed = np.full(H, np.nan)
    hi = hours.of(summ)
    status[hi] = (summ.status == "LOCALLY_SOLVED").to_numpy()
    shed[hi] = summ.load_shed_mw.to_numpy()
    info = read_run_info(rdir, args, hours, status)
    print(f"  {len(hours.days)} days ({hours.days[0]} to {hours.days[-1]}), {int(status.sum())}/{H} AC hours solved")

    prices = pd.read_csv(rdir / "market_prices.csv")
    price = {}
    for st in STAGES:
        p = np.full(H, np.nan)
        s = prices[(prices.stage == st) & prices.date.isin(hours.day_i)]
        p[hours.of(s)] = s.price_eur_mwh.to_numpy()
        price[st] = r1(p)

    units = unit_table(rdir)
    to_bus = bus_ids(rdir)
    units["bus_id"] = units.bus_i.map(to_bus)
    keys = list(zip(units.fuel, units.technology))
    uidx = {n: i for i, n in enumerate(units.unit_name)}
    U = len(units)

    print("  reading dispatch (day-ahead, balancing, redispatch) ...")
    mix, phys = {}, {}
    per_unit = {}
    for st, fname, col in (("DA", "da_dispatch.csv", "gen_id"), ("BAL", "bal_dispatch.csv", "gen_id"),
                           ("RD", "gen_dispatch.csv", "unit_name")):
        out, signed, seen = stream_dispatch(rdir / fname, col, hours, uidx, U)
        per_unit[st] = (out, signed, seen)
        for cats, table, dest in ((OMIE_CATS, OMIE_OF, mix), (PHYS_CATS, PHYS_OF, phys)):
            dest[st] = {}
            for c in cats:
                rows = [i for i, k in enumerate(keys) if table.get(k) == c]
                v = out[rows].sum(axis=0) if rows else np.zeros(H)
                dest[st][c] = r1(np.where(seen, v, np.nan))

    # balancing stage: what BAL moved relative to CID, summed up and down over the responding units
    # (wind, solar and the fixed cross-border injections left out), and the forecast change it had
    # to cover (CID -> BAL
    # load minus wind minus solar; positive = the system needs more energy). Compared with REE's
    # balancing energy and imbalance on the viewer's REE (e·sios) tab.
    balancing = None
    if (rdir / "cid_dispatch.csv").exists() and (rdir / "cid_profiles.csv").exists():
        print("  reading the continuous-intraday schedule for the balancing volume ...")
        _, cid_signed, cid_seen = stream_dispatch(rdir / "cid_dispatch.csv", "gen_id", hours, uidx, U)
        _, bal_s, bal_seen = per_unit["BAL"]
        # the plants that respond; wind and solar changing with their forecast are the cause, not balancing
        market = np.array([f not in ("CrossBorder", "Wind", "Solar") for f, _ in keys])
        d = (bal_s - cid_signed)[market]
        both = bal_seen & cid_seen
        up = np.where(both, np.clip(d, 0, None).sum(axis=0), np.nan)
        down = np.where(both, np.clip(-d, 0, None).sum(axis=0), np.nan)
        prof = {}
        for st in ("cid", "bal"):
            f = pd.read_csv(rdir / f"{st}_profiles.csv")
            f = f[f.date.isin(hours.day_i)]
            a = np.full((3, H), np.nan)
            a[:, hours.of(f)] = f[["load_mw", "wind_mw", "solar_mw"]].to_numpy().T
            prof[st] = a
        dl, dw, ds = prof["bal"] - prof["cid"]
        balancing = dict(up=r1(up), down=r1(down), need=r1(dl - dw - ds))

    # plant map groups: units of one fuel at one substation
    bus = pd.read_csv(MODEL_REPO / "Data/Bus_Data.csv", encoding="utf-8-sig").set_index("bus_id")
    units["group"] = [PLANT_OF.get(k) for k in keys]
    groups, group_rows = [], []
    for (b, g), u in units.dropna(subset=["group", "bus_id"]).groupby(["bus_id", "group"], sort=False):
        techs = u.technology.map(TECH_NAME).value_counts()
        x, y = proj(bus.loc[b, "x"], bus.loc[b, "y"])
        groups.append(dict(bus=b, f=g, x=x, y=y, cap=round(float(u.capacity_mw.sum()), 1), n=len(u),
                           tech=", ".join(k + (f" ×{v}" if v > 1 else "") for k, v in techs.items())))
        group_rows.append(u.index.to_numpy())
    rd_out, rd_signed, rd_seen = per_unit["RD"]
    _, bal_signed, _ = per_unit["BAL"]
    g_out = np.array([rd_out[r].sum(axis=0) for r in group_rows])
    # the model reports an interconnector's fixed hourly flow as its capacity, so use the highest
    # flow in the run instead (output can then never exceed it)
    for i, g in enumerate(groups):
        if g["f"] == "Imports":
            g["cap"] = round(max(g["cap"], float(g_out[i].max())), 1)
    cap = np.array([g["cap"] for g in groups])
    g_chg = np.array([rd_signed[r].sum(axis=0) - bal_signed[r].sum(axis=0) for r in group_rows])
    plant_out = np.where(rd_seen, np.clip(np.rint(250 * g_out / cap[:, None]), 0, 250), 255).astype(np.uint8)
    plant_chg = np.where(rd_seen, np.clip(np.rint(127 * g_chg / cap[:, None]), -127, 127), -128).astype(np.int8)

    # grid map
    print("  reading line flows ...")
    corr, corr_of, frame = corridors(rdir)
    grid_load = line_loading(rdir, hours, corr_of, len(corr))

    # real data and the ENTSO-E sites
    real, real_sites, ref_sites = real_reference(runs_repo, hours)
    site_rows = [[uidx[u] for u in s["model_units"] if u in uidx] for s in ref_sites["sites"]]
    site_model = np.array([rd_out[r].sum(axis=0) if r else np.zeros(H) for r in site_rows])
    NA = 65535
    site_model16 = np.where(rd_seen, np.clip(np.rint(site_model), 0, NA - 1), NA).astype("<u2")
    rs = real_sites.to_numpy().T
    site_real16 = np.where(np.isfinite(rs), np.clip(np.rint(np.nan_to_num(rs)), 0, NA - 1), NA).astype("<u2")

    data = dict(
        schema=SCHEMA, days=hours.days, price=price,
        real_price=r1(real["price"].to_numpy()),
        status=status.tolist(), shed=r1(shed),
        categories=OMIE_CATS, categories_phys=PHYS_CATS,
        real_mix={c: r1(real[f"omie_{c}"].to_numpy()) for c in OMIE_CATS},
        real_phys={c: r1(real[f"phys_{c}"].to_numpy()) for c in PHYS_CATS},
        mix=mix, mix_phys=phys,
        balancing=balancing,
        grid=dict(frame=frame, corridors=corr),
        plants=dict(groups=groups),
        sites=dict(sites=[{k: v for k, v in s.items() if k != "model_units"} | {"model_units": len(s["model_units"])}
                          for s in ref_sites["sites"]], coverage=ref_sites["coverage"]),
    )
    months = sorted({d[:7] for d in hours.days})
    month_parts = {}
    for m in months:
        hsel = np.array([k for k, d in enumerate(hours.days) if d.startswith(m)])
        hcols = (hsel[:, None] * 24 + np.arange(24)).ravel()
        # hour-major (hour by hour), so months can simply be joined in the viewer
        month_parts[m] = dict(h0=int(hcols[0]), hours=len(hcols),
                              grid_load=b64(grid_load[:, hcols].T), plant_out=b64(plant_out[:, hcols].T),
                              plant_chg=b64(plant_chg[:, hcols].T), site_model=b64(site_model16[:, hcols].T),
                              site_real=b64(site_real16[:, hcols].T))
    return hours, info, status, data, months, month_parts


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "run"


def write_manifest(runs_repo):
    metas = []
    for f in sorted((runs_repo / "runs").glob("*/meta.json")):
        metas.append(json.loads(f.read_text(encoding="utf-8")))
    metas.sort(key=lambda m: m.get("published", ""), reverse=True)
    (runs_repo / "runs" / "manifest.js").write_text(
        "// Written by scripts/publish_run.py in the model repo. Lists every published run.\n"
        "window.RUN_MANIFEST = " + json.dumps(metas, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    return len(metas)


def main():
    ap = argparse.ArgumentParser(description="Publish a finished run to the results viewer (spain-model-runs).")
    ap.add_argument("results", help="the run's results folder, e.g. results/2024_by_month/2024-08")
    ap.add_argument("--name", required=True, help='short name shown in the menu, e.g. "August, coal floor"')
    ap.add_argument("--note", default="", help="one or two sentences: what the run tests")
    ap.add_argument("--id", help="folder name in runs/ (default: from the days and the name)")
    ap.add_argument("--runs-repo", default=str(MODEL_REPO.parent / "spain-model-runs"))
    ap.add_argument("--ran-by", help="who ran it (only for runs without run_info.json)")
    ap.add_argument("--commit", help="code version it ran on (only for runs without run_info.json)")
    ap.add_argument("--branch", help="branch it ran on (only for runs without run_info.json)")
    ap.add_argument("--force", action="store_true", help="replace an existing package with the same id")
    ap.add_argument("--push", action="store_true", help="commit the package in spain-model-runs and push it")
    args = ap.parse_args()

    rdir = Path(args.results).resolve()
    runs_repo = Path(args.runs_repo).resolve()
    if not (rdir / "summary.csv").exists():
        sys.exit(f"{rdir} has no summary.csv; is it a finished run's results folder?")
    if not (runs_repo / "reference" / "sites.json").exists():
        sys.exit(f"{runs_repo} is not a clone of spain-model-runs (reference/ missing). "
                 "Clone it next to this repo or pass --runs-repo.")

    print(f"Publishing {rdir}")
    hours, info, status, data, months, parts = build(rdir, runs_repo, args)
    run_id = args.id or f"{hours.days[0]}_{slug(args.name)}"
    out = runs_repo / "runs" / run_id
    if out.exists() and not args.force:
        sys.exit(f"runs/{run_id} already exists; use --force to replace it or --id to choose another name")
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.js"):
        old.unlink()

    data["id"] = run_id
    data["months"] = months
    (out / "data.js").write_text("VIEWER.addRun(" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ");\n",
                                 encoding="utf-8")
    for m, part in parts.items():
        (out / f"{m}.js").write_text(f"VIEWER.addMonth({json.dumps(run_id)}, {json.dumps(m)}, "
                                     + json.dumps(part, separators=(",", ":")) + ");\n", encoding="utf-8")
    size_mb = sum(f.stat().st_size for f in out.glob("*.js")) / 1e6
    meta = dict(schema=SCHEMA, id=run_id, name=args.name, note=args.note,
                published=dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                published_by=git(MODEL_REPO, "config", "user.name") or getpass.getuser(),
                first_day=hours.days[0], last_day=hours.days[-1], n_days=len(hours.days),
                ac_solved=int(status.sum()), ac_total=hours.H, months=months, size_mb=round(size_mb, 1),
                info={k: info.get(k) for k in ("ran_by", "branch", "commit", "commit_message", "uncommitted_files",
                                               "started", "finished", "runtime_min", "power_flow", "linear_solver",
                                               "label", "reconstructed")})
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    n = write_manifest(runs_repo)
    print(f"  wrote runs/{run_id}/ ({size_mb:.1f} MB, {len(months)} month file(s)); the menu now lists {n} run(s)")

    if args.push:
        git(runs_repo, "add", f"runs/{run_id}", "runs/manifest.js", check=True)
        git(runs_repo, "commit", "-m", f"Publish run: {args.name} ({hours.days[0]} to {hours.days[-1]})", check=True)
        git(runs_repo, "pull", "--rebase", check=True)
        write_manifest(runs_repo)                    # another run may have arrived with the pull
        if git(runs_repo, "status", "--porcelain", "runs/manifest.js"):
            git(runs_repo, "add", "runs/manifest.js", check=True)
            git(runs_repo, "commit", "-m", "Update run list", check=True)
        git(runs_repo, "push", check=True)
        print("  pushed: teammates get it with git pull")
    else:
        print(f"  not pushed. To share it: cd {runs_repo} ; git add runs ; git commit -m \"Publish run\" ; git push")


if __name__ == "__main__":
    main()
