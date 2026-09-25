"""Advanced payments analysis on top of the KPI layer.

    merchant_health         Growing / Stable / Declining / Dormant / Churned / never-transacted,
                            plus alert flags (negative GP, billing leakage, low success rate)
    cohort_retention        go-live quarter x months-since-live active share (maturity-masked)
    growth_bridge           FY2025 -> FY2026 GMV: new / expansion / contraction / churn, by segment
    gateway_incidents       robust z-score of daily success rate vs a trailing baseline; incidents
                            grouped into episodes with excess failures and GMV / revenue at risk
    gateway_degradation     6-month slope of monthly success rate per gateway x method
    concentration           top-10 / top-10% share and HHI for GMV and GP
    profitability           negative-GP merchants with root cause and a repricing what-if
    activation              median onboarding times by integration type

All headline numbers -> reports/analysis_results.json.

Run:  python python/analysis.py
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from utils import get_logger, load_config, read_csv_checked, safe_div

log = get_logger("analysis")


def merchant_health(cfg, mm: pd.DataFrame, merchants: pd.DataFrame) -> pd.DataFrame:
    lc, an = cfg["lifecycle"], cfg["analysis"]
    last = int(mm["month_key"].max())
    months = sorted(mm["month_key"].unique())
    l3, p3 = months[-3:], months[-6:-3]
    g = mm.groupby("merchant_key").apply(lambda x: pd.Series({
        "gmv_last_3m": x.loc[x["month_key"].isin(l3), "gmv"].sum(),
        "gmv_prior_3m": x.loc[x["month_key"].isin(p3), "gmv"].sum(),
        "gmv_fy26": x.loc[x["fiscal_year"] == 2026, "gmv"].sum(),
        "revenue_fy26": x.loc[x["fiscal_year"] == 2026, "revenue"].sum(),
        "gp_fy26": x.loc[x["fiscal_year"] == 2026, "gp"].sum(),
        "leakage_fy26": x.loc[x["fiscal_year"] == 2026, "billing_leakage"].sum(),
        "success_last_3m": x.loc[x["month_key"].isin(l3), "success_txn"].sum(),
        "failed_last_3m": x.loc[x["month_key"].isin(l3), "failed_txn"].sum(),
    }), include_groups=False)
    h = merchants.set_index("merchant_key")[["mid", "merchant_name", "country_code", "segment", "vertical",
                                             "integration_type", "account_manager", "lifecycle_status",
                                             "live_date", "last_txn_date"]].join(g, how="left").fillna(
        {"gmv_last_3m": 0, "gmv_prior_3m": 0, "gmv_fy26": 0, "revenue_fy26": 0, "gp_fy26": 0, "leakage_fy26": 0,
         "success_last_3m": 0, "failed_last_3m": 0})
    chg = safe_div(h["gmv_last_3m"] - h["gmv_prior_3m"], h["gmv_prior_3m"])
    h["gmv_change_3m_pct"] = chg
    big_enough = h["gmv_prior_3m"] >= lc["min_gmv_for_trend_usd"] * 3
    h["health_status"] = np.select(
        [h["lifecycle_status"] != "Active",
         big_enough & (chg <= lc["decline_threshold_pct"]),
         big_enough & (chg >= lc["growth_threshold_pct"])],
        [h["lifecycle_status"], "Declining", "Growing"], default="Stable")
    h["success_rate_last_3m"] = safe_div(h["success_last_3m"], h["success_last_3m"] + h["failed_last_3m"])
    h["flag_negative_gp"] = ((h["gp_fy26"] < 0) & (h["revenue_fy26"] > 1000)).astype(int)
    h["flag_billing_leakage"] = (h["leakage_fy26"] > 0.02 * (h["revenue_fy26"] + h["leakage_fy26"]) ).astype(int) \
        * (h["leakage_fy26"] > 50).astype(int)
    h["flag_low_success_rate"] = ((h["success_rate_last_3m"] < an["low_success_rate"]) &
                                  (h["success_last_3m"] + h["failed_last_3m"] >= 300)).astype(int)
    h["flag_declining"] = (h["health_status"] == "Declining").astype(int)
    h["flag_inactive"] = h["health_status"].isin(["Dormant", "Churned"]).astype(int)
    h["flag_never_transacted"] = (h["health_status"] == "Live - never transacted").astype(int)
    flags = [c for c in h.columns if c.startswith("flag_")]
    h["alert_count"] = h[flags].sum(axis=1)
    h["as_of_month"] = last
    return h.reset_index()


def cohort_retention(mm: pd.DataFrame, merchants: pd.DataFrame) -> pd.DataFrame:
    m = merchants[merchants["first_txn_date"].notna() & (pd.to_datetime(merchants["live_date"]) >= "2024-07-01")].copy()
    live = pd.to_datetime(m["live_date"])
    m["cohort"] = live.dt.year.astype(str) + "-Q" + ((live.dt.month + 2) // 3).astype(str)
    m["live_idx"] = live.dt.year * 12 + live.dt.month
    end_idx = int(mm["month_key"].max()) // 100 * 12 + int(mm["month_key"].max()) % 100
    act = mm[mm["is_active"] == 1][["merchant_key", "months_since_live"]]
    rows = []
    for c, grp in m.groupby("cohort"):
        size = len(grp)
        observed = end_idx - grp["live_idx"].max()
        a = act[act["merchant_key"].isin(grp["merchant_key"])]
        for k in range(0, 13):
            val = a[a["months_since_live"] == k]["merchant_key"].nunique() / size if k <= observed else np.nan
            rows.append({"cohort": c, "cohort_size": size, "months_since_live": k, "active_share": val})
    return pd.DataFrame(rows)


def growth_bridge(mm: pd.DataFrame) -> pd.DataFrame:
    p = mm.pivot_table(index=["merchant_key", "segment"], columns="fiscal_year", values="gmv", aggfunc="sum",
                       fill_value=0).reset_index()
    p["type"] = np.select([(p[2025] == 0) & (p[2026] > 0), (p[2025] > 0) & (p[2026] == 0), p[2026] >= p[2025]],
                          ["New merchants", "Churned merchants", "Expansion"], default="Contraction")
    p["delta"] = p[2026] - p[2025]
    b = p.groupby(["segment", "type"]).agg(merchants=("merchant_key", "count"), gmv_change=("delta", "sum")).reset_index()
    return b


def gateway_incidents(cfg, gd: pd.DataFrame, cm: pd.DataFrame, dm: pd.DataFrame):
    an = cfg["analysis"]
    g = gd.groupby(["gateway", "payment_method", "date_key"], as_index=False)[["success_count", "failed_count", "gmv_usd"]].sum()
    g["attempts"] = g["success_count"] + g["failed_count"]
    g["sr"] = g["success_count"] / g["attempts"]
    g = g.sort_values(["gateway", "payment_method", "date_key"]).reset_index(drop=True)
    w = an["baseline_window_days"]
    grp = g.groupby(["gateway", "payment_method"])["sr"]
    g["baseline_sr"] = grp.transform(lambda s: s.shift(1).rolling(w, min_periods=14).median())
    g["baseline_mad"] = grp.transform(lambda s: (s.shift(1) - s.shift(1).rolling(w, min_periods=14).median()).abs()
                                      .rolling(w, min_periods=14).median())
    g["robust_z"] = 0.6745 * (g["sr"] - g["baseline_sr"]) / g["baseline_mad"].replace(0, np.nan)
    g["is_anomaly"] = (g["robust_z"] <= -an["anomaly_mad_threshold"]) & (g["attempts"] >= an["anomaly_min_attempts"])
    # group consecutive anomalous days into incidents (<=2-day gaps bridged)
    events = []
    for (gw, pm), x in g[g["is_anomaly"]].groupby(["gateway", "payment_method"]):
        dates = pd.to_datetime(x["date_key"].astype(str))
        ep = (dates.diff().dt.days.fillna(99) > 3).cumsum()
        for _, e in x.groupby(ep.values):
            base_sr = e["baseline_sr"].mean()
            excess_failed = float((e["attempts"] * e["baseline_sr"] - e["success_count"]).clip(lower=0).sum())
            aov = e["gmv_usd"].sum() / max(e["success_count"].sum(), 1)
            lost_gmv = excess_failed * aov * (1 - an["retry_recovery_rate"])
            tr = dm[(dm["dimension_name"] == "gateway") & (dm["dimension_value"] == gw)]
            take = tr["revenue"].sum() / tr["gmv"].sum()
            events.append({"gateway": gw, "payment_method": pm, "start": str(e["date_key"].min()),
                           "end": str(e["date_key"].max()), "anomalous_days": len(e),
                           "avg_success_rate": round(float(e["success_count"].sum() / e["attempts"].sum()), 4),
                           "baseline_success_rate": round(float(base_sr), 4),
                           "excess_failed_txn": round(excess_failed), "est_lost_gmv_usd": round(lost_gmv),
                           "est_lost_revenue_usd": round(lost_gmv * take)})
    ev = pd.DataFrame(events).sort_values("excess_failed_txn", ascending=False) if events else pd.DataFrame()
    if len(ev):   # sustained incidents (>= 2 anomalous days) vs one-day blips
        ev["event_type"] = np.where(ev["anomalous_days"] >= 2, "Incident", "One-day blip")
    return g, ev


def gateway_degradation(cfg, g: pd.DataFrame) -> pd.DataFrame:
    x = g.assign(month=g["date_key"] // 100).groupby(["gateway", "payment_method", "month"], as_index=False)[
        ["success_count", "attempts"]].sum()
    x["sr"] = x["success_count"] / x["attempts"]
    out = []
    for (gw, pm), s in x.groupby(["gateway", "payment_method"]):
        s = s.sort_values("month").tail(6)
        if s["attempts"].sum() < 20000:
            continue
        slope = np.polyfit(np.arange(len(s)), s["sr"] * 100, 1)[0]
        out.append({"gateway": gw, "payment_method": pm, "slope_pp_per_month": round(slope, 2),
                    "sr_6m_ago_pct": round(100 * s["sr"].iloc[0], 2), "sr_latest_pct": round(100 * s["sr"].iloc[-1], 2),
                    "flag_degrading": slope <= cfg["analysis"]["degradation_slope_pp_per_month"]})
    return pd.DataFrame(out).sort_values("slope_pp_per_month")


def concentration(mm: pd.DataFrame) -> dict:
    fy = mm[mm["fiscal_year"] == 2026].groupby("merchant_key")[["gmv", "gp"]].sum()
    out = {}
    for col in ("gmv", "gp"):
        s = fy[col].sort_values(ascending=False)
        pos = s.clip(lower=0)
        share = pos / pos.sum()
        n10 = max(1, int(round(len(s) * 0.10)))
        out[col] = {"merchants": int(len(s)), "top10_share_pct": round(100 * share.head(10).sum(), 1),
                    "top10pct_share_pct": round(100 * share.head(n10).sum(), 1),
                    "hhi": round(float((share ** 2).sum() * 10000), 0)}
    return out


def profitability(cfg, mm: pd.DataFrame, health: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    fy = mm[mm["fiscal_year"] == 2026].groupby("merchant_key").agg(
        gmv=("gmv", "sum"), revenue=("revenue", "sum"), expected_revenue=("expected_revenue", "sum"),
        cogs=("cogs", "sum"), gp=("gp", "sum"), failed_cost=("cost_of_failed_attempts", "sum"))
    neg = fy[(fy["gp"] < 0) & (fy["revenue"] > 1000)].copy()
    neg["leakage"] = neg["expected_revenue"] - neg["revenue"]
    neg["gp_if_billed_correctly"] = neg["gp"] + neg["leakage"]
    neg["root_cause"] = np.where(neg["gp_if_billed_correctly"] > 0, "Billing leakage (under-billed vs contract)",
                                 "Contract priced below processing cost")
    neg = neg.join(health.set_index("merchant_key")[["mid", "merchant_name", "segment", "country_code", "account_manager"]])
    # what-if: reprice below-cost contracts to a 15% GP margin on the same volume
    below = neg[neg["root_cause"].str.startswith("Contract")]
    uplift = float((below["cogs"] / 0.85 - below["revenue"]).sum())
    summary = {"negative_gp_merchants": int(len(neg)), "negative_gp_total_usd": round(float(neg["gp"].sum()), 0),
               "negative_gp_gmv_musd": round(float(neg["gmv"].sum()) / 1e6, 1),
               "below_cost_contracts": int(len(below)), "billing_leakage_driven": int(len(neg) - len(below)),
               "repricing_uplift_usd": round(uplift, 0)}
    return neg.reset_index().sort_values("gp"), summary


def activation(merchants: pd.DataFrame) -> pd.DataFrame:
    m = merchants[(merchants["signup_date"] >= "2024-07-01") & (merchants["signup_date"] <= "2026-03-31")]
    return m.groupby("integration_type").agg(
        signed=("merchant_key", "count"),
        live_pct=("live_date", lambda s: round(100 * s.notna().mean(), 1)),
        activated_pct=("is_activated", lambda s: round(100 * s.mean(), 1)),
        never_transacted_after_live_pct=("lifecycle_status", lambda s: round(100 * (s == "Live - never transacted").mean(), 1)),
        median_days_signup_to_live=("days_signup_to_live", "median"),
        median_days_live_to_first_txn=("days_live_to_first_txn", "median")).reset_index()


def main() -> None:
    cfg = load_config()
    p = cfg["paths"]["processed"]
    mm = read_csv_checked(p / "kpi_merchant_month.csv")
    dm = read_csv_checked(p / "kpi_dimension_month.csv")
    cm = read_csv_checked(p / "kpi_company_month.csv")
    merchants = read_csv_checked(p / "dim_merchant.csv")
    gd = read_csv_checked(p / "fact_gateway_daily.csv")
    out = cfg["paths"]["reports"] / "analysis"
    out.mkdir(parents=True, exist_ok=True)

    health = merchant_health(cfg, mm, merchants)
    cohorts = cohort_retention(mm, merchants)
    bridge = growth_bridge(mm)
    gdaily, incidents = gateway_incidents(cfg, gd, cm, dm)
    degr = gateway_degradation(cfg, gdaily)
    conc = concentration(mm)
    neg, prof = profitability(cfg, mm, health)
    act = activation(merchants)
    for name, df in {"merchant_health": health, "cohort_retention": cohorts, "growth_bridge_segment": bridge,
                     "gateway_daily_sr": gdaily, "gateway_incidents": incidents, "gateway_degradation": degr,
                     "negative_gp_merchants": neg, "activation_by_integration": act}.items():
        df.to_csv(out / f"{name}.csv", index=False)
        log.info("wrote %-26s %6d rows", name, len(df))

    fy = cm.groupby("fiscal_year").agg(gmv=("gmv", "sum"), revenue=("revenue", "sum"), gp=("gp", "sum"),
                                       success=("success_txn", "sum"), failed=("failed_txn", "sum"),
                                       leakage=("billing_leakage", "sum"), failed_cost=("cost_of_failed_attempts", "sum"))
    hs = health["health_status"].value_counts().to_dict()
    lk = health[health["flag_billing_leakage"] == 1]
    results = {
        "gmv_fy25": round(fy.loc[2025, "gmv"]), "gmv_fy26": round(fy.loc[2026, "gmv"]),
        "revenue_fy25": round(fy.loc[2025, "revenue"]), "revenue_fy26": round(fy.loc[2026, "revenue"]),
        "gp_fy25": round(fy.loc[2025, "gp"]), "gp_fy26": round(fy.loc[2026, "gp"]),
        "gmv_growth_pct": round(100 * (fy.loc[2026, "gmv"] / fy.loc[2025, "gmv"] - 1), 1),
        "revenue_growth_pct": round(100 * (fy.loc[2026, "revenue"] / fy.loc[2025, "revenue"] - 1), 1),
        "gp_growth_pct": round(100 * (fy.loc[2026, "gp"] / fy.loc[2025, "gp"] - 1), 1),
        "gp_margin_fy26_pct": round(100 * fy.loc[2026, "gp"] / fy.loc[2026, "revenue"], 1),
        "take_rate_fy26_pct": round(100 * fy.loc[2026, "revenue"] / fy.loc[2026, "gmv"], 3),
        "success_rate_fy25_pct": round(100 * fy.loc[2025, "success"] / (fy.loc[2025, "success"] + fy.loc[2025, "failed"]), 2),
        "success_rate_fy26_pct": round(100 * fy.loc[2026, "success"] / (fy.loc[2026, "success"] + fy.loc[2026, "failed"]), 2),
        "failed_attempt_cost_fy26": round(fy.loc[2026, "failed_cost"]),
        "gmv_yoy_first_month_pct": round(100 * cm["gmv_yoy"].dropna().iloc[0], 1),
        "gmv_yoy_last_month_pct": round(100 * cm["gmv_yoy"].dropna().iloc[-1], 1),
        "active_merchants_first_month": int(cm["active_merchants"].iloc[0]),
        "active_merchants_last_month": int(cm["active_merchants"].iloc[-1]),
        "health_status_counts": {k: int(v) for k, v in hs.items()},
        "declining_gmv_change_usd": round(float((health.loc[health["health_status"] == "Declining", "gmv_last_3m"]
                                                 - health.loc[health["health_status"] == "Declining", "gmv_prior_3m"]).sum())),
        "alerts": {c: int(health[c].sum()) for c in health.columns if c.startswith("flag_")},
        "billing_leakage_fy26_usd": round(float(lk["leakage_fy26"].sum())),
        "billing_leakage_total_usd": round(float(fy["leakage"].sum())),
        "billing_leakage_merchants": int(len(lk)),
        "concentration": conc,
        "profitability": prof,
        "incidents": incidents[incidents["event_type"] == "Incident"].to_dict("records"),
        "one_day_blips": int((incidents["event_type"] == "One-day blip").sum()),
        "degradation": degr[degr["flag_degrading"]].to_dict("records"),
        "growth_bridge_total": bridge.groupby("type")["gmv_change"].sum().round(0).to_dict(),
    }
    (cfg["paths"]["reports"] / "analysis_results.json").write_text(json.dumps(results, indent=2, default=float))
    log.info("health: %s", hs)
    log.info("incidents: %d (+%d blips) | degrading gateway-methods: %d | negative GP merchants: %d | leakage FY26 $%.0f",
             len(results["incidents"]), results["one_day_blips"], int(degr["flag_degrading"].sum()), prof["negative_gp_merchants"], results["billing_leakage_fy26_usd"])


if __name__ == "__main__":
    main()
