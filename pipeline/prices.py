"""Kursdaten von Yahoo Finance (inoffiziell) mit Cache, inkrementellen Updates und Fallback.

- Primär: Yahoo-Chart-Endpunkt direkt (liefert auch die Kurswährung, z. B. GBp).
- Fallback: Bibliothek yfinance (falls installiert), für Symbole, die direkt scheitern.
- Cache: komplette Historie je Symbol; täglich nur die letzten ~40 Tage nachladen,
  einmal pro Woche (oder auf Wunsch) komplette Neuladung.
- Nachträgliche Dividenden-/Split-Anpassungen werden beim Zusammenführen erkannt und
  auf die ältere Historie übertragen.
"""
from __future__ import annotations

import gzip
import pickle
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd

YAHOO_CHART = "https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
MINOR_UNITS = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0), "ILA": ("ILS", 100.0), "ZAc": ("ZAR", 100.0),
               "KWF": ("KWD", 1000.0)}
HISTORY_START = "2000-01-01"
CACHE_VERSION = 1
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")


@dataclass
class PriceStore:
    data: dict = field(default_factory=dict)   # sym -> {"df": DataFrame(raw units), "meta": dict, "fetched": str, "full": str}

    @classmethod
    def load(cls, path: Path) -> "PriceStore":
        if path.exists():
            try:
                with gzip.open(path, "rb") as fh:
                    obj = pickle.load(fh)
                if obj.get("version") == CACHE_VERSION:
                    return cls(obj["symbols"])
            except Exception:  # noqa: BLE001 – defekter Cache => neu laden
                pass
        return cls({})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wb", compresslevel=5) as fh:
            pickle.dump({"version": CACHE_VERSION, "symbols": self.data}, fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)


def make_session():
    try:
        from curl_cffi import requests as creq  # wird mit yfinance installiert
        return creq.Session(impersonate="chrome"), "curl_cffi"
    except Exception:  # noqa: BLE001
        import requests
        s = requests.Session()
        s.headers["User-Agent"] = UA
        return s, "requests"


def parse_chart_json(js: dict, now: datetime | None = None) -> tuple[pd.DataFrame, dict]:
    chart = js.get("chart") or {}
    if chart.get("error"):
        raise ValueError(str(chart["error"].get("description") or chart["error"]))
    results = chart.get("result") or []
    if not results:
        raise ValueError("leere Antwort")
    res = results[0]
    meta = res.get("meta") or {}
    ts = res.get("timestamp") or []
    if not ts:
        raise ValueError("keine Kurszeitpunkte")
    ind = res.get("indicators") or {}
    q = (ind.get("quote") or [{}])[0]
    adj_list = (ind.get("adjclose") or [{}])[0].get("adjclose")
    offset = int(meta.get("gmtoffset") or 0)
    dates = pd.to_datetime(np.asarray(ts, dtype="int64") + offset, unit="s").normalize()
    close = pd.to_numeric(pd.Series(q.get("close"), dtype="float64"), errors="coerce").values
    adj = pd.to_numeric(pd.Series(adj_list if adj_list is not None else q.get("close"), dtype="float64"), errors="coerce").values
    vol = pd.to_numeric(pd.Series(q.get("volume"), dtype="float64"), errors="coerce").values
    df = pd.DataFrame({"close": close, "adj": adj, "volume": vol}, index=dates)
    df = df[~df.index.duplicated(keep="last")]
    df = df[df["close"].notna() & (df["close"] > 0)]
    df.loc[df["adj"].isna() | (df["adj"] <= 0), "adj"] = np.nan
    # Laufender Handelstag (Teilbalken) entfernen, falls der Markt noch geöffnet ist
    period = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    now = now or datetime.now(timezone.utc)
    end = period.get("end")
    start = period.get("start")
    if end and start and not df.empty and now.timestamp() < float(end):
        open_day = pd.to_datetime(int(start) + offset, unit="s").normalize()
        if df.index[-1] == open_day:
            if now.timestamp() >= float(start):
                df = df.iloc[:-1]          # Markt ist offen: Teilbalken verwerfen
            else:
                # Markt noch nicht offen: Yahoo datiert den letzten Schlusskurs nachts auf den nächsten Handelstag
                # vor. Den Balken auf den Tag des letzten regulären Schlusskurses zurücksetzen statt ihn zu verwerfen.
                rmt = meta.get("regularMarketTime")
                real_day = pd.to_datetime(int(rmt) + offset, unit="s").normalize() if rmt else None
                if real_day is not None and real_day < open_day and real_day not in df.index[:-1]:
                    df = df.rename(index={df.index[-1]: real_day})
                else:
                    df = df.iloc[:-1]
    info = {
        "currency": meta.get("currency"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "tz": meta.get("exchangeTimezoneName"),
        "instrument": meta.get("instrumentType"),
        "name": meta.get("longName") or meta.get("shortName"),
    }
    return df.sort_index(), info


def fetch_direct(session, sym: str, start: pd.Timestamp, retries: int = 3, sleep=None) -> tuple[pd.DataFrame | None, dict, str]:
    sleep = sleep or time.sleep
    params = {
        "period1": int(pd.Timestamp(start).timestamp()),
        "period2": int(time.time()) + 86400,
        "interval": "1d",
        "events": "div,splits",
        "includeAdjustedClose": "true",
    }
    url = YAHOO_CHART.format(sym=quote(sym, safe=""))
    backoff = [20, 60]
    last_err = ""
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=25)
        except Exception as exc:  # noqa: BLE001
            last_err = f"Netzwerk: {exc.__class__.__name__}"
            sleep(3)
            continue
        if r.status_code == 429:
            last_err = "429 (gedrosselt)"
            if attempt < retries - 1:
                sleep(backoff[min(attempt, len(backoff) - 1)])
            continue
        if r.status_code == 404:
            return None, {}, "nicht gefunden (404)"
        if r.status_code >= 400:
            last_err = f"HTTP {r.status_code}"
            sleep(2)
            continue
        try:
            df, info = parse_chart_json(r.json())
            return df, info, "ok"
        except Exception as exc:  # noqa: BLE001
            return None, {}, f"Format: {exc}"
    return None, {}, last_err or "unbekannter Fehler"


