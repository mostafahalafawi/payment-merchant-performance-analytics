"""Run the full payments pipeline end to end.

    python run_pipeline.py                  # generate -> ETL -> SQL -> KPIs -> analysis -> visuals -> reports
    python run_pipeline.py --skip-generate  # reuse existing data/raw extracts

Any failed quality gate stops the run.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "python"))

import analysis  # noqa: E402
import database  # noqa: E402
import etl  # noqa: E402
import generate_data  # noqa: E402
import kpi_engine  # noqa: E402
import reporting  # noqa: E402
import visuals  # noqa: E402
from utils import get_logger, load_config, read_csv_checked  # noqa: E402

log = get_logger("pipeline")


def export_samples(cfg) -> None:
    n, raw, proc, out = cfg["reporting"]["sample_rows"], cfg["paths"]["raw"], cfg["paths"]["processed"], cfg["paths"]["sample"]
    read_csv_checked(raw / "raw_transactions_daily.csv", nrows=3000).to_csv(out / "sample_raw_transactions_daily.csv", index=False)
    read_csv_checked(raw / "raw_merchants.csv").head(300).to_csv(out / "sample_raw_merchants.csv", index=False)
    fd = read_csv_checked(proc / "fact_payments_daily.csv")
    fd.sample(n=min(n, len(fd)), random_state=cfg["project"]["seed"]).sort_values("date_key") \
      .to_csv(out / "sample_fact_payments_daily.csv", index=False)
    read_csv_checked(proc / "quarantine_transactions.csv").head(2000).to_csv(out / "sample_quarantine_transactions.csv", index=False)
    log.info("samples written to %s", out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-generate", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    steps = [("generate synthetic raw data", generate_data.main, not args.skip_generate),
             ("ETL + data validation", etl.main, True),
             ("build SQLite model + SQL assertions", lambda: database.build(cfg), True),
             ("run business SQL queries", lambda: database.run_named_queries(cfg), True),
             ("KPI engine + Python/SQL reconciliation", kpi_engine.main, True),
             ("advanced analysis", analysis.main, True),
             ("render visuals", visuals.main, True),
             ("automated reports", reporting.main, True),
             ("export samples", lambda: export_samples(cfg), True)]
    t0 = time.time()
    for i, (name, fn, on) in enumerate(steps, 1):
        if not on:
            log.info("[%d/%d] skipped: %s", i, len(steps), name)
            continue
        log.info("[%d/%d] %s", i, len(steps), name)
        fn()
    log.info("pipeline finished in %.0fs", time.time() - t0)


if __name__ == "__main__":
    main()
