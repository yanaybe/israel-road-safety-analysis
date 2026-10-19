"""The headline claims, as tests. If the data changes and a claim stops being true, CI fails."""
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def r():
    subprocess.run([sys.executable, str(ROOT / "analysis" / "run_analysis.py")], check=True, capture_output=True)
    return json.loads((ROOT / "analysis" / "results.json").read_text())


def test_fatal_crashes_rose_while_injury_crashes_fell(r):
    c = r["q1"]["change_pct_2020_2024"]
    assert c["fatal"] > 20 and c["injury_crashes"] < -10


def test_severity_model_generalises_to_unseen_years(r):
    assert r["q2"]["cv_auc_by_year"] > 0.70


@pytest.mark.parametrize("n", [20, 50])
def test_empirical_bayes_beats_raw_counts_on_held_out_years(r, n):
    raw, eb = r["q3"][f"raw_top{n}"], r["q3"][f"eb_top{n}"]
    assert eb["actual_2023_24"] > raw["actual_2023_24"], "EB list should catch more future crashes"
    assert abs(eb["error_pct"]) < abs(raw["error_pct"]), "EB should be better calibrated"


def test_raw_ranking_regresses_to_the_mean(r):
    assert r["q3"]["raw_top20"]["error_pct"] > 25


def test_dashboard_data_is_aggregate_and_finite():
    page = (ROOT / "dashboard" / "dashboard.html").read_text()
    data = json.loads(page.split("const DATA = ", 1)[1].split(";\nconst NS", 1)[0])
    for row in data["segments"]:
        assert "accident_id" not in row
        assert all(math.isfinite(v) for v in row.values() if isinstance(v, (int, float)))
        assert 29.4 <= row["lat"] <= 33.4 and 34.2 <= row["lon"] <= 35.95
