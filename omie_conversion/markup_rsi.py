"""L(h) and RSI(h) for every hour of 2024 from OMIE's day-ahead bid curves.

L(h)   = MW-weighted Lerner index (bid - cost)/bid of gas (CCGT) and coal bid steps
         priced within +-WINDOW of the Spanish day-ahead price; cost = the model's own
         daily cost (fuel_prices.jl, exported to daily_costs.csv).
RSI(h) = (all offered sell capacity - largest firm's offered capacity) / matched demand.
         Offered capacity = sum of a unit's sell bid steps (MIBEL: Spain + Portugal);
         firm shares from OMIE's unit list (owner, % ownership), June 2024.
         Imports from France are not in the bid curves (market coupling): not counted.

    python markup_rsi.py <OMIE_data dir> <units csv> <daily_costs.csv> <out hourly csv>
"""
import csv, io, sys, zipfile, glob, os, collections

omie, units_csv, costs_csv, out_csv = sys.argv[1:5]
YEAR = sys.argv[5] if len(sys.argv) > 5 else "2024"
WINDOW = 0.20

# ── owners ──────────────────────────────────────────────────────────────────────
GROUPS = [("IBERDROLA", "Iberdrola"), ("ENDESA", "Endesa"), ("ENEL", "Endesa"),
          ("NATURGY", "Naturgy"), ("GAS NATURAL", "Naturgy"), ("EDP", "EDP"),
          ("REPSOL", "Repsol"), ("ACCIONA", "Acciona"), ("TOTAL", "TotalEnergies"),
          ("CEPSA", "Cepsa"), ("MOEVE", "Cepsa"), ("ENGIE", "Engie"), ("AXPO", "Axpo"),
          ("GALP", "Galp"), ("RWE", "RWE"), ("STATKRAFT", "Statkraft")]


def firm_of(agent):
    a = agent.upper()
    for key, name in GROUPS:
        if key in a:
            return name
    return agent.strip()


owners = collections.defaultdict(list)   # code -> [(firm, share)]
tech = {}
for r in csv.DictReader(open(units_csv, encoding="utf-8")):
    pct = r["ownership_pct"].replace(".", "").replace(",", ".").strip()
    share = float(pct) / 100 if pct else 1.0
    owners[r["code"]].append((firm_of(r["agent"]), share))
    tech[r["code"]] = r["technology"]
for c, lst in owners.items():                        # normalise shares to 1
    s = sum(x for _, x in lst) or 1.0
    owners[c] = [(f, x / s) for f, x in lst]

GAS = {c for c, t in tech.items() if t.startswith("Ciclo Combinado")}
COAL = {c for c, t in tech.items() if t.startswith("Hulla") or t.startswith("Carb")}
# CCGT efficiency by ENTSO-E category (Data/gas_unit_efficiency.csv, matched by plant
# name); unlisted CCGTs 0.56 as in the model.
ETA = {c: 0.58 for c in ["ACE4", "PGR5", "BES5", "CTGN1", "CTGN2", "CTGN3", "CTN4", "CTNU",
                         "COL4", "ECT2", "ECT3", "ESC6", "ESCCC1", "ESCCC2", "ESCCC3", "MALA1",
                         "PVENT1", "PVENT2", "SBO3", "SAGU1", "SAGU2", "SAGU3", "SRI4R"]}
ETA.update({"SRI5": 0.60, "ALG3": 0.60})

cost = {r["date"]: r for r in csv.DictReader(open(costs_csv))}


def unit_cost(code, date):
    r = cost[date]
    if code in COAL:
        return float(r["coal"] or "nan")   # no coal price for that year: NaN
    e = ETA.get(code, 0.56)
    return float(r["gas_%03d" % round(e * 100)])


def num(s):
    return float(s.replace(".", "").replace(",", "."))


