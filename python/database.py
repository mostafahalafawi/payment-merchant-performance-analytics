"""Build the SQLite analytics database and run the SQL layer.

    1. sql/01_schema.sql     tables, keys, checks, indexes
    2. load data/processed   star schema CSVs (chunked for the 2M-row daily fact)
    3. sql/02, 03            data-quality assertions + KPI views
    4. assert vw_dq_assertions all zero
    5. sql/04                named business queries -> reports/sql_results/<name>.csv

Run:  python python/database.py
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

from utils import get_logger, load_config, read_csv_checked

log = get_logger("database")

LOAD_ORDER = ["dim_date", "dim_country", "dim_payment_method", "dim_gateway", "dim_status", "dim_merchant",
              "dim_merchant_pricing", "ref_gateway_costs", "ref_fx_rates", "fact_payments_daily",
              "fact_payments_monthly", "fact_declines_monthly", "fact_gateway_daily"]


def connect(cfg) -> sqlite3.Connection:
    con = sqlite3.connect(cfg["paths"]["database"])
    con.execute("PRAGMA foreign_keys = ON;")
    return con


def run_script(con, path: Path) -> None:
    con.executescript(path.read_text(encoding="utf-8"))
    log.info("executed %s", path.name)


def load_tables(cfg, con) -> None:
    proc = cfg["paths"]["processed"]
    con.execute("PRAGMA synchronous = OFF;")
    for table in LOAD_ORDER:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        path = proc / f"{table}.csv"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing - run etl.py first")
        n = 0
        for chunk in pd.read_csv(path, chunksize=250_000):
            missing = set(cols) - set(chunk.columns)
            if missing:
                raise ValueError(f"{table}: missing columns {missing}")
            chunk[cols].to_sql(table, con, if_exists="append", index=False)
            n += len(chunk)
        log.info("loaded %-24s %9d rows", table, n)
    con.commit()


def assert_dq(con) -> pd.DataFrame:
    dq = pd.read_sql("SELECT * FROM vw_dq_assertions", con)
    for _, r in dq.iterrows():
        (log.info if r.failing_rows == 0 else log.error)("%s %-4s %s", r.check_id,
                                                         "PASS" if r.failing_rows == 0 else "FAIL", r.check_name)
    if (dq["failing_rows"] > 0).any():
        raise ValueError("SQL data-quality assertions failed")
    return dq


def parse_named_queries(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    out = []
    for b in re.split(r"^-- name:\s*", text, flags=re.M)[1:]:
        name, _, body = b.partition("\n")
        q = re.search(r"^-- question:\s*(.+)$", body, flags=re.M)
        out.append({"name": name.strip(), "question": q.group(1).strip() if q else "", "sql": body.strip().rstrip(";")})
    return out


def run_named_queries(cfg, con=None) -> dict[str, pd.DataFrame]:
    con = con or connect(cfg)
    out_dir = cfg["paths"]["reports"] / "sql_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = {}
    for q in parse_named_queries(cfg["paths"]["sql"] / "04_business_analysis.sql"):
        try:
            df = pd.read_sql(q["sql"], con)
        except Exception as exc:
            raise RuntimeError(f"Query {q['name']} failed: {exc}") from exc
        df.to_csv(out_dir / f"{q['name']}.csv", index=False)
        res[q["name"]] = df
        log.info("%-36s %6d rows | %s", q["name"], len(df), q["question"][:70])
    return res


def build(cfg) -> None:
    db = cfg["paths"]["database"]
    if db.exists():
        db.unlink()
    con = connect(cfg)
    try:
        run_script(con, cfg["paths"]["sql"] / "01_schema.sql")
        load_tables(cfg, con)
        for s in ("02_cleaning.sql", "03_kpi_analysis.sql"):
            run_script(con, cfg["paths"]["sql"] / s)
        assert_dq(con)
    finally:
        con.close()
    log.info("database ready: %s", db)


if __name__ == "__main__":
    build(load_config())
