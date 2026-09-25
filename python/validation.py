"""Data-quality rules for the payments pipeline.

Rules are declarative (ID, table, severity, action) and return a boolean mask.
The ETL applies the actions:  FIX -> repaired and logged | DROP -> removed |
QUARANTINE -> held out in data/processed/quarantine_*.csv | FLAG -> kept, reported.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from utils import get_logger

log = get_logger("validation")


@dataclass(frozen=True)
class Rule:
    rule_id: str
    table: str
    description: str
    severity: str
    action: str
    check: Callable[[pd.DataFrame, dict], pd.Series]


TXN_RULES: list[Rule] = [
    Rule("DQ-T01", "transactions", "Exact duplicate row (double export)", "HIGH", "DROP",
         lambda df, c: df.duplicated(subset=c["dup_cols"], keep="first")),
    Rule("DQ-T02", "transactions", "Transaction date missing or invalid (e.g. 2025-13-01, 31/02/2025)", "CRITICAL", "QUARANTINE",
         lambda df, c: df["txn_date"].isna()),
    Rule("DQ-T03", "transactions", "Transaction date outside the reporting window", "HIGH", "QUARANTINE",
         lambda df, c: df["txn_date"].notna() & ((df["txn_date"] < c["start"]) | (df["txn_date"] > c["end"]))),
    Rule("DQ-T04", "transactions", "MID not found in merchant master", "HIGH", "QUARANTINE",
         lambda df, c: ~df["mid"].isin(c["mids"])),
    Rule("DQ-T05", "transactions", "Impossible / unknown payment status (e.g. PENDING_REVIEW)", "HIGH", "QUARANTINE",
         lambda df, c: df["status_std"].isna()),
    Rule("DQ-T06", "transactions", "Unknown payment method or gateway", "HIGH", "QUARANTINE",
         lambda df, c: ~df["payment_method"].isin(c["methods"]) | ~df["gateway"].isin(c["gateways"])),
    Rule("DQ-T07", "transactions", "Negative amount / revenue / cost", "HIGH", "QUARANTINE",
         lambda df, c: (df["amount_local"] < 0) | (df["revenue_local"] < 0) | (df["cost_local"] < 0)),
    Rule("DQ-T08", "transactions", "Zero or negative transaction count with a non-zero amount", "HIGH", "QUARANTINE",
         lambda df, c: (df["txn_count"] <= 0) & (df["amount_local"] != 0)),
    Rule("DQ-T09", "transactions", "Revenue greater than GMV (impossible for a successful payment)", "HIGH", "QUARANTINE",
         lambda df, c: (df["status_std"] == "Success") & (df["amount_local"] > 0) & (df["revenue_local"] > df["amount_local"])),
    Rule("DQ-T10", "transactions", "Revenue booked on a failed / voided / refunded row", "MEDIUM", "QUARANTINE",
         lambda df, c: df["status_std"].isin(["Failed", "Voided", "Refunded"]) & (df["revenue_local"] > 0)),
    Rule("DQ-T11", "transactions", "Currency does not match the merchant's country", "MEDIUM", "QUARANTINE",
         lambda df, c: df["mid"].isin(c["mids"]) & (df["currency"] != df["mid"].map(c["mid_currency"]))),
    Rule("DQ-T12", "transactions", "GP inconsistent with revenue - cost (recomputed)", "MEDIUM", "FIX",
         lambda df, c: (df["gp_local"] - (df["revenue_local"] - df["cost_local"])).abs() > 0.05),
]

MERCHANT_RULES: list[Rule] = [
    Rule("DQ-M01", "merchants", "Duplicate MID: several merchant records share one MID (merged to earliest record)", "HIGH", "FIX",
         lambda df, c: df.sort_values("signup_date").duplicated("mid", keep="first").reindex(df.index)),
    Rule("DQ-M02", "merchants", "Missing country (imputed from account manager's market)", "MEDIUM", "FIX",
         lambda df, c: df["country_code"].isna()),
    Rule("DQ-M03", "merchants", "Missing vertical (set to 'Unclassified')", "LOW", "FIX",
         lambda df, c: df["vertical"].isna()),
    Rule("DQ-M04", "merchants", "Go-live date before signup date (signup reset to go-live)", "MEDIUM", "FIX",
         lambda df, c: df["live_date"].notna() & (df["live_date"] < df["signup_date"])),
    Rule("DQ-M05", "merchants", "Missing merchant ID or MID", "CRITICAL", "QUARANTINE",
         lambda df, c: df["merchant_id"].isna() | df["mid"].isna()),
]


def evaluate(df: pd.DataFrame, rules: list[Rule], ctx: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    flags, records = pd.DataFrame(index=df.index), []
    for r in rules:
        try:
            mask = r.check(df, ctx).fillna(False).astype(bool)
        except Exception as exc:
            raise RuntimeError(f"Rule {r.rule_id} failed to evaluate: {exc}") from exc
        flags[r.rule_id] = mask
        records.append({"rule_id": r.rule_id, "table": r.table, "description": r.description, "severity": r.severity,
                        "action": r.action, "rows_affected": int(mask.sum()),
                        "pct_of_rows": round(100 * mask.mean(), 4) if len(df) else 0.0})
        if mask.any():
            log.info("%s %-10s %8d rows  %s", r.rule_id, r.action, mask.sum(), r.description)
    return flags, pd.DataFrame(records)


def integrity_checks(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    f, m = t["fact_payments_daily"], t["dim_merchant"]
    succ = f["status"] == "Success"
    checks = [
        ("IC-01", "Every fact row maps to a merchant", f["merchant_key"].isin(m["merchant_key"]).all()),
        ("IC-02", "dim_merchant: one row per MID", m["mid"].is_unique),
        ("IC-03", "No negative amounts / revenue / cost", bool((f[["amount_usd", "revenue_usd", "cost_usd"]] >= 0).all().all())),
        ("IC-04", "GMV only on Success rows", bool((f.loc[~succ, "gmv_usd"] == 0).all())),
        ("IC-05", "Revenue <= GMV on Success rows", bool((f.loc[succ, "revenue_usd"] <= f.loc[succ, "gmv_usd"] + 0.01).all())),
        ("IC-06", "GP = revenue - cost", bool(((f["gp_usd"] - (f["revenue_usd"] - f["cost_usd"])).abs() < 0.01).all())),
        ("IC-07", "No transactions before merchant go-live",
         bool((f["date_key"] >= f["merchant_key"].map(m.set_index("merchant_key")["live_date_key"])).all())),
        ("IC-08", "Unique grain (date, merchant, method, gateway, status)",
         not f.duplicated(["date_key", "merchant_key", "payment_method", "gateway", "status"]).any()),
    ]
    out = pd.DataFrame(checks, columns=["check_id", "description", "passed"])
    for _, r in out.iterrows():
        (log.info if r.passed else log.error)("%s %s  %s", r.check_id, "PASS" if r.passed else "FAIL", r.description)
    return out
