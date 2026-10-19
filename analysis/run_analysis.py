"""Israel road safety 2020-2024: the full analysis, from raw CBS files to findings.

    python scripts/download_data.py      # once: CBS files from data.gov.il
    python analysis/run_analysis.py

SQL (sql/*.sql, DuckDB) builds the tables; Python fits the models, draws the
figures and writes analysis/results.json, analysis/findings.md and
dashboard/data.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import statsmodels.api as sm  # noqa: E402
import statsmodels.formula.api as smf  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from pyproj import Transformer  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402
from sklearn.model_selection import GroupKFold  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SQL, FIG, OUT, DASH = ROOT / "sql", ROOT / "figures", ROOT / "analysis", ROOT / "dashboard"

BLUE, ORANGE, RED, GREY = "#2a78d6", "#eb6834", "#e34948", "#b9b8b2"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
SEQ = ["#f4f8fd", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
NOTE = "Source: Central Bureau of Statistics, road accidents with casualties (PUF), 2020-2024, via data.gov.il."
DISTRICTS = {1: "Jerusalem", 2: "North", 3: "Haifa", 4: "Central", 5: "Tel Aviv", 6: "South",
             7: "Judea & Samaria", 9: "Unknown"}
plt.rcParams.update({
    "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "savefig.facecolor": "#fcfcfb",
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
})


def save(fig, name):
    fig.text(0.01, 0.01, NOTE, fontsize=7.5, color=INK2, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    fig.savefig(FIG / name, dpi=160)
    plt.close(fig)


# ------------------------------------------------------------------ Q1: the trend

def q1_trend(t: pd.DataFrame, decomp: pd.DataFrame) -> dict:
    t = t.set_index("year")
    base = t.loc[2020]
    idx = {k: (t[k] / base[k] * 100) for k in ["fatal", "serious", "light", "injury_crashes"]}
    out = {
        "by_year": t.reset_index().to_dict(orient="records"),
        "change_pct_2020_2024": {k: float(v.loc[2024] - 100) for k, v in idx.items()},
        "fatal_excl_js_change_pct": float(t.loc[2024, "fatal_excl_js"] / base["fatal_excl_js"] * 100 - 100),
        "decomposition": decomp.to_dict(orient="records"),
    }
    total_change = int(decomp.change.sum())
    inter = int(decomp.loc[decomp.road == "Interurban", "change"].sum())
    out["interurban_share_of_fatal_increase"] = inter / total_change

    fig, ax = plt.subplots(figsize=(7.8, 4.0))
    years = t.index.to_numpy()
    style = {"fatal": (RED, "Fatal crashes"), "serious": (ORANGE, "Serious-injury crashes"),
             "injury_crashes": (INK2, "All injury crashes"), "light": (GREY, "Light-injury crashes")}
    for k, (color, label) in style.items():
        ax.plot(years, idx[k], color=color, lw=2.2 if k == "fatal" else 2, marker="o", markersize=6)
        ax.text(years[-1] + 0.12, idx[k].iloc[-1], f"{label}  {idx[k].iloc[-1] - 100:+.0f}%",
                color=INK, va="center", fontsize=9.5)
    ax.axhline(100, color=INK2, lw=1, ls=":")
    ax.set_xticks(years)
    ax.set_xlim(years[0] - 0.2, years[-1] + 2.3)
    ax.set_ylabel("Index, 2020 = 100")
    ax.set_title("Fewer crashes are reported, but more of them kill")
    ax.grid(axis="x", visible=False)
    save(fig, "01_trend_by_severity.png")
    return out


# --------------------------------------------------------- Q2: what makes a crash fatal

FEATURES_SQL = """
select severity = 1 as fatal, year, weekday in (6, 7) as weekend, is_judea_samaria,
  case road_type when 1 then 'Urban, junction' when 2 then 'Urban, between junctions'
       when 3 then 'Interurban, junction' when 4 then 'Interurban, between junctions'
       else 'Off-road' end as road,
  case when speed_limit_code = 0 then 'Unknown' when speed_limit_code = 1 then 'Up to 50'
       when speed_limit_code in (2, 3) then '60-70' when speed_limit_code in (4, 5) then '80-90'
       else '100-120' end as speed_limit,
  -- "Day, poor visibility" (code 2) has 127 crashes and 1 death: too sparse to stand alone.
  case when lighting in (1, 2, 10) then 'Daylight / twilight'
       when lighting in (3, 7) then 'Night, lit'
       when lighting in (4, 5, 8, 9) then 'Night, unlit or broken lights'
       else 'Unknown' end as light,
  case crash_type when 1 then 'Pedestrian hit' when 5 then 'Head-on' when 2 then 'Front-to-side'
       when 3 then 'Rear-end' when 4 then 'Side-to-side' when 8 then 'Hit fixed object'
       when 9 then 'Off-road / rollover' when 10 then 'Off-road / rollover'
       else 'Other' end as crash
