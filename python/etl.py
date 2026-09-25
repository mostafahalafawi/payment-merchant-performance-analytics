"""ETL: raw switch / billing / CRM extracts -> validated star schema (data/processed).

    1. extract       raw CSVs
    2. merchants     de-duplicate MIDs, impute country, fix impossible dates
    3. transactions  standardise status labels & dates, apply DQ rules (drop / quarantine / fix)
    4. conform       FX to USD, merchant keys, contracted (expected) revenue for leakage checks,
                     go-live corrected to first transaction where the CRM date is impossible
    5. model         dimensions + daily and monthly facts + decline reasons
    6. reconcile     raw rows = clean + quarantined + duplicates; integrity checks
    7. load          CSVs + DQ report

Run:  python python/etl.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from utils import ensure_dirs, fiscal_year, get_logger, load_config, read_csv_checked
from validation import MERCHANT_RULES, TXN_RULES, evaluate, integrity_checks

log = get_logger("etl")


def extract(cfg) -> dict[str, pd.DataFrame]:
    raw = cfg["paths"]["raw"]
    names = ["merchants", "merchant_pricing", "gateway_costs", "transactions_daily", "decline_reasons", "fx_rates",
             "account_managers"]
    d = {n: read_csv_checked(raw / f"raw_{n}.csv", dtype={"mid": "string", "txn_date": "string"}) for n in names}
    for k, v in d.items():
        log.info("extracted %-18s %9d rows", k, len(v))
    return d


# ---------------------------------------------------------------------------
def clean_merchants(cfg, d) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    m = d["merchants"].copy()
    m["signup_date"] = pd.to_datetime(m["signup_date"], errors="coerce")
    m["live_date"] = pd.to_datetime(m["live_date"], errors="coerce")
    flags, log_df = evaluate(m, MERCHANT_RULES, {})
    m = m[~flags["DQ-M05"]].copy()

    # DQ-M01: duplicate MIDs -> keep earliest record, keep a mapping for audit
    m = m.sort_values(["signup_date", "merchant_id"])
    dup = m[m.duplicated("mid", keep="first")]
    canon = m.drop_duplicates("mid", keep="first").set_index("mid")["merchant_id"]
    dup_map = dup[["merchant_id", "mid", "merchant_name"]].assign(canonical_merchant_id=dup["mid"].map(canon))
    m = m.drop_duplicates("mid", keep="first")

    am_country = d["account_managers"].set_index("account_manager")["country_code"]
    m["country_code"] = m["country_code"].fillna(m["account_manager"].map(am_country))       # DQ-M02
    m["vertical"] = m["vertical"].fillna("Unclassified")                                      # DQ-M03
    bad = m["live_date"].notna() & (m["live_date"] < m["signup_date"])                         # DQ-M04
    m.loc[bad, "signup_date"] = m.loc[bad, "live_date"]
    return m.reset_index(drop=True), log_df, dup_map


def clean_transactions(cfg, d, merchants):
    t = d["transactions_daily"].copy()
    fixes = []
    # status labels -> canonical
    lookup = {lab: std for std, labels in cfg["status_map"].items() for lab in labels}
    t["status_std"] = t["status"].map(lookup)
    fixes.append({"rule_id": "STD-01", "description": "Status label variants mapped to canonical status",
                  "rows_affected": int((t["status_std"].notna() & (t["status"] != t["status_std"])).sum())})
    t["txn_date"] = pd.to_datetime(t["txn_date"], format="%Y-%m-%d", errors="coerce")
    ctx = {
        "start": pd.Timestamp(cfg["project"]["start_date"]), "end": pd.Timestamp(cfg["project"]["end_date"]),
        "mids": set(merchants["mid"]), "methods": set(cfg["payment_methods"]), "gateways": set(cfg["gateways"]),
        "mid_currency": merchants.set_index("mid")["country_code"].map(lambda c: cfg["countries"][c]["currency"]),
        "dup_cols": ["txn_date", "mid", "payment_method", "gateway", "status", "txn_count", "amount_local",
                     "currency", "revenue_local", "cost_local", "gp_local"],
    }
    flags, dq = evaluate(t, TXN_RULES, ctx)
    act = dq.set_index("rule_id")["action"]
    drop = flags["DQ-T01"]
    qcols = [r for r in flags if act[r] == "QUARANTINE"]
    qmask = flags[qcols].any(axis=1) & ~drop
    quarantine = t[qmask].copy()
    quarantine["dq_failed_rules"] = flags.loc[qmask, qcols].apply(lambda r: ";".join(r.index[r.values]), axis=1)
    clean = t[~drop & ~qmask].copy()
    clean["gp_local"] = clean["revenue_local"] - clean["cost_local"]                     # DQ-T12 FIX
    recon = {"raw_rows": len(t), "duplicates_dropped": int(drop.sum()), "quarantined": len(quarantine),
             "clean_rows": len(clean)}
    recon["balanced"] = recon["raw_rows"] == recon["duplicates_dropped"] + recon["quarantined"] + recon["clean_rows"]
    log.info("reconciliation raw=%d = clean %d + quarantine %d + duplicates %d -> %s", recon["raw_rows"],
             recon["clean_rows"], recon["quarantined"], recon["duplicates_dropped"], "OK" if recon["balanced"] else "MISMATCH")
    if not recon["balanced"]:
        raise ValueError("Row reconciliation failed")
    fx = pd.DataFrame(fixes)
    fx[["table", "severity", "action"]] = ["transactions", "LOW", "FIX"]
    return clean, quarantine, pd.concat([fx, dq], ignore_index=True), recon


# ---------------------------------------------------------------------------
def conform(cfg, d, clean, merchants):
    fx = d["fx_rates"].set_index(["fx_month", "currency"])["rate_per_usd"]
    rate = fx.reindex(pd.MultiIndex.from_arrays([clean["txn_date"].dt.strftime("%Y-%m"), clean["currency"]])).to_numpy()
    f = pd.DataFrame({"txn_date": clean["txn_date"], "mid": clean["mid"], "payment_method": clean["payment_method"],
                      "gateway": clean["gateway"], "status": clean["status_std"], "txn_count": clean["txn_count"].astype(int),
                      "currency": clean["currency"], "amount_local": clean["amount_local"], "fx_rate": rate})
    for c in ("amount", "revenue", "cost"):
        f[f"{c}_usd"] = (clean[f"{c}_local"].to_numpy() / rate).round(4)
    f["gp_usd"] = f["revenue_usd"] - f["cost_usd"]
    succ = f["status"] == "Success"
    f["gmv_usd"] = np.where(succ, f["amount_usd"], 0.0)
    f["refund_usd"] = np.where(f["status"] == "Refunded", f["amount_usd"], 0.0)
    # contracted pricing -> expected revenue (billing leakage check)
    pr = d["merchant_pricing"].merge(merchants[["merchant_id", "mid"]], on="merchant_id")
    pr = pr.set_index(["mid", "payment_method"])
    key = pd.MultiIndex.from_arrays([f["mid"], f["payment_method"]])
    mdr, fee = pr["mdr_pct"].reindex(key).to_numpy(), pr["fixed_fee_usd"].reindex(key).to_numpy()
    f["expected_revenue_usd"] = np.where(succ, f["gmv_usd"] * mdr + f["txn_count"] * fee, 0.0).round(4)
    f["expected_revenue_usd"] = f["expected_revenue_usd"].fillna(f["revenue_usd"])
    return f


def build_model(cfg, d, f, merchants, dup_map):
    start, end = pd.Timestamp(cfg["project"]["start_date"]), pd.Timestamp(cfg["project"]["end_date"])
    fy_m = cfg["project"]["fiscal_year_start_month"]

    # merchants: go-live corrected where the switch shows earlier activity (DQ-M06 FIX)
    first_txn = f[f["status"] == "Success"].groupby("mid")["txn_date"].min()
    first_any = f.groupby("mid")["txn_date"].min()
    m = merchants.copy()
    m["first_txn_date"] = m["mid"].map(first_txn)
    early = m["mid"].map(first_any)
    fix = early.notna() & (m["live_date"].isna() | (early < m["live_date"]))
    m["live_date_corrected"] = fix.astype(int)
    m.loc[fix, "live_date"] = early[fix]
    # lifecycle attributes as of the period end
    lc = cfg["lifecycle"]
    last_txn = f[f["status"] == "Success"].groupby("mid")["txn_date"].max()
    m["last_txn_date"] = m["mid"].map(last_txn)
    days_since = (end - m["last_txn_date"]).dt.days
    days_to_first = (m["first_txn_date"] - m["live_date"]).dt.days
    m["days_signup_to_live"] = (m["live_date"] - m["signup_date"]).dt.days
    m["days_live_to_first_txn"] = days_to_first
    m["is_activated"] = (days_to_first.notna() & (days_to_first <= lc["activation_window_days"])).astype(int)
    m["lifecycle_status"] = np.select(
        [m["live_date"].isna(), m["first_txn_date"].isna(), days_since > lc["churned_after_days"],
         days_since > lc["dormant_after_days"]],
        ["Onboarding (not live)", "Live - never transacted", "Churned", "Dormant"], default="Active")
    m["signup_cohort"] = m["signup_date"].dt.strftime("%Y-%m")
    m["live_cohort"] = m["live_date"].dt.strftime("%Y-%m")
    m["live_fy"] = np.where(m["live_date"].notna(), fiscal_year(m["live_date"].fillna(start), fy_m), np.nan)
    m["is_new_in_period"] = (m["live_date"] >= start).astype(int)
    m.insert(0, "merchant_key", range(1, len(m) + 1))
    for c in ("signup_date", "live_date", "first_txn_date", "last_txn_date"):
        m[f"{c.replace('_date', '')}_date_key"] = m[c].dt.strftime("%Y%m%d").astype(float).astype("Int64")
    m = m.rename(columns={"live_date_key": "live_date_key"})
    dim_merchant = m

    key = dim_merchant.set_index("mid")["merchant_key"]
    f = f.copy()
    f["merchant_key"] = f["mid"].map(key)
    f["date_key"] = f["txn_date"].dt.strftime("%Y%m%d").astype(int)
    f["month_key"] = f["txn_date"].dt.strftime("%Y%m").astype(int)
    fact_daily = f[["date_key", "month_key", "merchant_key", "payment_method", "gateway", "status", "txn_count",
                    "amount_usd", "gmv_usd", "refund_usd", "revenue_usd", "expected_revenue_usd", "cost_usd", "gp_usd",
                    "currency", "amount_local"]].sort_values(["date_key", "merchant_key"])
    # after merging duplicate-MID merchants the grain can repeat -> aggregate to the declared grain
    grain = ["date_key", "month_key", "merchant_key", "payment_method", "gateway", "status", "currency"]
    fact_daily = fact_daily.groupby(grain, as_index=False).sum(numeric_only=True)

    fact_monthly = fact_daily.assign(gmv_local=np.where(fact_daily["status"] == "Success", fact_daily["amount_local"], 0.0)) \
        .drop(columns=["date_key", "amount_local"]).groupby(
        ["month_key", "merchant_key", "payment_method", "gateway", "status", "currency"], as_index=False).sum()
    fact_monthly["date_key"] = fact_monthly["month_key"] * 100 + 1

    dec = d["decline_reasons"].copy()
    dec = dec[dec["mid"].isin(key.index)]
    dec["merchant_key"] = dec["mid"].map(key)
    dec["month_key"] = dec["txn_month"].str.replace("-", "").astype(int)
    dec["date_key"] = dec["month_key"] * 100 + 1
    fact_declines = dec.groupby(["month_key", "date_key", "merchant_key", "payment_method", "gateway", "decline_reason"],
                                as_index=False)["failed_count"].sum()

    agg_declines = fact_declines.groupby(["month_key", "date_key", "gateway", "payment_method", "decline_reason"],
                                         as_index=False)["failed_count"].sum()

    # daily gateway-level table for transaction-quality monitoring (small, committed)
    g = fact_daily.copy()
    g["country_code"] = g["merchant_key"].map(dim_merchant.set_index("merchant_key")["country_code"])
    g["success_count"] = np.where(g["status"] == "Success", g["txn_count"], 0)
    g["failed_count"] = np.where(g["status"] == "Failed", g["txn_count"], 0)
    fact_gateway_daily = g.groupby(["date_key", "gateway", "payment_method", "country_code"], as_index=False)[
        ["success_count", "failed_count", "gmv_usd"]].sum()

    dates = pd.date_range(start, end, freq="D")
    dd = pd.DataFrame({"date": dates})
    dd["date_key"] = dd["date"].dt.strftime("%Y%m%d").astype(int)
    dd["month_key"] = dd["date"].dt.strftime("%Y%m").astype(int)
    dd["year_month"] = dd["date"].dt.strftime("%Y-%m")
    dd["year"], dd["month_num"], dd["month_name"] = dd["date"].dt.year, dd["date"].dt.month, dd["date"].dt.strftime("%b")
    dd["fiscal_year"] = fiscal_year(dd["date"], fy_m)
    dd["fiscal_year_label"] = "FY" + dd["fiscal_year"].astype(str)
    dd["fiscal_month_num"] = (dd["month_num"] - fy_m) % 12 + 1
    dd["fiscal_quarter"] = "Q" + (((dd["fiscal_month_num"] - 1) // 3) + 1).astype(str)
    dd["weekday_name"] = dd["date"].dt.day_name()
    dd["is_weekend"] = dd["date"].dt.dayofweek.isin([4, 5]).astype(int)

    pm = pd.DataFrame([{"payment_method": k, "payment_method_name": v["name"], "default_mdr_pct": v["mdr_pct"],
                        "default_cost_pct": v["cost_pct"]} for k, v in cfg["payment_methods"].items()])
    gw = pd.DataFrame([{"gateway": k, "gateway_name": v["name"], "gateway_countries": ",".join(v["countries"]),
                        "auth_fee_usd": v["auth_fee_usd"]} for k, v in cfg["gateways"].items()])
    ctry = pd.DataFrame([{"country_code": k, "country_name": v["name"], "currency": v["currency"], "region": v["region"]}
                         for k, v in cfg["countries"].items()])
    status = pd.DataFrame([("Success", 1, 1, 1), ("Failed", 0, 1, 2), ("Refunded", 0, 0, 3), ("Voided", 0, 0, 4)],
                          columns=["status", "counts_in_gmv", "counts_in_success_rate", "sort_order"])
    pricing = d["merchant_pricing"].merge(dim_merchant[["merchant_id", "merchant_key"]], on="merchant_id")
    return {"dim_date": dd, "dim_merchant": dim_merchant, "dim_payment_method": pm, "dim_gateway": gw,
            "dim_country": ctry, "dim_status": status, "dim_merchant_pricing": pricing,
            "ref_gateway_costs": d["gateway_costs"], "ref_fx_rates": d["fx_rates"],
            "fact_payments_daily": fact_daily, "fact_payments_monthly": fact_monthly,
            "fact_declines_monthly": fact_declines, "agg_declines_gateway_month": agg_declines,
            "fact_gateway_daily": fact_gateway_daily,
            "dq_duplicate_mid_map": dup_map}


def write_dq_report(cfg, dq, recon, integrity, model):
    out = cfg["paths"]["processed"]
    dq.to_csv(out / "dq_rule_log.csv", index=False)
    integrity.to_csv(out / "dq_integrity_checks.csv", index=False)
    r = recon
    f = model["fact_payments_daily"]
    leak = f["expected_revenue_usd"].sum() - f["revenue_usd"].sum()
    corrected = int(model["dim_merchant"]["live_date_corrected"].sum())
    lines = ["# Data Quality Report", "", "_Auto-generated by `python/etl.py` on every run._", "",
             "## Row reconciliation (daily transactions)", "",
             "| Raw rows | Clean rows | Quarantined | Duplicates dropped | Balanced |", "|---:|---:|---:|---:|:---:|",
             f"| {r['raw_rows']:,} | {r['clean_rows']:,} | {r['quarantined']:,} | {r['duplicates_dropped']:,} | "
             f"{'Yes' if r['balanced'] else 'No'} |", "",
             "## Rules", "", "| Rule | Table | Description | Severity | Action | Rows |", "|---|---|---|---|---|---:|"]
    for _, x in dq.iterrows():
        lines.append(f"| {x['rule_id']} | {x['table']} | {x['description']} | {x['severity']} | {x['action']} | {int(x['rows_affected']):,} |")
    lines += [f"| DQ-M06 | merchants | Go-live date later than first transaction (corrected to first transaction) | MEDIUM | FIX | {corrected} |",
              f"| DQ-B01 | billing | Billed revenue below contracted pricing (billing leakage, USD) | HIGH | FLAG | {leak:,.0f} |",
              "", "## Integrity checks", "", "| Check | Description | Result |", "|---|---|:---:|"]
    for _, x in integrity.iterrows():
        lines.append(f"| {x['check_id']} | {x['description']} | {'PASS' if x['passed'] else 'FAIL'} |")
    (out / "dq_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    cfg = load_config()
    ensure_dirs(cfg)
    d = extract(cfg)
    merchants, dq_m, dup_map = clean_merchants(cfg, d)
    clean, quarantine, dq_t, recon = clean_transactions(cfg, d, merchants)
    f = conform(cfg, d, clean, merchants)
    model = build_model(cfg, d, f, merchants, dup_map)
    integrity = integrity_checks(model)
    if not integrity["passed"].all():
        raise ValueError("Integrity checks failed")
    out = cfg["paths"]["processed"]
    for name, df in model.items():
        df.to_csv(out / f"{name}.csv", index=False)
        log.info("loaded %-24s %9d rows", name, len(df))
    quarantine.to_csv(out / "quarantine_transactions.csv", index=False)
    write_dq_report(cfg, pd.concat([dq_m, dq_t], ignore_index=True), recon, integrity, model)
    log.info("ETL complete")


if __name__ == "__main__":
    main()