def fetch_yfinance(symbols: list[str], start: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Fallback über yfinance. Gibt nur erfolgreich geladene Symbole zurück."""
    try:
        import yfinance as yf
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for i in range(0, len(symbols), 25):
        chunk = symbols[i:i + 25]
        try:
            raw = yf.download(chunk, start=pd.Timestamp(start).strftime("%Y-%m-%d"), auto_adjust=False,
                              actions=False, group_by="ticker", threads=False, progress=False)
        except Exception:  # noqa: BLE001
            continue
        if raw is None or raw.empty:
            continue
        for sym in chunk:
            try:
                sub = _yf_extract(raw, sym, len(chunk))
            except Exception:  # noqa: BLE001
                continue
            if sub is not None and not sub.empty:
                out[sym] = sub
        time.sleep(1.0)
    return out


def _yf_extract(raw: pd.DataFrame, sym: str, n: int) -> pd.DataFrame | None:
    fields = {"Close": "close", "Adj Close": "adj", "Volume": "volume"}
    if isinstance(raw.columns, pd.MultiIndex):
        lvl0 = set(raw.columns.get_level_values(0))
        if sym in lvl0:
            sub = raw[sym]
        elif sym in set(raw.columns.get_level_values(1)):
            sub = raw.xs(sym, axis=1, level=1)
        else:
            return None
    else:
        if n != 1:
            return None
        sub = raw
    cols = {c: fields[c] for c in sub.columns if c in fields}
    df = sub[list(cols)].rename(columns=cols).copy()
    if "adj" not in df:
        df["adj"] = df["close"]
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df = df[df["close"].notna() & (df["close"] > 0)]
    return df[["close", "adj", "volume"]].astype(float)


def merge_incremental(old: pd.DataFrame, new: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Hängt neue Daten an und überträgt neue Split-/Dividendenfaktoren auf die alte Historie."""
    info = {"close_factor": 1.0, "adj_factor": 1.0, "needs_full": False}
    if old is None or old.empty:
        return new.copy(), info
    if new is None or new.empty:
        return old.copy(), info
    overlap = old.index.intersection(new.index)
    if len(overlap) == 0:
        info["needs_full"] = True
        return old.copy(), info
    d0 = overlap.min()
    fc = new.at[d0, "close"] / old.at[d0, "close"]
    fa = new.at[d0, "adj"] / old.at[d0, "adj"] if np.isfinite(old.at[d0, "adj"]) and old.at[d0, "adj"] > 0 else 1.0
    keep_newer = old.loc[old.index > new.index.max()]   # neuere, bereits gespeicherte Schlusskurse nicht verlieren
    old = old.loc[old.index < d0].copy()
    if np.isfinite(fc) and abs(fc - 1.0) > 1e-4:
        old["close"] *= fc
        old["volume"] /= fc
        info["close_factor"] = float(fc)
    if np.isfinite(fa) and abs(fa - 1.0) > 1e-7:
        old["adj"] *= fa
        info["adj_factor"] = float(fa)
    if len(keep_newer):
        keep_newer = keep_newer.copy()
        keep_newer["close"] *= info["close_factor"]
        keep_newer["adj"] *= info["adj_factor"]
    merged = pd.concat([old, new, keep_newer]).sort_index()
    merged = merged[~merged.index.duplicated(keep="first")]
    return merged, info


def normalize_units(df: pd.DataFrame, currency: str | None) -> tuple[pd.DataFrame, str | None]:
    if currency in MINOR_UNITS:
        major, factor = MINOR_UNITS[currency]
        df = df.copy()
        df["close"] /= factor
        df["adj"] /= factor
        return df, major
    return df, currency


@dataclass
class PriceUpdateResult:
    frames: dict            # sym -> normalisierte DataFrame
    currency: dict          # sym -> Währung (Haupteinheit)
    status: dict            # sym -> Text
    stats: dict


def update_prices(symbols: list[str], store: PriceStore, currency_hints: dict, full_refresh: bool,
                  session=None, deadline_s: float = 3600, delay_s: float = 0.25,
                  today: pd.Timestamp | None = None, log=print, refresh_if_older_days: int | None = None,
                  fallback: bool = True, skip: set | None = None) -> PriceUpdateResult:
    today = (today or pd.Timestamp.utcnow().tz_localize(None)).normalize()
    if session is None:
        session, kind = make_session()
    else:
        kind = "custom"
    t0 = time.time()
    status, failed = {}, []
    stats = {"requested": len(symbols), "ok": 0, "cached_only": 0, "failed": 0, "full": 0,
             "incremental": 0, "client": kind, "blocked": False, "yfinance_fallback": 0}
    consecutive_fail = 0
    for i, sym in enumerate(symbols):
        if time.time() - t0 > deadline_s or stats["blocked"]:
            status[sym] = "übersprungen (Zeitlimit/Sperre) – Cache verwendet"
            failed.append(sym)
            continue
        entry = store.data.get(sym)
        if skip and sym in skip:
            status[sym] = "übersprungen (zuletzt nicht gefunden)"
            continue
        if refresh_if_older_days is not None and entry is not None and entry.get("fetched") and \
                (today - pd.Timestamp(entry["fetched"])).days < refresh_if_older_days:
            # heute schon geladen (z. B. im ersten Screening desselben Laufs) = so gut wie ein frischer Abruf
            status[sym] = "ok (heute bereits geladen)" if (today - pd.Timestamp(entry["fetched"])).days < 1 \
                else "aus Cache (noch aktuell)"
            continue
        full = full_refresh or entry is None or entry.get("full") is None or \
            (today - pd.Timestamp(entry["full"])).days > 8
        start = pd.Timestamp(HISTORY_START) if full else today - pd.Timedelta(days=40)
        df, info, msg = fetch_direct(session, sym, start)
        if df is None or df.empty:
            # 404 = Server antwortet normal, Symbol existiert nicht -> kein Hinweis auf eine Sperre
            consecutive_fail = 0 if msg.startswith("nicht gefunden") else consecutive_fail + 1
            status[sym] = f"Fehler: {msg}"
            failed.append(sym)
            if consecutive_fail >= 8:
                stats["blocked"] = True
                log(f"[prices] 8 Abruffehler in Folge – Datenquelle vermutlich gesperrt (zuletzt: {msg})")
        else:
            consecutive_fail = 0
            _store_update(store, sym, df, info, full, today, stats)
            status[sym] = "ok"
        if delay_s:
            time.sleep(delay_s)
        if (i + 1) % 200 == 0:
            log(f"[prices] {i + 1}/{len(symbols)} verarbeitet, Fehler bisher: {len(failed)}")
    # Fallback yfinance für gescheiterte Symbole
    retry = [s for s in failed if not status[s].startswith("übersprungen")]
    if retry and not stats["blocked"] and fallback:
        got = fetch_yfinance(retry, pd.Timestamp(HISTORY_START))
        for sym, df in got.items():
            entry = store.data.get(sym, {})
            info = dict(entry.get("meta", {}))
            if not info.get("currency"):
                info["currency"] = currency_hints.get(sym)
                info["currency_inferred"] = True
            _store_update(store, sym, df, info, True, today, stats)
            status[sym] = "ok (yfinance)"
            stats["yfinance_fallback"] += 1
    frames, currency = {}, {}
    for sym in symbols:
        entry = store.data.get(sym)
        if entry is None or entry["df"].empty:
            stats["failed"] += 1
            continue
        if status.get(sym, "").startswith("ok"):
            stats["ok"] += 1
        else:
            stats["cached_only"] += 1
        cur = entry["meta"].get("currency") or currency_hints.get(sym)
        norm, major = normalize_units(entry["df"], cur)
        frames[sym] = norm
        currency[sym] = major
    stats["seconds"] = round(time.time() - t0, 1)
    return PriceUpdateResult(frames, currency, status, stats)


def _store_update(store: PriceStore, sym: str, df: pd.DataFrame, info: dict, full: bool,
                  today: pd.Timestamp, stats: dict) -> None:
    entry = store.data.get(sym)
    if full or entry is None:
        merged = df
        stats["full"] += 1
        full_date = today.strftime("%Y-%m-%d")
    else:
        merged, minfo = merge_incremental(entry["df"], df)
        stats["incremental"] += 1
        full_date = None if minfo["needs_full"] else entry.get("full")
    meta = dict(entry["meta"]) if entry else {}
    meta.update({k: v for k, v in info.items() if v})
    store.data[sym] = {"df": merged, "meta": meta, "fetched": today.strftime("%Y-%m-%d"), "full": full_date}


def to_wide(frames: dict, field_name: str, start: str | None = None) -> pd.DataFrame:
    cols = {s: df[field_name] for s, df in frames.items() if not df.empty}
    wide = pd.DataFrame(cols).sort_index()
    if start:
        wide = wide.loc[wide.index >= pd.Timestamp(start)]
    return wide
