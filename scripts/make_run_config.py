"""Write a copy of config.toml for one stage of a split run.

A split run (scripts/run_markets_sequential.sh, scripts/run_redispatch_only.sh)
first clears the market stages for the whole period in order, then runs the
network redispatch for each chunk on its own. Both need a config copy that
differs from config.toml in a few switches only; this script writes it, editing
the text in place (comments and layout are kept).

    python3 scripts/make_run_config.py <out.toml> --stage markets|redispatch
                                       [--gas on|off] [--res-input accepted|offered]

  --stage markets      [redispatch] enabled = false
  --stage redispatch   [redispatch] enabled = true, from_saved = "BAL"
  --gas on             the gas/coal switches, all off in config.toml:
                       [costs.gas_unit_efficiency] enabled, [unit_commitment]
                       enabled, [costs.coal_srmc] enabled, [fleet] enabled and
                       [islands] exclude_from_market (the coal fleet without its
                       availability factor needs the island plants out of the
                       market and the closed plants removed)
  --res-input X        [run] res_input = "X"
"""
import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

GAS_ON = [("costs.gas_unit_efficiency", "enabled", "true"),
          ("unit_commitment", "enabled", "true"),
          ("costs.coal_srmc", "enabled", "true"),
          ("fleet", "enabled", "true"),
          ("islands", "exclude_from_market", "true")]


def set_key(text, section, key, value):
    """Set `key = value` in [section] (the first such line before the next header)."""
    lines = text.split("\n")
    head = re.compile(r"^\s*\[([^\[\]]+)\]\s*(#.*)?$")
    inside = False
    for i, line in enumerate(lines):
        m = head.match(line)
        if m:
            inside = m.group(1).strip() == section
            continue
        if inside:
            k = re.match(rf"^(\s*{re.escape(key)}\s*=\s*)([^#]*?)(\s*#.*)?$", line)
            if k:
                lines[i] = k.group(1) + value + (k.group(3) or "")
                return "\n".join(lines)
    sys.exit(f"config.toml: no '{key}' in [{section}]")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--stage", choices=["markets", "redispatch"], required=True)
    ap.add_argument("--gas", choices=["on", "off"], default="off")
    ap.add_argument("--res-input", choices=["accepted", "offered"])
    ap.add_argument("--config", type=Path, default=REPO / "config.toml")
    a = ap.parse_args()

    raw = a.config.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    if a.stage == "markets":
        text = set_key(text, "redispatch", "enabled", "false")
    else:
        text = set_key(text, "redispatch", "enabled", "true")
        text = set_key(text, "redispatch", "from_saved", '"BAL"')
    if a.gas == "on":
        for sec, key, val in GAS_ON:
            text = set_key(text, sec, key, val)
    if a.res_input:
        text = set_key(text, "run", "res_input", f'"{a.res_input}"')
    if crlf:
        text = text.replace("\n", "\r\n")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = a.out.with_suffix(a.out.suffix + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(a.out)
    print(f"wrote {a.out} (stage {a.stage}, gas {a.gas}{', res_input ' + a.res_input if a.res_input else ''})")


if __name__ == "__main__":
    main()