from accidents
order by accident_id
"""
REFS = {"road": "Urban, junction", "speed_limit": "Up to 50", "light": "Daylight / twilight", "crash": "Rear-end"}
SHOW = [("crash", "Head-on"), ("crash", "Pedestrian hit"), ("crash", "Off-road / rollover"),
        ("crash", "Hit fixed object"), ("road", "Interurban, between junctions"),
        ("road", "Interurban, junction"), ("speed_limit", "100-120"), ("speed_limit", "80-90"),
        ("light", "Night, unlit or broken lights"), ("light", "Night, lit"), ("weekend", "True")]


def q2_severity_model(con) -> dict:
    d = con.execute(FEATURES_SQL).df()
    d["fatal"] = d.fatal.astype(int)
    terms = " + ".join(f"C({c}, Treatment('{r}'))" for c, r in REFS.items())
    formula = f"fatal ~ {terms} + C(year) + weekend + is_judea_samaria"
    m = smf.logit(formula, data=d).fit(disp=0)

    # Cross-validated discrimination, folds by year so a test year is never seen in training.
    preds = np.zeros(len(d))
    for tr, te in GroupKFold(n_splits=5).split(d, groups=d.year):
        f = smf.logit(formula.replace(" + C(year)", ""), data=d.iloc[tr]).fit(disp=0)
        preds[te] = f.predict(d.iloc[te])

    ors = {}
    for var, level in SHOW:
        key = (f"weekend[T.True]" if var == "weekend"
               else f"C({var}, Treatment('{REFS[var]}'))[T.{level}]")
        lo, hi = np.exp(m.conf_int().loc[key])
        ors[f"{var}: {level}"] = {"or": float(np.exp(m.params[key])), "lo": float(lo), "hi": float(hi)}

    # Illustrative contrast: the same crash at night on an unlit 90 km/h interurban road vs a lit city street.
    profile = pd.DataFrame([
        {"road": "Urban, between junctions", "speed_limit": "Up to 50", "light": "Night, lit",
         "crash": "Pedestrian hit", "year": 2024, "weekend": False, "is_judea_samaria": False},
        {"road": "Interurban, between junctions", "speed_limit": "80-90", "light": "Night, unlit or broken lights",
         "crash": "Pedestrian hit", "year": 2024, "weekend": False, "is_judea_samaria": False},
    ])
    p = m.predict(profile)
    out = {"n": int(len(d)), "fatal": int(d.fatal.sum()), "odds_ratios": ors,
           "cv_auc_by_year": float(roc_auc_score(d.fatal, preds)),
           "pedestrian_city_lit_p": float(p.iloc[0]), "pedestrian_interurban_unlit_p": float(p.iloc[1])}

    labels = {"crash: Head-on": "Head-on collision", "crash: Pedestrian hit": "Pedestrian hit",
              "crash: Off-road / rollover": "Off-road / rollover", "crash: Hit fixed object": "Hit a fixed object",
              "road: Interurban, between junctions": "Interurban road, between junctions",
              "road: Interurban, junction": "Interurban junction", "speed_limit: 100-120": "Speed limit 100-120",
              "speed_limit: 80-90": "Speed limit 80-90", "light: Night, unlit or broken lights": "Night, no working lights",
              "light: Night, lit": "Night, lit road", "weekend: True": "Friday or Saturday"}
    items = sorted(ors.items(), key=lambda kv: kv[1]["or"])
    fig, ax = plt.subplots(figsize=(7.8, 4.6))
    y = np.arange(len(items))
    for i, (k, v) in enumerate(items):
        ax.plot([v["lo"], v["hi"]], [i, i], color=INK2, lw=1.5)
        ax.scatter(v["or"], i, color=RED if v["lo"] > 1 else GREY, s=55, zorder=3)
        ax.text(v["hi"] * 1.08, i, f"×{v['or']:.1f}", va="center", fontsize=9, color=INK)
    ax.axvline(1, color=INK2, lw=1, ls=":")
    ax.set_xscale("log")
    ax.set_xticks([0.5, 1, 2, 4, 8, 16], ["0.5", "1", "2", "4", "8", "16"])
    ax.set_yticks(y, [labels[k] for k, _ in items])
    ax.set_xlabel("Odds that an injury crash is fatal, vs. baseline (log scale, 95% CI)")
    ax.set_title("What turns a crash into a fatal one")
    ax.grid(axis="y", visible=False)
    save(fig, "02_what_makes_a_crash_fatal.png")
    return out


# ------------------------------------------------------------- Q3: hotspots

def empirical_bayes(seg: pd.DataFrame, count: str, light: str) -> pd.Series:
    """Shrink each segment's fatal+serious count towards what similar segments see.

    "Similar" = same road class (national / regional / local) and the same volume of
    light-injury crashes, which stands in for traffic: there is no public traffic count
    per segment, but busy roads have more fender-benders. A negative binomial gives the
    expected count mu and over-dispersion alpha; the estimate is w*mu + (1-w)*observed,
    with w = 1 / (1 + mu*alpha). Lucky or unlucky years get pulled back; a segment that
    is bad year after year keeps most of its count.
    """
    d = seg.assign(cls=np.select([seg.road < 100, seg.road < 1000], ["national", "regional"], "local"),
                   log_light=np.log1p(seg[light]), y=seg[count])
    m = smf.negativebinomial("y ~ C(cls) + log_light", data=d).fit(disp=0, maxiter=300)
    alpha = float(m.params["alpha"])
    mu = m.predict(d)
    w = 1 / (1 + mu * alpha)
    est = w * mu + (1 - w) * d.y
    return est, mu, {"alpha": alpha, "converged": bool(m.mle_retvals["converged"])}


def top_n(df: pd.DataFrame, n: int, col: str) -> pd.DataFrame:
    """Largest n by `col`, ties broken by road and km so every run picks the same rows."""
    return df.sort_values([col, "road", "km"], ascending=[False, True, True]).head(n)


def q3_hotspots(seg: pd.DataFrame, trend: float) -> tuple[dict, pd.DataFrame]:
    seg = seg.sort_values(["road", "km"]).reset_index(drop=True)
    seg["eb_2020_22"], _, fit_info = empirical_bayes(seg, "ksi_2020_22", "light_2020_22")
    # Predicting 2023-24 from 2020-22: 2 years instead of 3, and the national trend in
    # fatal+serious interurban crashes. Both methods get the same adjustment.
    scale = 2 / 3 * trend
    out = {"segments": int(len(seg)), "trend_ratio": trend,
           "eb_alpha": fit_info["alpha"], "eb_converged": fit_info["converged"]}
    for n in (20, 50):
        best = int(top_n(seg, n, "ksi_2023_24").ksi_2023_24.sum())
        for name, col in (("raw", "ksi_2020_22"), ("eb", "eb_2020_22")):
            top = top_n(seg, n, col)
            pred, act = float(top[col].sum() * scale), int(top.ksi_2023_24.sum())
            out[f"{name}_top{n}"] = {"predicted_2023_24": pred, "actual_2023_24": act,
                                     "error_pct": (pred - act) / act * 100, "captured_vs_hindsight": act / best}

    # Final ranking for action: all five years, same method.
    full = seg.assign(ksi_all=seg.ksi_2020_22 + seg.ksi_2023_24)
    full["eb_all"], full["expected_similar"], _ = empirical_bayes(full, "ksi_all", "light_all_years")
    # Excess = how many more fatal+serious crashes than a segment of the same class and
    # traffic would expect (the Highway Safety Manual's "potential for safety improvement").
    # This, not the raw total, is what an engineering fix can remove.
    full["excess_per_year"] = (full.eb_all - full.expected_similar) / 5
    tr = Transformer.from_crs("EPSG:2039", "EPSG:4326", always_xy=True)
    full["lon"], full["lat"] = tr.transform(full.itm_x.to_numpy(), full.itm_y.to_numpy())
    full["district_name"] = full.district.map(DISTRICTS).fillna("Unknown")
    full["eb_per_year"] = full.eb_all / 5
    cols = ["road", "km", "district_name", "ksi_all", "fatal_all_years", "light_all_years",
            "eb_per_year", "excess_per_year"]
    out["top15_by_total"] = top_n(full, 15, "eb_all")[cols].to_dict(orient="records")
    top = top_n(full, 15, "excess_per_year")
    out["top15_by_excess"] = top[cols].to_dict(orient="records")
    out["roads_in_top15_by_total"] = sorted({int(x) for x in top_n(full, 15, "eb_all").road})
    out["roads_in_top15_by_excess"] = sorted({int(x) for x in top.road})

    # Chart A: regression to the mean.
    r, e = out["raw_top20"], out["eb_top20"]
    fig, ax = plt.subplots(figsize=(7.4, 3.7))
    pred, act = [r["predicted_2023_24"], e["predicted_2023_24"]], [r["actual_2023_24"], e["actual_2023_24"]]
    x = np.arange(2)
    ax.bar(x - 0.18, pred, width=0.34, color=GREY, label="Predicted for 2023-24 (from 2020-22)")
    ax.bar(x + 0.18, act, width=0.34, color=BLUE, label="What actually happened")
    for i in range(2):
        ax.text(x[i] - 0.18, pred[i] + 2, f"{pred[i]:.0f}", ha="center", color=INK)
        ax.text(x[i] + 0.18, act[i] + 2, f"{act[i]}", ha="center", color=INK)
    ax.set_xticks(x, ["Top 20 by raw counts", "Top 20 by empirical Bayes"])
    ax.set_ylabel("Fatal + serious crashes")
    ax.set_ylim(0, max(pred + act) * 1.25)
    ax.set_title("Raw counts over-promise: the 'worst' segments regress to the mean")
    ax.legend(frameon=False, loc="upper right", fontsize=9)
    ax.grid(axis="x", visible=False)
    save(fig, "03_regression_to_the_mean.png")

    # Chart B: the map, with a zoom on the Tel Aviv area where most hotspots sit.
    fig, (ax, az) = plt.subplots(1, 2, figsize=(9.6, 8.0), gridspec_kw={"width_ratios": [1, 1.25]})
    zoom = (34.70, 35.02, 31.93, 32.20)
    for a, pts in ((ax, full), (az, full)):
        a.scatter(pts.lon, pts.lat, s=np.clip(pts.ksi_all, 1, 30) * (1.2 if a is ax else 3),
                  color=GREY, alpha=0.45, linewidths=0)
        a.set_aspect(1 / np.cos(np.deg2rad(31.5)))
        a.set_xticks([])
        a.set_yticks([])
        a.grid(False)
    ax.scatter(top.lon, top.lat, s=top.excess_per_year * 70, color=RED, edgecolor="#fcfcfb", lw=1, zorder=3)
    ax.add_patch(plt.Rectangle((zoom[0], zoom[2]), zoom[1] - zoom[0], zoom[3] - zoom[2], fill=False,
                               edgecolor=INK2, lw=1))
    for sp in ax.spines.values():
        sp.set_visible(False)
    az.set_xlim(zoom[0], zoom[1])
    az.set_ylim(zoom[2], zoom[3])
    for sp in az.spines.values():
        sp.set_edgecolor(INK2)
    ranked = top.reset_index(drop=True)
    ranked["rank"] = ranked.index + 1
    inside = ranked[ranked.lon.between(zoom[0], zoom[1]) & ranked.lat.between(zoom[2], zoom[3])]
    outside = ranked.drop(inside.index)
    az.scatter(inside.lon, inside.lat, s=inside.excess_per_year * 160, color=RED, edgecolor="#fcfcfb",
               lw=1.2, zorder=3)
    for _, row in inside.iterrows():
        az.text(row.lon, row.lat, str(row["rank"]), color="#ffffff", fontsize=7.5, ha="center",
                va="center", zorder=4, fontweight="bold")
    for _, row in outside.iterrows():
        ax.annotate(f"#{row['rank']} Road {row.road}, km {row.km}", (row.lon, row.lat), xytext=(7, 0),
                    textcoords="offset points", fontsize=8, color=INK, va="center")
    legend = "\n".join(f"#{r['rank']:<3} Road {r.road}, km {r.km}" for _, r in inside.iterrows())
    az.text(1.02, 1.0, "In the zoom:\n" + legend, transform=az.transAxes, va="top", fontsize=8, color=INK,
            family="monospace")
    ax.set_title("15 segments far more dangerous\nthan similar roads", fontsize=11)
    az.set_title("Tel Aviv area", fontsize=11)
    save(fig, "04_hotspot_map.png")
    return out, full


# --------------------------------------------------------------- Q4: when

def q4_when(hw: pd.DataFrame) -> dict:
    days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    grid = hw.pivot_table(index="weekday", columns="hour", values="killed_or_serious", fill_value=0)
    fatal_rate = hw.groupby("hour")[["fatal", "crashes"]].sum()
    fatal_rate["rate"] = fatal_rate.fatal / fatal_rate.crashes
    night = fatal_rate.loc[list(range(0, 6))].sum()
    day = fatal_rate.loc[list(range(8, 18))].sum()
    by_day = hw.groupby("weekday")[["fatal", "crashes"]].sum()
    out = {
        "fatal_rate_00_06": float(night.fatal / night.crashes),
        "fatal_rate_08_18": float(day.fatal / day.crashes),
        "fatal_rate_by_weekday": {days[i - 1]: float(r.fatal / r.crashes) for i, r in by_day.iterrows()},
        "peak_cell": {"weekday": days[int(grid.stack().idxmax()[0]) - 1], "hour": int(grid.stack().idxmax()[1])},
    }
    fig, ax = plt.subplots(figsize=(8.4, 3.6))
    cmap = LinearSegmentedColormap.from_list("seq", SEQ)
    im = ax.imshow(grid.to_numpy(), aspect="auto", cmap=cmap)
    ax.set_yticks(range(7), days)
    ax.set_xticks(range(0, 24, 3), [f"{h:02d}:00" for h in range(0, 24, 3)])
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.set_label("Fatal + serious crashes, 2020-24", color=INK2)
    cb.outline.set_visible(False)
    ax.set_title("Fatal and serious crashes follow the weekday commute")
    save(fig, "05_when_heatmap.png")
    return out


def write_findings(r: dict) -> None:
    q1, q2, q3, q4 = r["q1"], r["q2"], r["q3"], r["q4"]
    c = q1["change_pct_2020_2024"]
    o = q2["odds_ratios"]
    pct = lambda v: f"{v * 100:.1f}%"  # noqa: E731
    lines = [
        "# Findings", "", "_Generated by `analysis/run_analysis.py` from CBS data. Every number below is in `results.json`._", "",
        "## Q1: Are Israel's roads getting safer?",
        f"- Injury crashes {c['injury_crashes']:+.0f}% (2020 → 2024), but fatal crashes {c['fatal']:+.0f}% and "
        f"serious-injury crashes {c['serious']:+.0f}%. Light-injury crashes {c['light']:+.0f}%.",
        f"- Excluding Judea & Samaria, fatal crashes {q1['fatal_excl_js_change_pct']:+.0f}%.",
        f"- {pct(q1['interurban_share_of_fatal_increase'])} of the rise in fatal crashes is on interurban roads.", "",
        "## Q2: What makes a crash fatal?",
        f"- Logistic model on {q2['n']:,} injury crashes ({q2['fatal']:,} fatal); cross-validated AUC "
        f"{q2['cv_auc_by_year']:.3f} with each year held out in turn.",
        *[f"- {k}: odds ×{v['or']:.1f} (95% CI {v['lo']:.1f}–{v['hi']:.1f})" for k, v in
          sorted(o.items(), key=lambda kv: -kv[1]["or"])],
        f"- A pedestrian hit at night on a lit city street: {pct(q2['pedestrian_city_lit_p'])} fatal. "
        f"On an unlit 80-90 km/h interurban road: {pct(q2['pedestrian_interurban_unlit_p'])}.", "",
        "## Q3: Where should the money go?",
        f"- {q3['segments']:,} interurban 1-km segments with at least one injury crash. Fatal+serious crashes per year "
        f"rose ×{q3['trend_ratio']:.2f} between 2020-22 and 2023-24; both methods' predictions include that trend.",
        *[f"- Top {n} by {'raw counts' if m == 'raw' else 'empirical Bayes'}: predicted "
          f"{q3[f'{m}_top{n}']['predicted_2023_24']:.0f}, actual {q3[f'{m}_top{n}']['actual_2023_24']} "
          f"({q3[f'{m}_top{n}']['error_pct']:+.0f}%); captured {pct(q3[f'{m}_top{n}']['captured_vs_hindsight'])} "
          "of what a perfect-hindsight list would have"
          for n in (20, 50) for m in ("raw", "eb")], "",
        "## Q4: When?",
        f"- Probability an injury crash is fatal: {pct(q4['fatal_rate_00_06'])} between 00:00 and 06:00 vs "
        f"{pct(q4['fatal_rate_08_18'])} between 08:00 and 18:00.",
        f"- By day: " + ", ".join(f"{d} {pct(v)}" for d, v in q4["fatal_rate_by_weekday"].items()) + ".",
    ]
    (OUT / "findings.md").write_text("\n".join(lines) + "\n")


def main():
    FIG.mkdir(exist_ok=True)
    DASH.mkdir(exist_ok=True)
    con = duckdb.connect()
    import os
    os.chdir(ROOT)
    con.execute((SQL / "00_load.sql").read_text())
    q = {f.stem: con.execute(f.read_text()).df() for f in sorted(SQL.glob("0[1-9]_*.sql"))}
    agg = OUT / "aggregates"
    agg.mkdir(exist_ok=True)
    for name, df in q.items():
        df.to_csv(agg / f"{name}.csv", index=False)

    res = {"q1": q1_trend(q["01_trend_by_severity"], q["02_fatal_change_decomposition"]),
           "q2": q2_severity_model(con)}
    trend = con.execute("""select (count(*) filter (where year >= 2023) / 2.0)
        / (count(*) filter (where year <= 2022) / 3.0) from accidents
        where severity <= 2 and road_type in (3, 4)""").fetchone()[0]
    res["q3"], segments = q3_hotspots(q["04_road_segments"], float(trend))
    res["q4"] = q4_when(q["03_hour_weekday"])
    res["data_quality"] = q["05_missingness_by_severity"].to_dict(orient="records")
    (OUT / "results.json").write_text(json.dumps(res, indent=2, default=float))
    write_findings(res)

    # Data for the interactive dashboard: aggregates only.
    seg_out = segments[segments.ksi_all > 0][["road", "km", "district_name", "ksi_all", "fatal_all_years",
                                             "eb_per_year", "excess_per_year", "lat", "lon"]]
    # A few source coordinates are corrupt (one converts to infinity): keep points inside Israel's bounding box.
    seg_out = seg_out[seg_out.lat.between(29.4, 33.4) & seg_out.lon.between(34.2, 35.95)].round(4)
    yearly = con.execute("""select year, case when is_urban then 'Urban' else 'Interurban' end as area,
        severity, count(*) as n from accidents where road_type <> 5 group by all order by all""").df()
    payload = json.dumps({
        "segments": seg_out.to_dict(orient="records"),
        "yearly": yearly.to_dict(orient="records"),
        "hour_weekday": q["03_hour_weekday"].to_dict(orient="records"),
    }, separators=(",", ":"))
    page = (DASH / "template.html").read_text().replace("/*DATA*/null", payload)
    (DASH / "dashboard.html").write_text(page)  # page body (published as a preview)
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "index.html").write_text(  # full document for GitHub Pages
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        "</head>\n<body>\n" + page + "\n</body>\n</html>\n")
    print((OUT / "findings.md").read_text())


if __name__ == "__main__":
    main()
