"""Step 7 (b) test data: Data/Bus_Data.csv and Data/lines.csv with the cross-border ties REE's tie list and
OpenStreetMap show but the model lacks (data/sweep_b_ties.csv). Written to redispatch_realism/data/sweep_b/, where
nothing reads them: the test run (ly9b) copies them over Data/ in a separate copy of the repo, so this branch, main
and every other run keep the shared data. Not for merging until the group has seen the test.

  ES00814 country ES -> PT     Aldeadávila-Lagoaça 400 kV (LTGES0355) is modelled, but its Portuguese end is
                               labelled ES and so gets no border share (OSM way 144327162, REN)
  + Aldeadávila - Pocinho 1, 2 220 kV, ES00245 -> ES00813, one circuit each (OSM ways 1432621809/10, REE)
  + Vic - Baixas               400 kV: the model has Vic (ES00012) -> ES00737 (LTGES0558) and stops there; added
                               ES00737 -> new French bus ES01300 at Baixas, 57.4 km along OSM way 169729517 and its
                               continuations "Liaison 400 kV n°1 Vich - Baixas" (REE 2012 p. 8; RTE),
                               one circuit

New lines take the model's generic per-km values of their voltage level (220 kV: r 0.06, x 0.301 Ω/km, c 12.5
nF/km, Imax 1.29 kA; 400 kV: 0.03, 0.246, 13.8, 2.58, as every other line of that level) and their OSM route length (Aldeadávila - Pocinho: OSM does not trace past Aldeadávila, so straight distance 37.9 km
x the route factor of the model's own parallel tie Saucelle - Pocinho, 33.35 / 28.7 km = 1.16: 44 km, an estimate).
The new bus gets no load and no reactor (as every foreign bus), so load.csv and reactors.csv are unchanged.

    python redispatch_realism/build_sweep_b_data.py --vic-baixas-km <km> --pocinho-km <km> --baixas <lat> <lon>
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "Data"
OUT = HERE / "data" / "sweep_b"
GENERIC = {220: ("0.06", "0.301", "12.5", "1.29"), 400: ("0.03", "0.246", "13.8", "2.58")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--vic-baixas-km", type=float, required=True)
    ap.add_argument("--pocinho-km", type=float, required=True)
    ap.add_argument("--baixas", type=float, nargs=2, required=True, metavar=("LAT", "LON"))
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    raw = (DATA / "Bus_Data.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
    lines = raw.decode("utf-8-sig").split("\r\n")
    i = [k for k, l in enumerate(lines) if l.startswith("ES00814,")]
    assert len(i) == 1 and lines[i[0]].endswith(",ES"), lines[i[0]] if i else "ES00814 not found"
    lines[i[0]] = lines[i[0]][:-3] + ",PT"
    assert not any(l.startswith("ES01300,") for l in lines)
    body = [l for l in lines if l]
    body.append(f"ES01300,400,{a.baixas[0]},{a.baixas[1]},FR")
    (OUT / "Bus_Data.csv").write_bytes(b"\xef\xbb\xbf" + ("\r\n".join(body) + "\r\n").encode("utf-8"))

    raw = (DATA / "lines.csv").read_bytes()
    assert b"\r\n" in raw
    rows = [l for l in raw.decode("ascii").split("\r\n") if l]
    assert rows[0] == "line_id,bus0,bus1,voltage,circuits,length,dc,r_per_length,x_per_length,c_per_length,Imax"
    new = [("LTGES_S7B_POC1", "ES00245", "ES00813", 220, a.pocinho_km),
           ("LTGES_S7B_POC2", "ES00245", "ES00813", 220, a.pocinho_km),
           ("LTGES_S7B_VICBAI", "ES00737", "ES01300", 400, a.vic_baixas_km)]
    for lid, b0, b1, v, km in new:
        r, x, c, imax = GENERIC[v]
        rows.append(f"{lid},{b0},{b1},{v},1,{km:.2f},f,{r},{x},{c},{imax}")
    (OUT / "lines.csv").write_bytes(("\r\n".join(rows) + "\r\n").encode("ascii"))
    print(f"wrote {OUT}: ES00814 -> PT, bus ES01300 (Baixas, FR) at {a.baixas}, lines: " +
          ", ".join(f"{l[0]} {l[4]:.1f} km" for l in new))


if __name__ == "__main__":
    main()
