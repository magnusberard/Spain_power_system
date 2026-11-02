"""Step 7 (a): every conventional generation position in REE's access-capacity list against the model's units.

Data rule of 2 Nov 2026 (vault decisions, "fixed by whole data class"): the class is every position REE lists as
existing conventional generation (EvCo_Exist) in "Capacidad de acceso ocupada por posición de conexión" (REE, 1 Jul
2024, Generacion_por_posicion_01jul24.pdf), whatever its fuel or size, checked whichever way a correction moves the
results. The earlier check (31 Oct) covered only the 30 model thermal units >= 100 MW it could match; this one starts
from REE's side, so every REE position is accounted for.

For each REE position (substation, kV, position code, MW): model units whose name shares a site word with the
substation or the position code, sized within ±15 % of the position (or of the substation's EvCo total, for plants
REE lists as one position per site), and not wind/solar. Status per position:
  same voltage   matched, model bus at REE's voltage (or moved there by data/unit_bus_override.csv)
  other voltage  matched, model bus at another voltage: a correction candidate (model bus at the site with REE's kV?)
  no match       nothing in the model matches by name and size: listed for a check by hand, not guessed

Renewable positions (EvRE_Exist) and the generation REE lists only as totals per substation ("Posición/es RdD")
are a separate part of the class: they need substation coordinates to match and are reported as not checked.

    python redispatch_realism/sweep_unit_connections.py <Generacion_por_posicion_01jul24.pdf>

Writes redispatch_realism/data/sweep_a_unit_connections.csv.
"""
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd
import pymupdf

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STOP = {"POWER", "STATION", "CENTRAL", "TERMICA", "PLANT", "NUCLEAR", "DE", "LA", "EL", "DEL", "LOS", "LAS", "Y", "GROUP",
        "UNIT", "CICLO", "COMBINADO", "PHASE", "GRUPO", "COMPLEJO", "HIDRAULICA", "CT", "CC", "SAN", "SANTA", "NUEVA", "NUEVO",
        "PUERTO", "TERMINAL", "TRANSFORMACION", "SUBESTACION", "CAMPO", "VALLE", "SIERRA", "ALTO", "BAJO", "RIO", "PUENTE"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9 ]", " ", s)


def toks(s):
    return {t for t in norm(s).split() if len(t) > 2 and t not in STOP and not t.isdigit()}


def ree_positions(pdf):
    L = [l.strip() for pg in pymupdf.open(pdf) for l in pg.get_text().splitlines()]
    sub = re.compile(r"^(.+?) (\d{2,3})$")
    rows = []
    for i in range(len(L) - 4):
        m = sub.match(L[i])
        if m and L[i + 2] == "EvCo_Exist":
            code, mw = L[i + 3], L[i + 4].replace(".", "").replace(",", ".")
            try:
                rows.append(dict(sub=m.group(1), kv=int(m.group(2)), region=L[i + 1], code=code, mw=float(mw)))
            except ValueError:
                pass
    return pd.DataFrame(rows).drop_duplicates()


def main():
    pdf = sys.argv[1]
    ree = ree_positions(pdf)
    ree["site_mw"] = ree.groupby(["sub", "kv"]).mw.transform("sum")
    g = pd.read_csv(REPO / "Data/generations.csv")
    B = pd.read_csv(REPO / "Data/Bus_Data.csv", encoding="utf-8-sig").set_index("bus_id")
    ov = pd.read_csv(HERE / "data/unit_bus_override.csv").set_index("unit_id").to_bus
    g["bus"] = g.unit_id.map(ov).fillna(g.bus_id)
    g["kv"] = B.voltage.reindex(g.bus).values
    g["moved"] = g.unit_id.isin(ov.index)
    g = g[~g.primary_fuel.isin(["Solar", "Wind"])].copy()
    g["tok"] = g.name.map(toks)
    out = []
    for r in ree.itertuples():
        rt = toks(r.sub) | toks(re.sub(r"\d", " ", r.code.split("-")[-1]))
        cand = g[[bool(rt & t) for t in g.tok]]
        size_ok = cand[(abs(cand.capacity_mw - r.mw) <= 0.15 * r.mw) | (abs(cand.capacity_mw - r.site_mw) <= 0.15 * r.site_mw)]
        # plants REE lists as one position for several model units: the site's units together
        if size_ok.empty and not cand.empty:
            tot = cand.groupby("name").capacity_mw.sum()
            names = tot[(abs(tot - r.mw) <= 0.15 * r.mw) | (abs(tot - r.site_mw) <= 0.15 * r.site_mw)].index
            size_ok = cand[cand.name.isin(names)]
        if size_ok.empty:
            out.append(dict(ree_sub=r.sub, ree_kv=r.kv, region=r.region, ree_code=r.code, ree_mw=r.mw, status="no match",
                            model_units="", model_names="; ".join(sorted(set(cand.name)))[:100], model_kv="", model_mw=""))
            continue
        kvs = sorted(set(size_ok.kv.dropna().astype(int)))
        status = "same voltage" if kvs == [r.kv] else "other voltage"
        out.append(dict(ree_sub=r.sub, ree_kv=r.kv, region=r.region, ree_code=r.code, ree_mw=r.mw, status=status,
                        model_units=" ".join(size_ok.unit_id), model_names="; ".join(sorted(set(size_ok.name)))[:100],
                        model_kv="/".join(map(str, kvs)), model_mw=round(size_ok.capacity_mw.sum(), 1),
                        moved_by_override=bool(size_ok.moved.any())))
    o = pd.DataFrame(out)
    o.to_csv(HERE / "data/sweep_a_unit_connections.csv", index=False)
    print(f"REE existing conventional positions: {len(o)} ({o.ree_mw.sum():,.0f} MW)")
    print(o.status.value_counts().to_string())
    print(o.groupby("status").ree_mw.sum().round(0).to_string())
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 60)
    print("\nother voltage:"); print(o[o.status == "other voltage"].drop(columns=["region"]).to_string(index=False))
    print("\nno match:"); print(o[o.status == "no match"][["ree_sub", "ree_kv", "ree_code", "ree_mw", "model_names"]].to_string(index=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
