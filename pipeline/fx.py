"""Wechselkurse: offizielle EZB-Referenzkurse (kostenlos, ohne Schlüssel).

Kurse = Einheiten Fremdwährung je 1 EUR, werktäglich ca. 16:00 MEZ.
Historie seit 1999 als ZIP (eurofxref-hist.zip). Fallback: zuletzt gespeicherte Kopie.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

ECB_HIST_ZIP = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"


def parse_ecb_hist(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        name = [n for n in zf.namelist() if n.lower().endswith(".csv")][0]
        raw = zf.read(name).decode("utf-8")
    df = pd.read_csv(io.StringIO(raw), na_values=["N/A", ""], skipinitialspace=True)
    df = df.loc[:, [c for c in df.columns if c and not str(c).startswith("Unnamed")]]
    df.columns = [str(c).strip() for c in df.columns]
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()
    return df.apply(pd.to_numeric, errors="coerce")


def load_fx(http_get_bytes, cache_path: Path, offline: bool = False) -> tuple[pd.DataFrame | None, dict]:
    status = {"source": "EZB-Referenzkurse", "ok": False, "from_cache": False, "last_date": None, "error": None}
    df = None
    if not offline:
        try:
            df = parse_ecb_hist(http_get_bytes(ECB_HIST_ZIP))
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_pickle(cache_path)
            status["ok"] = True
        except Exception as exc:  # noqa: BLE001
            status["error"] = f"EZB nicht erreichbar: {exc}"
    if df is None and cache_path.exists():
        df = pd.read_pickle(cache_path)
        status["from_cache"] = True
        status["ok"] = True
    if df is not None and not df.empty:
        status["last_date"] = df.index.max().strftime("%Y-%m-%d")
    return df, status


def fx_on_index(fx: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Kurse auf ein Datumsraster bringen (Vortageskurs an EZB-Feiertagen)."""
    full = fx.reindex(fx.index.union(index)).sort_index().ffill()
    return full.reindex(index)


def to_eur_factor(currency: str, fx_row: pd.Series) -> float:
    """Multiplikator Lokalwährung -> EUR."""
    if currency == "EUR":
        return 1.0
    rate = fx_row.get(currency)
    if rate is None or pd.isna(rate) or rate == 0:
        return float("nan")
    return 1.0 / float(rate)