# ── prices ──────────────────────────────────────────────────────────────────────
price = {}
for f in glob.glob(os.path.join(omie, "marginalpdbc", f"marginalpdbc_{YEAR}*.*")):
    for line in open(f, encoding="latin-1"):
        p = line.strip().split(";")
        if len(p) >= 6 and p[0] == YEAR:
            price[(f"{p[0]}-{p[1]}-{p[2]}", int(p[3]))] = float(p[5])

# ── bid curves, day by day ──────────────────────────────────────────────────────
rows = []
for z in sorted(glob.glob(os.path.join(omie, "curva_pbc_uof", f"curva_pbc_uof_{YEAR}*.zip"))):
    zf = zipfile.ZipFile(z)
    for name in sorted(zf.namelist()):
        d = name.split("_")[-1].split(".")[0]
        date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        cap = collections.defaultdict(lambda: collections.defaultdict(float))  # hour -> unit -> offered MW
        dem = collections.defaultdict(float)          # hour -> matched buy MW
        steps = collections.defaultdict(list)         # hour -> [(unit, MW, price)] gas/coal sell steps
        for line in io.TextIOWrapper(zf.open(name), encoding="latin-1"):
            f = line.split(";")
            if len(f) < 8 or not f[0].isdigit():
                continue
            h, unit, typ, st = int(f[0]), f[3], f[4], f[7]
            q = num(f[5])
            if typ == "V" and st == "O":
                cap[h][unit] += q
                if unit in GAS or unit in COAL:
                    steps[h].append((unit, q, num(f[6])))
            elif typ == "C" and st == "C":
                dem[h] += q
        hours = sorted(dem)
        for h in hours:
            P = price.get((date, h))
            if P is None:
                continue
            firm_cap = collections.defaultdict(float)
            total = 0.0
            for u, q in cap[h].items():
                total += q
                for fm, sh in owners.get(u, [(u, 1.0)]):
                    firm_cap[fm] += q * sh
            big_firm, big = max(firm_cap.items(), key=lambda kv: kv[1])
            D = dem[h]
            near = [(u, q, p) for u, q, p in steps[h]
                    if P > 0 and (1 - WINDOW) * P <= p <= (1 + WINDOW) * P and q > 0]
            mw = sum(q for _, q, _ in near)
            if mw > 0:
                Ls = [((p - unit_cost(u, date)) / p, q) for u, q, p in near]
                L_w = sum(l * q for l, q in Ls) / mw
                L_m = sum(l for l, _ in Ls) / len(Ls)
                n_units = len({u for u, _, _ in near})
            else:
                L_w = L_m = None
                n_units = 0
            gas_cap = sum(q for u, q in cap[h].items() if u in GAS)
            sep = {}
            for tag, grp in (("gas", GAS), ("coal", COAL)):
                nr = [(u, q, p) for u, q, p in near if u in grp]
                m = sum(q for _, q, _ in nr)
                sep[f"L_{tag}"] = round(sum((p - unit_cost(u, date)) / p * q for u, q, p in nr) / m, 4) if m > 0 else None
                sep[f"near_mw_{tag}"] = round(m, 1)
                sep[f"near_units_{tag}"] = len({u for u, _, _ in nr})
            rows.append(dict(date=date, hour=h, price=P, demand_mw=round(D, 1),
                             offered_mw=round(total, 1), largest_firm=big_firm,
                             largest_mw=round(big, 1), rsi=round((total - big) / D, 4) if D else None,
                             margin=round((total - D) / D, 4) if D else None,
                             gas_offered_mw=round(gas_cap, 1),
                             near_mw=round(mw, 1), near_units=n_units,
                             L_weighted=None if L_w is None else round(L_w, 4),
                             L_mean=None if L_m is None else round(L_m, 4), **sep))
        print(date, len(hours), "hours", flush=True) if date.endswith("-01") else None

with open(out_csv, "w", newline="") as fo:
    w = csv.DictWriter(fo, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print("wrote", out_csv, len(rows), "hours;", sum(r["L_weighted"] is not None for r in rows), "with gas/coal near the price")
