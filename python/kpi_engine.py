"""KPI engine: one consistent pandas implementation of every payments KPI.

Outputs (data/processed/, also loaded into SQLite):
    kpi_merchant_month    merchant x month: GMV, net GMV, revenue, COGS, GP, margin, take rate,
                          AOV, success / failure / refund rate, active / new / first-txn flags,
                          MoM growth, months since live, billing leakage
    kpi_dimension_month   country / segment / vertical / method / gateway x month (long format)
    kpi_company_month     company KPIs incl. active, new-live and activated merchants, MoM / YoY

reconcile_with_sql() compares the pandas results with vw_merchant_month and
vw_company_month and stops the pipeline on any difference.

Run:  python python/kpi_engine.py
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from utils import get_logger, load_config, read_csv_checked, safe_div

log = get_logger("kpi_engine")


def fy_of_month(month_key: pd.Series, start_month: int) -> pd.Series:
    y, m = month_key // 100, month_key % 100
    return np.where(m >= start_month, y + 1, y)


def merchant_month(cfg, f: pd.DataFrame, merchants: pd.DataFrame) -> pd.DataFrame:
    s = f["status"]
    f = f.assign(success_txn=np.where(s == "Success", f["txn_count"], 0),
                 failed_txn=np.where(s == "Failed", f["txn_count"], 0),
                 refunded_txn=np.where(s == "Refunded", f["txn_count"], 0),
                 voided_txn=np.where(s == "Voided", f["txn_count"], 0),
                 failed_cost=np.where(s.isin(["Failed", "Voided"]), f["cost_usd"], 0.0))
    g = f.groupby(["merchant_key", "month_key"], as_index=False).agg(
        gmv=("gmv_usd", "sum"), refunds=("refund_usd", "sum"), success_txn=("success_txn", "sum"),
        failed_txn=("failed_txn", "sum"), refunded_txn=("refunded_txn", "sum"), voided_txn=("voided_txn", "sum"),
        revenue=("revenue_usd", "sum"), expected_revenue=("expected_revenue_usd", "sum"), cogs=("cost_usd", "sum"),
        cost_of_failed_attempts=("failed_cost", "sum"), gp=("gp_usd", "sum"))
    m = merchants.set_index("merchant_key")
    for c in ("mid", "merchant_name", "country_code", "segment", "vertical", "service", "integration_type",
              "account_manager"):
        g[c] = g["merchant_key"].map(m[c])
    g["fiscal_year"] = fy_of_month(g["month_key"], cfg["project"]["fiscal_year_start_month"])
    g["date_key"] = g["month_key"] * 100 + 1
    g["net_gmv"] = g["gmv"] - g["refunds"]
    g["billing_leakage"] = g["expected_revenue"] - g["revenue"]
    g["gp_margin"] = safe_div(g["gp"], g["revenue"])
    g["take_rate"] = safe_div(g["revenue"], g["gmv"])
    g["aov"] = safe_div(g["gmv"], g["success_txn"])
    g["success_rate"] = safe_div(g["success_txn"], g["success_txn"] + g["failed_txn"])
    g["refund_rate"] = safe_div(g["refunds"], g["gmv"])
    g["is_active"] = (g["success_txn"] > 0).astype(int)
    live = pd.to_datetime(g["merchant_key"].map(m["live_date"]))
    first = pd.to_datetime(g["merchant_key"].map(m["first_txn_date"]))
    g["is_live_month"] = (live.dt.strftime("%Y%m").astype(float) == g["month_key"]).astype(int)
    g["is_first_txn_month"] = (first.dt.strftime("%Y%m").astype(float) == g["month_key"]).astype(int)
    g["months_since_live"] = (g["month_key"] // 100 * 12 + g["month_key"] % 100) - (live.dt.year * 12 + live.dt.month)
    g = g.sort_values(["merchant_key", "month_key"]).reset_index(drop=True)
    g["prev_month_gmv"] = g.groupby("merchant_key")["gmv"].shift(1)
    g["gmv_mom"] = safe_div(g["gmv"] - g["prev_month_gmv"], g["prev_month_gmv"])
    g["gmv_rank_in_month"] = g.groupby("month_key")["gmv"].rank(method="min", ascending=False)
    return g


def dimension_month(mm: pd.DataFrame, f: pd.DataFrame, merchants: pd.DataFrame) -> pd.DataFrame:
    """Long-format KPIs by country / segment / vertical (merchant attributes) and method / gateway (fact attributes)."""
    frames = []
    for dim in ("country_code", "segment", "vertical"):
        a = mm.groupby([dim, "month_key", "fiscal_year"], as_index=False).agg(
            gmv=("gmv", "sum"), refunds=("refunds", "sum"), revenue=("revenue", "sum"), cogs=("cogs", "sum"),
            gp=("gp", "sum"), success_txn=("success_txn", "sum"), failed_txn=("failed_txn", "sum"),
            active_merchants=("is_active", "sum"))
        frames.append(a.rename(columns={dim: "dimension_value"}).assign(dimension_name=dim.replace("_code", "")))
    s = f["status"]
    f = f.assign(success_txn=np.where(s == "Success", f["txn_count"], 0), failed_txn=np.where(s == "Failed", f["txn_count"], 0))
    for dim, name in (("payment_method", "method"), ("gateway", "gateway")):
        a = f.groupby([dim, "month_key"], as_index=False).agg(
            gmv=("gmv_usd", "sum"), refunds=("refund_usd", "sum"), revenue=("revenue_usd", "sum"), cogs=("cost_usd", "sum"),
            gp=("gp_usd", "sum"), success_txn=("success_txn", "sum"), failed_txn=("failed_txn", "sum"))
        act = f[f["success_txn"] > 0].groupby([dim, "month_key"])["merchant_key"].nunique().rename("active_merchants")
        a = a.merge(act, on=[dim, "month_key"], how="left")
        a["fiscal_year"] = fy_of_month(a["month_key"], 7)
        frames.append(a.rename(columns={dim: "dimension_value"}).assign(dimension_name=name))
    d = pd.concat(frames, ignore_index=True).sort_values(["dimension_name", "dimension_value", "month_key"])
    d["date_key"] = d["month_key"] * 100 + 1
    d["gp_margin"] = safe_div(d["gp"], d["revenue"])
    d["take_rate"] = safe_div(d["revenue"], d["gmv"])
    d["success_rate"] = safe_div(d["success_txn"], d["success_txn"] + d["failed_txn"])
    prev12 = d.groupby(["dimension_name", "dimension_value"])["gmv"].shift(12)
    d["gmv_yoy"] = safe_div(d["gmv"] - prev12, prev12)
    d["gmv_rank"] = d.groupby(["dimension_name", "month_key"])["gmv"].rank(method="min", ascending=False)
    return d.reset_index(drop=True)


def company_month(mm: pd.DataFrame, merchants: pd.DataFrame) -> pd.DataFrame:
    c = mm.groupby(["month_key", "fiscal_year"], as_index=False).agg(
        gmv=("gmv", "sum"), net_gmv=("net_gmv", "sum"), refunds=("refunds", "sum"), revenue=("revenue", "sum"),
        cogs=("cogs", "sum"), gp=("gp", "sum"), success_txn=("success_txn", "sum"), failed_txn=("failed_txn", "sum"),
        active_merchants=("is_active", "sum"), newly_transacting_merchants=("is_first_txn_month", "sum"),
        billing_leakage=("billing_leakage", "sum"), cost_of_failed_attempts=("cost_of_failed_attempts", "sum"))
    live = pd.to_datetime(merchants["live_date"])
    nl = merchants.assign(month_key=live.dt.strftime("%Y%m").astype(float)).groupby("month_key").agg(
        new_live_merchants=("merchant_key", "count"), activated_merchants=("is_activated", "sum"))
    c = c.merge(nl, left_on="month_key", right_index=True, how="left").fillna({"new_live_merchants": 0, "activated_merchants": 0})
    c["date_key"] = c["month_key"] * 100 + 1
    c["gp_margin"] = safe_div(c["gp"], c["revenue"])
    c["take_rate"] = safe_div(c["revenue"], c["gmv"])
    c["aov"] = safe_div(c["gmv"], c["success_txn"])
    c["success_rate"] = safe_div(c["success_txn"], c["success_txn"] + c["failed_txn"])
    c["failure_rate"] = 1 - c["success_rate"]
    c["refund_rate"] = safe_div(c["refunds"], c["gmv"])
    for col in ("gmv", "revenue", "gp", "active_merchants"):
        c[f"{col}_mom"] = safe_div(c[col] - c[col].shift(1), c[col].shift(1))
        c[f"{col}_yoy"] = safe_div(c[col] - c[col].shift(12), c[col].shift(12))
    c["gmv_3m_avg"] = c["gmv"].rolling(3, min_periods=1).mean()
    c["fytd_gmv"] = c.groupby("fiscal_year")["gmv"].cumsum()
    return c


def reconcile_with_sql(cfg, mm: pd.DataFrame, cm: pd.DataFrame) -> pd.DataFrame:
    con = sqlite3.connect(cfg["paths"]["database"])
    try:
        s = pd.read_sql("SELECT merchant_key, month_key, gmv, revenue, gp, success_txn, failed_txn, is_active, "
                        "months_since_live, gmv_rank_in_month FROM vw_merchant_month", con)
        sc = pd.read_sql("SELECT month_key, active_merchants, new_live_merchants, gmv_yoy FROM vw_company_month", con)
    finally:
        con.close()
    m = mm.merge(s, on=["merchant_key", "month_key"], suffixes=("", "_sql"))
    k = cm.merge(sc, on="month_key", suffixes=("", "_sql"))
    checks = {
        "row_count": len(m) == len(mm) == len(s),
        "gmv": np.allclose(m["gmv"], m["gmv_sql"], atol=0.01),
        "revenue": np.allclose(m["revenue"], m["revenue_sql"], atol=0.01),
        "gp": np.allclose(m["gp"], m["gp_sql"], atol=0.01),
        "transactions": bool((m["success_txn"] == m["success_txn_sql"]).all() and (m["failed_txn"] == m["failed_txn_sql"]).all()),
        "active_flag": bool((m["is_active"] == m["is_active_sql"]).all()),
        "months_since_live": bool((m["months_since_live"] == m["months_since_live_sql"]).all()),
        "gmv_rank": bool((m["gmv_rank_in_month"] == m["gmv_rank_in_month_sql"]).all()),
        "company_active_merchants": bool((k["active_merchants"] == k["active_merchants_sql"]).all()),
        "company_new_live": bool((k["new_live_merchants"] == k["new_live_merchants_sql"]).all()),
        "company_gmv_yoy": np.allclose(k["gmv_yoy"].fillna(-9), k["gmv_yoy_sql"].fillna(-9), atol=1e-9),
    }
    out = pd.DataFrame([{"check": c, "passed": bool(v)} for c, v in checks.items()])
    for _, r in out.iterrows():
        (log.info if r.passed else log.error)("reconcile %-26s %s", r.check, "PASS" if r.passed else "FAIL")
    if not out["passed"].all():
        raise ValueError("Python vs SQL reconciliation failed")
    return out


def main() -> None:
    cfg = load_config()
    p = cfg["paths"]["processed"]
    f = read_csv_checked(p / "fact_payments_monthly.csv")
    merchants = read_csv_checked(p / "dim_merchant.csv")
    mm = merchant_month(cfg, f, merchants)
    dm = dimension_month(mm, f, merchants)
    cm = company_month(mm, merchants)
    rec = reconcile_with_sql(cfg, mm, cm)
    con = sqlite3.connect(cfg["paths"]["database"])
    try:
        for name, df in (("kpi_merchant_month", mm), ("kpi_dimension_month", dm), ("kpi_company_month", cm)):
            df.to_csv(p / f"{name}.csv", index=False)
            df.to_sql(name, con, if_exists="replace", index=False)
            log.info("wrote %-20s %7d rows", name, len(df))
    finally:
        con.close()
    rec.to_csv(p / "reconciliation_python_vs_sql.csv", index=False)


if __name__ == "__main__":
    main()
