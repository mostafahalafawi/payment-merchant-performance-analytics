"""Unit + integration tests.

    python -m unittest discover -s tests -v     (or: pytest)

Unit tests run without data. Integration tests run after `python run_pipeline.py`.
"""
import json
import sqlite3
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from kpi_engine import merchant_month  # noqa: E402
from utils import fiscal_year, load_config  # noqa: E402
from validation import TXN_RULES, evaluate  # noqa: E402

CFG = load_config()
PROC, RAW, REP = CFG["paths"]["processed"], CFG["paths"]["raw"], CFG["paths"]["reports"]


class TestUnits(unittest.TestCase):
    def test_fiscal_year_jul_jun(self):
        fy = fiscal_year(pd.to_datetime(["2025-06-30", "2025-07-01", "2026-06-30"]), 7)
        self.assertEqual(list(fy), [2025, 2026, 2026])

    def test_status_and_amount_rules(self):
        df = pd.DataFrame({
            "txn_date": pd.to_datetime(["2025-01-01", None, "2025-01-02", "2025-01-03"]),
            "mid": ["A", "A", "A", "A"], "payment_method": ["CARD"] * 4, "gateway": ["GW-ATLAS"] * 4,
            "status": ["Success", "Success", "PENDING_REVIEW", "Success"],
            "status_std": ["Success", "Success", None, "Success"], "txn_count": [5, 5, 5, 0],
            "amount_local": [100.0, 100.0, 100.0, 50.0], "currency": ["EGP"] * 4,
            "revenue_local": [2.0, 2.0, 0.0, 120.0], "cost_local": [1.0, 1.0, 0.0, 1.0], "gp_local": [1.0, 1.0, 0.0, 119.0]})
        ctx = {"start": pd.Timestamp("2024-07-01"), "end": pd.Timestamp("2026-06-30"), "mids": {"A"},
               "methods": {"CARD"}, "gateways": {"GW-ATLAS"}, "mid_currency": pd.Series({"A": "EGP"}),
               "dup_cols": ["txn_date", "mid", "status", "amount_local"]}
        flags, _ = evaluate(df, TXN_RULES, ctx)
        self.assertTrue(flags.loc[1, "DQ-T02"])             # invalid date
        self.assertTrue(flags.loc[2, "DQ-T05"])             # impossible status
        self.assertTrue(flags.loc[3, "DQ-T08"])             # zero count with amount
        self.assertTrue(flags.loc[3, "DQ-T09"])             # revenue > GMV
        self.assertFalse(flags.loc[0].any())                # clean row passes every rule

    def test_success_rate_and_take_rate(self):
        f = pd.DataFrame({"merchant_key": [1] * 3, "month_key": [202507] * 3, "status": ["Success", "Failed", "Refunded"],
                          "txn_count": [90, 10, 2], "gmv_usd": [9000.0, 0, 0], "refund_usd": [0, 0, 200.0],
                          "revenue_usd": [180.0, 0, 0], "expected_revenue_usd": [200.0, 0, 0],
                          "cost_usd": [120.0, 0.2, 0.3], "gp_usd": [60.0, -0.2, -0.3]})
        m = pd.DataFrame({"merchant_key": [1], "mid": ["X"], "merchant_name": ["X"], "country_code": ["EG"],
                          "segment": ["SME"], "vertical": ["Retail"], "service": ["POS Acceptance"],
                          "integration_type": ["POS Terminal"], "account_manager": ["A"],
                          "live_date": ["2025-05-10"], "first_txn_date": ["2025-05-12"]})
        r = merchant_month(CFG, f, m).iloc[0]
        self.assertAlmostEqual(r["success_rate"], 0.90)
        self.assertAlmostEqual(r["take_rate"], 0.02)
        self.assertAlmostEqual(r["net_gmv"], 8800.0)
        self.assertAlmostEqual(r["billing_leakage"], 20.0)
        self.assertEqual(r["months_since_live"], 2)


@unittest.skipUnless((PROC / "kpi_merchant_month.csv").exists(), "run the pipeline first")
class TestOutputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dq = pd.read_csv(PROC / "dq_rule_log.csv").set_index("rule_id")
        cls.man = json.loads((RAW / "_defect_manifest.json").read_text())

    def test_injected_defects_detected(self):
        pairs = {"DQ-T01": "duplicate_rows", "DQ-T02": "bad_dates", "DQ-T04": "unknown_mid", "DQ-T05": "unknown_status",
                 "DQ-T07": "negative_amount", "DQ-T08": "zero_count_with_amount", "DQ-T09": "revenue_gt_gmv",
                 "DQ-T12": "gp_inconsistent", "DQ-M01": "duplicate_mid_merchants", "DQ-M02": "missing_country",
                 "DQ-M03": "missing_vertical", "DQ-M04": "live_before_signup"}
        for rule, key in pairs.items():
            self.assertGreaterEqual(self.dq.loc[rule, "rows_affected"], self.man[key], msg=rule)

    def test_underbilled_merchants_found(self):
        leak = pd.read_csv(REP / "sql_results" / "q16_billing_leakage.csv")
        dim = pd.read_csv(PROC / "dim_merchant.csv").set_index("merchant_id")
        injected = {dim.loc[m, "mid"] for m in self.man["underbilled_merchants"] if m in dim.index}
        # every injected merchant that had volume after the misconfiguration date must be detected
        self.assertGreaterEqual(len(set(leak["mid"]) & injected), len(injected) - 2)
        self.assertTrue(set(leak["mid"]) <= injected, "false positives in billing leakage")

    def test_incident_detected(self):
        inc = pd.read_csv(REP / "analysis" / "gateway_incidents.csv")
        top = inc[inc["event_type"] == "Incident"].iloc[0]
        self.assertEqual(top["gateway"], "GW-ORION")
        self.assertTrue(20251010 <= top["start"] <= 20251015)

    def test_integrity_and_sql(self):
        self.assertTrue(pd.read_csv(PROC / "dq_integrity_checks.csv")["passed"].all())
        con = sqlite3.connect(CFG["paths"]["database"])
        try:
            dq = pd.read_sql("SELECT * FROM vw_dq_assertions", con)
        finally:
            con.close()
        self.assertTrue((dq["failing_rows"] == 0).all())

    def test_python_sql_reconciliation(self):
        self.assertTrue(pd.read_csv(PROC / "reconciliation_python_vs_sql.csv")["passed"].all())

    def test_kpi_ties_to_fact(self):
        f = pd.read_csv(PROC / "fact_payments_monthly.csv")
        k = pd.read_csv(PROC / "kpi_company_month.csv")
        self.assertTrue(np.isclose(f["gmv_usd"].sum(), k["gmv"].sum()))
        self.assertTrue(np.isclose(f["gp_usd"].sum(), k["gp"].sum()))


if __name__ == "__main__":
    unittest.main()
