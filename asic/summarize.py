"""Print the key results of the latest LibreLane run of blake3_top.

Usage (from anywhere):   python3 ~/blake3/asic/summarize.py [path/to/run]

Reads runs/<latest>/final/metrics.json and prints area, timing, power and the
signoff checks (DRC, LVS, antenna), plus the maximum clock implied by the
worst setup slack.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def latest_run():
    runs = sorted((HERE / "runs").glob("RUN_*"))
    if not runs:
        sys.exit("No runs found in asic/runs. Run LibreLane first.")
    return runs[-1]


def config_clock_period():
    for line in (HERE / "config.yaml").read_text().splitlines():
        if line.startswith("CLOCK_PERIOD:"):
            return float(line.split(":", 1)[1])
    return None


run = Path(sys.argv[1]) if len(sys.argv) > 1 else latest_run()
metrics_file = run / "final" / "metrics.json"
if not metrics_file.exists():
    sys.exit(f"{metrics_file} not found: the run may not have finished.")
m = json.loads(metrics_file.read_text())

print(f"Run: {run.name}\n")

# Groups of metrics to show; any metric whose name contains one of these
# strings is printed (names vary a little between LibreLane versions).
groups = {
    "Area": ["design__die__bbox", "design__core__area", "design__instance__count",
             "design__instance__area", "design__instance__utilization"],
    "Timing (worst slack per corner, ns)": ["timing__setup__ws", "timing__hold__ws",
                                            "timing__setup_vio__count", "timing__hold_vio__count"],
    "Power (W)": ["power__total", "power__internal__total", "power__switching__total",
                  "power__leakage__total"],
    "Signoff checks": ["route__drc_errors", "magic__drc_error__count", "klayout__drc_error__count",
                       "design__lvs_error__count", "antenna__violating__nets", "design__xor_difference__count"],
}

for title, keys in groups.items():
    print(title)
    shown = [k for k in sorted(m) if any(key in k for key in keys)]
    for k in shown:
        print(f"  {k:70s} {m[k]}")
    if not shown:
        print("  (none found)")
    print()

# Maximum clock at the typical corner (nominal wires, 25 C, 1.8 V)
period = config_clock_period()
typ = [k for k in m if k.startswith("timing__setup__ws__corner:nom_tt")]
if period and typ:
    slack = float(m[typ[0]])
    print(f"Clock target {period} ns, typical-corner setup slack {slack:.2f} ns")
    print(f"=> slowest path {period - slack:.2f} ns, max clock about {1000 / (period - slack):.1f} MHz (typical corner)")
worst = m.get("timing__setup__ws")
if period and worst is not None:
    w = float(worst)
    print(f"   worst corner slack {w:.2f} ns => max clock about {1000 / (period - w):.1f} MHz (all corners)")
