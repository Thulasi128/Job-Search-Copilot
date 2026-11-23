"""Evaluation script measuring human application review time.

Enforces ground rule: No time-saving claim permitted anywhere unless >= 5 timing rows exist.
"""

import csv
from pathlib import Path
import sys
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TIMING_CSV_PATH = PROJECT_ROOT / "data" / "timing.csv"
MIN_TIMING_TRIALS = 5


def evaluate_timing() -> Dict[str, Any]:
    """Read timing measurements and compute review duration statistics."""
    if not TIMING_CSV_PATH.exists():
        return {
            "n": 0,
            "has_sufficient_data": False,
            "message": "timing.csv not found. No timing measurements recorded.",
        }

    rows: List[Dict[str, str]] = []
    with open(TIMING_CSV_PATH, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader((line for line in f if not line.startswith("#")))
        for r in reader:
            if r.get("traditional_prep_seconds") and r.get("copilot_review_seconds"):
                rows.append(r)

    n = len(rows)
    if n < MIN_TIMING_TRIALS:
        return {
            "n": n,
            "has_sufficient_data": False,
            "message": f"Insufficient timing data (n = {n} < {MIN_TIMING_TRIALS}). No time-saving claim permitted.",
            "rows": rows,
        }

    trad_times = [float(r["traditional_prep_seconds"]) for r in rows]
    copilot_times = [float(r["copilot_review_seconds"]) for r in rows]

    avg_trad = sum(trad_times) / n
    avg_copilot = sum(copilot_times) / n
    reduction_pct = ((avg_trad - avg_copilot) / avg_trad) * 100 if avg_trad > 0 else 0.0

    return {
        "n": n,
        "has_sufficient_data": True,
        "avg_traditional_seconds": round(avg_trad, 1),
        "avg_copilot_seconds": round(avg_copilot, 1),
        "reduction_percentage": round(reduction_pct, 1),
        "rows": rows,
    }


def main():
    print("=" * 65)
    print("APPLICATION REVIEW TIME MEASUREMENT BENCHMARK")
    print("=" * 65)

    stats = evaluate_timing()
    n = stats["n"]
    print(f"\nMeasured Trials: n = {n}")

    if not stats["has_sufficient_data"]:
        print(f"NOTICE: {stats['message']}")
        print("Required Action: Record at least 5 real human trials in data/timing.csv.")
    else:
        print(f"Average Traditional Preparation: {stats['avg_traditional_seconds']} seconds ({stats['avg_traditional_seconds']/60:.1f} min)")
        print(f"Average Copilot Review Time:     {stats['avg_copilot_seconds']} seconds ({stats['avg_copilot_seconds']/60:.1f} min)")
        print(f"Measured Time Reduction:         {stats['reduction_percentage']:.1f}%")
    print("=" * 65)


if __name__ == "__main__":
    main()

