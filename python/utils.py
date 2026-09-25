"""Shared helpers: configuration, paths, logging, fiscal calendar utilities."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


def load_config(path: Path | str = CONFIG_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg["paths"] = {k: PROJECT_ROOT / v for k, v in cfg["paths"].items()}
    return cfg


def ensure_dirs(cfg: dict[str, Any]) -> None:
    for key in ("raw", "processed", "sample", "reports", "images", "insights"):
        cfg["paths"][key].mkdir(parents=True, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(asctime)s | %(name)-11s | %(levelname)-7s | %(message)s", "%H:%M:%S"))
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def read_csv_checked(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Expected input '{path.name}' not found in {path.parent}. "
                                "Run the previous pipeline step first (python run_pipeline.py).")
    return pd.read_csv(path, **kwargs)


def fiscal_year(dates: pd.Series | pd.DatetimeIndex, start_month: int = 7) -> np.ndarray:
    """FY label = calendar year in which the fiscal year ENDS (Jul-2025..Jun-2026 -> 2026)."""
    d = pd.DatetimeIndex(dates)
    return np.where(d.month >= start_month, d.year + 1, d.year) if start_month > 1 else d.year.to_numpy()


def safe_div(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where((b == 0) | np.isnan(b), np.nan, a / b)
