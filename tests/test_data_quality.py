"""Checks on the raw CBS files. If these fail, no number downstream is trustworthy."""
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]

# Row counts reported by data.gov.il's datastore for each yearly file.
EXPECTED_ROWS = {2020: 10836, 2021: 11554, 2022: 10404, 2023: 8832, 2024: 8315}


@pytest.fixture(scope="module")
def con():
    import os
    os.chdir(ROOT)
    c = duckdb.connect()
    c.execute((ROOT / "sql" / "00_load.sql").read_text())
    return c


def one(con, sql):
    return con.execute(sql).fetchone()[0]


def test_every_year_is_complete(con):
    got = dict(con.execute("select year, count(*) from accidents group by 1").fetchall())
    assert got == EXPECTED_ROWS


def test_accident_ids_are_unique(con):
    assert one(con, "select count(*) - count(distinct accident_id) from accidents") == 0


def test_codes_are_in_range(con):
    assert one(con, "select count(*) from accidents where severity not in (1, 2, 3)") == 0
    assert one(con, "select count(*) from accidents where hour not between 0 and 23") == 0
    assert one(con, "select count(*) from accidents where weekday not between 1 and 7") == 0


def test_every_code_used_has_a_label(con):
    # severity, crash type and road type codes must all exist in the CBS dictionary
    for col, table in (("severity", 4), ("crash_type", 5), ("road_type", 2)):
        missing = one(con, f"""select count(*) from (select distinct {col} c from accidents) a
            where not exists (select 1 from codes where code_table = {table} and code = a.c)""")
        assert missing == 0, col


def test_coordinates_are_almost_all_valid(con):
    bad = one(con, """select count(*) from accidents
        where itm_x not between 100000 and 300000 or itm_y not between 350000 and 820000 or itm_x is null""")
    assert bad / one(con, "select count(*) from accidents") < 0.005


def test_negative_km_markers_are_rare_and_excluded(con):
    assert one(con, "select count(*) from accidents where km_tenths < 0") < 50
    seg = con.execute((ROOT / "sql" / "04_road_segments.sql").read_text()).df()
    assert (seg.km >= 0).all()


@pytest.mark.parametrize("year,scope,published,source", [
    # National Road Safety Authority figures as reported in the press; scopes differ by year.
    (2021, "excl_js", 304, "NRSA annual report via saver.one"),
    (2023, "all", 336, "NRSA via JNS, 2024"),
])
def test_fatal_counts_reconcile_with_published_figures(con, year, scope, published, source):
    where = "and not is_judea_samaria" if scope == "excl_js" else ""
    ours = one(con, f"select count(*) from accidents where severity = 1 and year = {year} {where}")
    assert abs(ours - published) / published <= 0.01, f"{ours} vs {published} ({source})"
