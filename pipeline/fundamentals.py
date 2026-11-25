"""Kennzahlen und Analystenschätzungen für Stage 2 – Yahoo Finance (inoffiziell, kostenlos, ohne Schlüssel).

Je Aktie zwei Abrufarten:
  1) quoteSummary (EIN Aufruf mit mehreren Modulen): Bewertung, Margen, Renditen, Verschuldung, Wachstum,
     Analystenschätzungen (EPS-Trend heute / vor 7, 30, 60, 90 Tagen, Zahl der Auf-/Abwärtsrevisionen),
     Gewinnüberraschungen der letzten Quartale und der nächste Quartalstermin.
  2) Fundamentals-Zeitreihen (EIN Aufruf): Jahreswerte für ROIC, Zinsdeckung, Verwässerung und Margenentwicklung.

Damit Vergleiche fair sind (Perzentile gegen das ganze Universum bzw. den eigenen Sektor), werden die Daten
für ALLE Aktien des Universums gepflegt – rollierend, nicht alles an einem Tag:
  Stage-1-Kandidaten und Beobachtungsliste täglich, Momentum-Vergleichsgruppe alle 3 Tage, übriges Universum
  wöchentlich, Jahreswerte alle 45 Tage. Pausen zwischen den Abrufen, Mengen- und Zeitbudget je Lauf und
  Abbruch bei Drosselung schützen vor Sperren. Kurse (wichtiger) werden vorher geladen.

Grundsatz: Nichts wird geschätzt oder aufgefüllt. Fehlt ein Wert, bleibt er leer und wird als fehlend angezeigt.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd

QS_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}"
TS_URL = "https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{sym}"
COOKIE_URL = "https://fc.yahoo.com"
CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
QS_MODULES = ["financialData", "defaultKeyStatistics", "summaryDetail", "earningsTrend",
              "earningsHistory", "calendarEvents", "price"]
TS_FIELDS = ["TotalRevenue", "OperatingIncome", "EBIT", "InterestExpense", "DilutedAverageShares",
             "TotalDebt", "StockholdersEquity", "CashAndCashEquivalents", "InvestedCapital", "FreeCashFlow"]
STORE_VERSION = 1
MINOR_UNITS = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0), "ILA": ("ILS", 100.0), "ZAc": ("ZAR", 100.0)}


class RateLimited(Exception):
    """Yahoo drosselt (HTTP 429)."""


class NotFound(Exception):
    """Für dieses Symbol gibt es keine Daten."""


class CrumbError(Exception):
    """Zugangskennung (Cookie/Crumb) nicht erhältlich."""


# ------------------------------------------------------------------ Parser
def _num(v):
    """Zahl aus einem Yahoo-Feld ({"raw": x}, x oder {}). Fehlend/ungültig -> None."""
    if isinstance(v, dict):
        v = v.get("raw")
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _date(v) -> str | None:
    """Epoch-Sekunden, {"raw": epoch} oder 'YYYY-MM-DD' -> ISO-Datum."""
    if isinstance(v, dict):
        v = v.get("raw", v.get("fmt"))
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, str):
        try:
            return pd.Timestamp(v[:10]).strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or x <= 0:
        return None
    return datetime.fromtimestamp(x, tz=timezone.utc).strftime("%Y-%m-%d")


def parse_quote_summary(js: dict) -> dict:
    qs = (js or {}).get("quoteSummary") or {}
    err = qs.get("error")
    if err:
        desc = (err.get("description") or err.get("code") or str(err)) if isinstance(err, dict) else str(err)
        if "not found" in desc.lower() or "no fundamentals" in desc.lower():
            raise NotFound(desc)
        raise ValueError(desc)
    res = (qs.get("result") or [None])[0]
    if not res:
        raise NotFound("leere Antwort")
    fd = res.get("financialData") or {}
    ks = res.get("defaultKeyStatistics") or {}
    sd = res.get("summaryDetail") or {}
    pr = res.get("price") or {}

    def first(*vals):
        for v in vals:
            x = _num(v)
            if x is not None:
                return x
        return None

    rec = {
        "currency": pr.get("currency") or sd.get("currency"),
        "fin_currency": fd.get("financialCurrency"),
        "name": pr.get("longName") or pr.get("shortName"),
        "price": first(fd.get("currentPrice"), pr.get("regularMarketPrice"), sd.get("previousClose")),
        "market_cap": first(pr.get("marketCap"), sd.get("marketCap")),
        "pe_ttm": _num(sd.get("trailingPE")),
        "pe_fwd": first(ks.get("forwardPE"), sd.get("forwardPE")),
        "eps_ttm": _num(ks.get("trailingEps")),
        "eps_fwd": _num(ks.get("forwardEps")),
        "ev": _num(ks.get("enterpriseValue")),
        "ev_ebitda": _num(ks.get("enterpriseToEbitda")),
        "ps": _num(sd.get("priceToSalesTrailing12Months")),
        "pb": _num(ks.get("priceToBook")),
        "revenue": _num(fd.get("totalRevenue")),
        "ebitda": _num(fd.get("ebitda")),
        "total_debt": _num(fd.get("totalDebt")),
        "total_cash": _num(fd.get("totalCash")),
        "fcf": _num(fd.get("freeCashflow")),
        "ocf": _num(fd.get("operatingCashflow")),
        "de_pct": _num(fd.get("debtToEquity")),
        "current_ratio": _num(fd.get("currentRatio")),
        "roe": _num(fd.get("returnOnEquity")),
        "roa": _num(fd.get("returnOnAssets")),
        "gross_margin": _num(fd.get("grossMargins")),
        "op_margin": _num(fd.get("operatingMargins")),
        "profit_margin": _num(fd.get("profitMargins")),
        "rev_growth": _num(fd.get("revenueGrowth")),
        "eps_growth": _num(fd.get("earningsGrowth")),
        "analysts": _num(fd.get("numberOfAnalystOpinions")),
        "rec_mean": _num(fd.get("recommendationMean")),
        "target_mean": _num(fd.get("targetMeanPrice")),
        "last_fy_end": _date(ks.get("lastFiscalYearEnd")),
        "mrq": _date(ks.get("mostRecentQuarter")),
    }
    trend = {}
    for t in ((res.get("earningsTrend") or {}).get("trend") or []):
        per = t.get("period")
        if per not in ("0q", "+1q", "0y", "+1y"):
            continue
        ee = t.get("earningsEstimate") or {}
        rv = t.get("revenueEstimate") or {}
        et = t.get("epsTrend") or {}
        er = t.get("epsRevisions") or {}
        trend[per] = {
            "end": _date(t.get("endDate")),
            "eps_avg": _num(ee.get("avg")), "eps_n": _num(ee.get("numberOfAnalysts")),
            "eps_growth": first(ee.get("growth"), t.get("growth")),
            "rev_avg": _num(rv.get("avg")), "rev_n": _num(rv.get("numberOfAnalysts")), "rev_growth": _num(rv.get("growth")),
            "eps_now": _num(et.get("current")), "eps_7d": _num(et.get("7daysAgo")), "eps_30d": _num(et.get("30daysAgo")),
            "eps_60d": _num(et.get("60daysAgo")), "eps_90d": _num(et.get("90daysAgo")),
            "up7": _num(er.get("upLast7days")), "up30": _num(er.get("upLast30days")),
            "down30": _num(er.get("downLast30days")), "down7": first(er.get("downLast7Days"), er.get("downLast7days")),
        }
    rec["trend"] = trend
    hist = []
    for h in ((res.get("earningsHistory") or {}).get("history") or []):
        q = _date(h.get("quarter"))
        act, est = _num(h.get("epsActual")), _num(h.get("epsEstimate"))
        sp = _num(h.get("surprisePercent"))
        if sp is None and act is not None and est not in (None, 0.0):
            sp = (act - est) / abs(est)
        if q and (act is not None or sp is not None):
            hist.append({"quarter": q, "eps_actual": act, "eps_est": est, "surprise": sp})
    hist.sort(key=lambda x: x["quarter"])
    rec["history"] = hist[-4:]
    ce = res.get("calendarEvents") or {}
    ed = (ce.get("earnings") or {}).get("earningsDate") or []
    if isinstance(ed, (dict, int, float, str)):
        ed = [ed]
    dates = sorted(d for d in (_date(x) for x in ed) if d)
    rec["next_earnings"] = dates[0] if dates else None
    rec["ex_dividend"] = _date(ce.get("exDividendDate"))
    return rec


def parse_timeseries(js: dict) -> dict:
    ts = (js or {}).get("timeseries") or {}
    if ts.get("error"):
        raise ValueError(str(ts["error"]))
    series, currency = {}, None
    for item in ts.get("result") or []:
        meta = item.get("meta") or {}
        for typ in meta.get("type") or []:
            out = {}
            for v in item.get(typ) or []:
                if not v:
                    continue
                d, x = v.get("asOfDate"), _num(v.get("reportedValue"))
                if d and x is not None:
                    out[str(d)[:10]] = x
                    currency = currency or v.get("currencyCode")
            if out:
                series[typ] = out
    if not series:
        raise NotFound("keine Jahreswerte")
    return derive_timeseries(series, currency)


def _consecutive(d1: str, d2: str) -> bool:
    days = (pd.Timestamp(d2) - pd.Timestamp(d1)).days
    return 300 <= days <= 430


def derive_timeseries(series: dict, currency: str | None = None) -> dict:
    """Leitet Kennzahlen aus Jahreswerten ab (nur wenn die Bausteine wirklich vorhanden sind)."""
    def ann(name):
        return series.get("annual" + name) or {}
    rev, oi, ebit = ann("TotalRevenue"), ann("OperatingIncome"), ann("EBIT")
    years = sorted(set(rev) | set(oi) | set(ebit))
    rec = {"currency": currency, "fy_end": years[-1] if years else None, "roic_pre": None, "interest_cov": None,
           "dilution": None, "margin_change": None, "op_margin_fy": None, "rev_fy": None, "fcf_fy": None}
    if not years:
        return rec
    y = years[-1]
    ebit_y = ebit.get(y, oi.get(y))
    ic = ann("InvestedCapital").get(y)
    if ic is None:
        td, eq, cash = ann("TotalDebt").get(y), ann("StockholdersEquity").get(y), ann("CashAndCashEquivalents").get(y)
        if td is not None and eq is not None:
            ic = td + eq - (cash or 0.0)
    if ebit_y is not None and ic is not None and ic > 0:
        rec["roic_pre"] = ebit_y / ic
    ie = ann("InterestExpense").get(y)
    if ebit_y is not None and ie is not None and abs(ie) > 0:
        rec["interest_cov"] = ebit_y / abs(ie)
    sh = ann("DilutedAverageShares")
    sy = sorted(sh)
    if len(sy) >= 2 and sh[sy[-2]] > 0 and _consecutive(sy[-2], sy[-1]):
        rec["dilution"] = sh[sy[-1]] / sh[sy[-2]] - 1.0
    both = sorted(d for d in years if rev.get(d) and rev.get(d) > 0 and oi.get(d) is not None)
    if both:
        rec["op_margin_fy"] = oi[both[-1]] / rev[both[-1]]
        if len(both) >= 2 and _consecutive(both[-2], both[-1]):
            rec["margin_change"] = rec["op_margin_fy"] - oi[both[-2]] / rev[both[-2]]
    rec["rev_fy"] = rev.get(y)
    rec["fcf_fy"] = ann("FreeCashFlow").get(y)
    return rec


# ------------------------------------------------------------------ Zugriff
class YahooClient:
    """Direkter Zugriff mit eigener Cookie-/Crumb-Verwaltung (curl_cffi-Sitzung wie bei den Kursen)."""

    def __init__(self, session=None, log=print):
        if session is None:
            from .prices import make_session
            session, self.kind = make_session()
        else:
            self.kind = "custom"
        self.s = session
        self.log = log
        self.crumb = None
        self.crumb_failed = False

    def _ensure_crumb(self):
        if self.crumb:
            return
        if self.crumb_failed:
            raise CrumbError("Crumb nicht erhältlich")
        try:
            self.s.get(COOKIE_URL, timeout=20)
        except Exception:  # noqa: BLE001 – Seite antwortet oft mit Fehlercode, setzt aber das Cookie
            pass
        r = self.s.get(CRUMB_URL, timeout=20)
        txt = (getattr(r, "text", "") or "").strip()
        if r.status_code == 429:
            raise RateLimited("429 (Crumb)")
        if r.status_code != 200 or not txt or "<" in txt or " " in txt or len(txt) > 40:
            self.crumb_failed = True
            raise CrumbError(f"kein Crumb (HTTP {r.status_code})")
        self.crumb = txt

    def get_json(self, url: str, params: dict) -> dict:
        self._ensure_crumb()
        for attempt in range(2):
            try:
                r = self.s.get(url, params=dict(params, crumb=self.crumb), timeout=30)
            except Exception as exc:  # noqa: BLE001
                raise IOError(f"Netzwerk: {exc.__class__.__name__}") from exc
            if r.status_code == 401 and attempt == 0:
                self.crumb = None
                self._ensure_crumb()
                continue
            if r.status_code == 429:
                raise RateLimited("429")
            if r.status_code == 404:
                raise NotFound("404")
            if r.status_code >= 400:
                raise IOError(f"HTTP {r.status_code}")
            try:
                return r.json()
            except Exception as exc:  # noqa: BLE001
                txt = (getattr(r, "text", "") or "")[:80]
                if "too many" in txt.lower():
                    raise RateLimited(txt) from exc
                raise ValueError("Antwort ist kein JSON") from exc
        raise CrumbError("Crumb wird abgelehnt")

    def quote_summary(self, sym: str) -> dict:
        js = self.get_json(QS_URL.format(sym=quote(sym, safe="")),
                           {"modules": ",".join(QS_MODULES), "formatted": "false", "lang": "en-US",
                            "region": "US", "corsDomain": "finance.yahoo.com"})
        return parse_quote_summary(js)

    def timeseries(self, sym: str, today: pd.Timestamp) -> dict:
        end = int(pd.Timestamp(today).timestamp()) + 86400
        start = int((pd.Timestamp(today) - pd.DateOffset(years=6)).timestamp())
        js = self.get_json(TS_URL.format(sym=quote(sym, safe="")),
                           {"symbol": sym, "type": ",".join("annual" + f for f in TS_FIELDS),
                            "period1": start, "period2": end, "merge": "false", "padTimeSeries": "true",
                            "lang": "en-US", "region": "US"})
        return parse_timeseries(js)


def _map_yf_error(exc: Exception) -> Exception:
    name = exc.__class__.__name__.lower()
    text = str(exc).lower()
    if "ratelimit" in name or "too many" in text or "rate limit" in text:
        return RateLimited(str(exc)[:80])
    return exc


class YFinanceClient:
    """Reserve über die Bibliothek yfinance (eigene Cookie-/Crumb-Verwaltung, passt sich Yahoo-Änderungen an)."""

    kind = "yfinance"

    def __init__(self):
        import yfinance  # noqa: F401 – Fehler, falls nicht installiert
        self._raw_ok = True

    def _raw(self, url: str, params: dict) -> dict:
        from yfinance.data import YfData
        data = YfData()
        try:
            return data.get_raw_json(url, params=params)
        except TypeError:
            return data.get_raw_json(url, None, params)

    def quote_summary(self, sym: str) -> dict:
        if self._raw_ok:
            try:
                js = self._raw(QS_URL.format(sym=quote(sym, safe="")),
                               {"modules": ",".join(QS_MODULES), "formatted": "false", "lang": "en-US",
                                "region": "US", "corsDomain": "finance.yahoo.com", "symbol": sym})
                return parse_quote_summary(js)
            except NotFound:
                raise
            except Exception as exc:  # noqa: BLE001
                mapped = _map_yf_error(exc)
                if isinstance(mapped, RateLimited):
                    raise mapped from exc
                self._raw_ok = False      # interne Schnittstelle geändert -> öffentliche Funktionen
        return record_from_yf_public(sym)

    def timeseries(self, sym: str, today: pd.Timestamp) -> dict:
        try:
            end = int(pd.Timestamp(today).timestamp()) + 86400
            start = int((pd.Timestamp(today) - pd.DateOffset(years=6)).timestamp())
            js = self._raw(TS_URL.format(sym=quote(sym, safe="")),
                           {"symbol": sym, "type": ",".join("annual" + f for f in TS_FIELDS),
                            "period1": start, "period2": end, "merge": "false", "padTimeSeries": "true"})
            return parse_timeseries(js)
        except NotFound:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _map_yf_error(exc) from exc


def record_from_yf_public(sym: str) -> dict:
    """Letzte Reserve: öffentliche yfinance-Funktionen (mehrere Aufrufe) in dasselbe Format bringen."""
    import yfinance as yf
    t = yf.Ticker(sym)
    try:
        info = t.info or {}
    except Exception as exc:  # noqa: BLE001
        raise _map_yf_error(exc) from exc
    if not info or len(info) < 5:
        raise NotFound("keine Unternehmensdaten")
    g = lambda k: _num(info.get(k))  # noqa: E731
    earn = info.get("earningsTimestampStart") or info.get("earningsTimestamp")
    rec = {
        "currency": info.get("currency"), "fin_currency": info.get("financialCurrency"),
        "name": info.get("longName") or info.get("shortName"),
        "price": g("currentPrice") or g("regularMarketPrice"), "market_cap": g("marketCap"),
        "pe_ttm": g("trailingPE"), "pe_fwd": g("forwardPE"), "eps_ttm": g("trailingEps"), "eps_fwd": g("forwardEps"),
        "ev": g("enterpriseValue"), "ev_ebitda": g("enterpriseToEbitda"), "ps": g("priceToSalesTrailing12Months"),
        "pb": g("priceToBook"), "revenue": g("totalRevenue"), "ebitda": g("ebitda"), "total_debt": g("totalDebt"),
        "total_cash": g("totalCash"), "fcf": g("freeCashflow"), "ocf": g("operatingCashflow"),
        "de_pct": g("debtToEquity"), "current_ratio": g("currentRatio"), "roe": g("returnOnEquity"),
        "roa": g("returnOnAssets"), "gross_margin": g("grossMargins"), "op_margin": g("operatingMargins"),
        "profit_margin": g("profitMargins"), "rev_growth": g("revenueGrowth"), "eps_growth": g("earningsGrowth"),
        "analysts": g("numberOfAnalystOpinions"), "rec_mean": g("recommendationMean"),
        "target_mean": g("targetMeanPrice"), "last_fy_end": _date(info.get("lastFiscalYearEnd")),
        "mrq": _date(info.get("mostRecentQuarter")), "next_earnings": _date(earn), "ex_dividend": _date(info.get("exDividendDate")),
        "trend": {}, "history": [],
    }

    def frame(attr):
        try:
            df = getattr(t, attr)
            return df if isinstance(df, pd.DataFrame) and not df.empty else None
        except Exception:  # noqa: BLE001
            return None
    et, er, ee, rv = frame("eps_trend"), frame("eps_revisions"), frame("earnings_estimate"), frame("revenue_estimate")
    for per in ("0q", "+1q", "0y", "+1y"):
        row = {}
        def val(df, col):
            try:
                return _num(df.at[per, col]) if df is not None and per in df.index and col in df.columns else None
            except Exception:  # noqa: BLE001
                return None
        row = {"end": None, "eps_avg": val(ee, "avg"), "eps_n": val(ee, "numberOfAnalysts"), "eps_growth": val(ee, "growth"),
               "rev_avg": val(rv, "avg"), "rev_n": val(rv, "numberOfAnalysts"), "rev_growth": val(rv, "growth"),
               "eps_now": val(et, "current"), "eps_7d": val(et, "7daysAgo"), "eps_30d": val(et, "30daysAgo"),
               "eps_60d": val(et, "60daysAgo"), "eps_90d": val(et, "90daysAgo"),
               "up7": val(er, "upLast7days"), "up30": val(er, "upLast30days"), "down30": val(er, "downLast30days"),
               "down7": val(er, "downLast7Days") if val(er, "downLast7Days") is not None else val(er, "downLast7days")}
        if any(v is not None for k, v in row.items() if k != "end"):
            rec["trend"][per] = row
    eh = frame("earnings_history")
    if eh is not None:
        for q, r in eh.iterrows():
            qd = _date(str(q)[:10])
            act, est, sp = _num(r.get("epsActual")), _num(r.get("epsEstimate")), _num(r.get("surprisePercent"))
            if qd and (act is not None or sp is not None):
                rec["history"].append({"quarter": qd, "eps_actual": act, "eps_est": est, "surprise": sp})
        rec["history"] = sorted(rec["history"], key=lambda x: x["quarter"])[-4:]
    return rec


# ------------------------------------------------------------------ Speicher
@dataclass
class FundamentalsStore:
    data: dict = field(default_factory=dict)   # sym -> {"qs", "qs_at", "qs_err", "qs_try", "ts", "ts_at", "ts_err", "ts_try"}

    @classmethod
    def load(cls, path: Path) -> "FundamentalsStore":
        if path.exists():
            try:
                with gzip.open(path, "rt", encoding="utf-8") as fh:
                    obj = json.load(fh)
                if obj.get("version") == STORE_VERSION:
                    return cls(obj.get("symbols") or {})
            except Exception:  # noqa: BLE001 – defekter Cache => neu aufbauen
                pass
        return cls({})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as fh:
            json.dump({"version": STORE_VERSION, "symbols": self.data}, fh, separators=(",", ":"))
        tmp.replace(path)

    def age(self, sym: str, kind: str, today: pd.Timestamp) -> float:
        d = (self.data.get(sym) or {}).get(f"{kind}_at")
        return float((today - pd.Timestamp(d)).days) if d else float("inf")

    def record(self, sym: str, kind: str):
        return (self.data.get(sym) or {}).get(kind)


def coverage(store: FundamentalsStore, syms, today: pd.Timestamp, max_age: float, kind: str = "qs") -> float:
    syms = list(syms)
    if not syms:
        return 0.0
    ok = sum(1 for s in syms if store.record(s, kind) is not None and store.age(s, kind, today) <= max_age)
    return ok / len(syms)


def _hash_order(sym: str) -> str:
    return hashlib.md5(sym.encode()).hexdigest()   # deterministisch "zufällige" Reihenfolge (keine Alphabet-Verzerrung)


def plan_refresh(store: FundamentalsStore, today: pd.Timestamp, candidates, peers, universe, params: dict):
    """Liefert (qs_liste, ts_liste, aufbauphase) in Prioritätsreihenfolge."""
    universe = list(dict.fromkeys(universe))
    cands = list(dict.fromkeys(candidates))
    peers = [s for s in dict.fromkeys(peers) if s not in set(cands)]
    rest = [s for s in universe if s not in set(cands) | set(peers)]

    def retry_ok(sym, kind):
        e = store.data.get(sym) or {}
        tried, err = e.get(f"{kind}_try"), e.get(f"{kind}_err")
        if not tried or not err:
            return True
        wait = 7 if str(err).startswith("nicht gefunden") else 1
        return (today - pd.Timestamp(tried)).days >= wait

    qs = [s for s in cands if store.age(s, "qs", today) >= params["qs_age_candidates"] and retry_ok(s, "qs")]
    qs += [s for s in peers if store.age(s, "qs", today) >= params["qs_age_peers"] and retry_ok(s, "qs")]
    stale = [s for s in rest if store.age(s, "qs", today) >= params["qs_age_universe"] and retry_ok(s, "qs")]
    stale.sort(key=lambda s: (-min(store.age(s, "qs", today), 1e6), _hash_order(s)))
    qs += stale
    ts_pool = cands + peers + sorted(rest, key=_hash_order)
    ts = [s for s in ts_pool if store.age(s, "ts", today) >= params["ts_age"] and retry_ok(s, "ts")]
    cov = coverage(store, universe, today, 21)
    return qs, ts, cov < params["boot_coverage"]


def refresh(store: FundamentalsStore, qs_list, ts_list, today: pd.Timestamp, params: dict, boot: bool,
            clients=None, sleep=None, clock=None, log=print) -> dict:
    """Ruft Daten ab, solange Budget und Zeit reichen. Gibt eine Statistik zurück."""
    sleep = sleep or time.sleep
    clock = clock or time.time
    t0 = clock()
    deadline = params["deadline_s_boot"] if boot else params["deadline_s"]
    budget = {"qs": params["qs_calls_boot"] if boot else params["qs_calls"],
              "ts": params["ts_calls_boot"] if boot else params["ts_calls"]}
    stats = {"qs_ok": 0, "qs_fail": 0, "qs_notfound": 0, "ts_ok": 0, "ts_fail": 0, "ts_notfound": 0,
             "blocked": False, "boot": boot, "path": None, "planned_qs": len(qs_list), "planned_ts": len(ts_list),
             "skipped_qs": 0, "skipped_ts": 0}
    if clients is None:
        clients = []
        try:
            clients.append(YahooClient(log=log))
        except Exception:  # noqa: BLE001
            pass
        try:
            clients.append(YFinanceClient())
        except Exception:  # noqa: BLE001
            pass
    if not clients:
        stats["blocked"] = True
        stats["error"] = "kein Abrufweg verfügbar"
        return stats
    active = [0]
    client_err = [0] * len(clients)
    today_s = today.strftime("%Y-%m-%d")
    consec_rl, consec_err = 0, 0

    def call(kind, sym):
        while True:
            i = active[0]
            if i >= len(clients):
                raise CrumbError("kein funktionierender Abrufweg")
            cl = clients[i]
            try:
                out = cl.quote_summary(sym) if kind == "qs" else cl.timeseries(sym, today)
                client_err[i] = 0
                stats["path"] = getattr(cl, "kind", "?")
                return out
            except (NotFound, RateLimited):
                client_err[i] = 0      # Server antwortet -> Abrufweg funktioniert grundsätzlich
                raise
            except CrumbError:
                active[0] += 1         # Zugang klappt nicht -> nächster Abrufweg für den Rest des Laufs
            except Exception:  # noqa: BLE001
                client_err[i] += 1
                if client_err[i] >= 4 and i + 1 < len(clients):
                    active[0] += 1     # wiederholt kaputte Antworten -> Reserve-Abrufweg
                    continue
                raise

    for kind, lst in (("qs", qs_list), ("ts", ts_list)):
        done = 0
        for sym in lst:
            if stats["blocked"] or clock() - t0 > deadline or done >= budget[kind]:
                stats[f"skipped_{kind}"] += 1
                continue
            entry = store.data.setdefault(sym, {})
            done += 1
            try:
                rec = call(kind, sym)
                entry[kind], entry[f"{kind}_at"], entry[f"{kind}_err"], entry[f"{kind}_try"] = rec, today_s, None, today_s
                stats[f"{kind}_ok"] += 1
                consec_rl, consec_err = 0, 0
            except NotFound as exc:
                entry[f"{kind}_err"], entry[f"{kind}_try"] = f"nicht gefunden: {exc}"[:120], today_s
                stats[f"{kind}_notfound"] += 1
                consec_err = 0
            except RateLimited as exc:
                consec_rl += 1
                stats[f"{kind}_fail"] += 1
                entry[f"{kind}_err"], entry[f"{kind}_try"] = f"gedrosselt: {exc}"[:120], today_s
                if consec_rl >= 3:
                    stats["blocked"] = True
                    log(f"[fundamentals] Yahoo drosselt – Abruf für heute beendet ({stats['qs_ok']} + {stats['ts_ok']} aktualisiert)")
                else:
                    sleep(30 if consec_rl == 1 else 90)
            except CrumbError as exc:
                stats["blocked"] = True
                stats["error"] = str(exc)[:120]
                log(f"[fundamentals] kein Zugang: {exc}")
            except Exception as exc:  # noqa: BLE001
                consec_err += 1
                stats[f"{kind}_fail"] += 1
                entry[f"{kind}_err"], entry[f"{kind}_try"] = f"Fehler: {exc}"[:120], today_s
                if consec_err >= 10:
                    stats["blocked"] = True
                    stats["error"] = f"10 Fehler in Folge (zuletzt: {exc})"[:160]
                    log(f"[fundamentals] Abbruch: {stats['error']}")
            if params.get("delay_s"):
                sleep(params["delay_s"])
            if done % 100 == 0:
                log(f"[fundamentals] {kind}: {done} abgerufen")
    stats["seconds"] = round(clock() - t0, 1)
    return stats


# ------------------------------------------------------------------ Archiv (Point-in-Time-Daten für spätere Tests)
SNAP_FIELDS = ["symbol", "qs_at", "currency", "fin_currency", "price", "market_cap", "pe_ttm", "pe_fwd", "eps_ttm",
               "eps_fwd", "ev_ebitda", "ps", "pb", "roe", "roa", "op_margin", "profit_margin", "gross_margin", "fcf",
               "revenue", "de_pct", "current_ratio", "rev_growth", "eps_growth", "analysts",
               "eps0y_end", "eps0y_now", "eps0y_30d", "eps0y_90d", "eps1y_end", "eps1y_now", "eps1y_30d", "eps1y_90d",
               "up30_0y", "down30_0y", "up30_1y", "down30_1y", "rev0y_end", "rev0y_avg", "rev1y_end", "rev1y_avg",
               "surprise_last", "next_earnings", "ts_at", "roic_pre", "interest_cov", "dilution", "margin_change"]


def snapshot_rows(store: FundamentalsStore, syms, today: pd.Timestamp, max_age: float = 21):
    rows = []
    for s in syms:
        e = store.data.get(s) or {}
        q = e.get("qs")
        if not q or store.age(s, "qs", today) > max_age:
            continue
        tr = q.get("trend") or {}
        t0, t1 = tr.get("0y") or {}, tr.get("+1y") or {}
        hist = q.get("history") or []
        t = e.get("ts") or {}
        row = {"symbol": s, "qs_at": e.get("qs_at"), "ts_at": e.get("ts_at"),
               "eps0y_end": t0.get("end"), "eps0y_now": t0.get("eps_now"), "eps0y_30d": t0.get("eps_30d"), "eps0y_90d": t0.get("eps_90d"),
               "eps1y_end": t1.get("end"), "eps1y_now": t1.get("eps_now"), "eps1y_30d": t1.get("eps_30d"), "eps1y_90d": t1.get("eps_90d"),
               "up30_0y": t0.get("up30"), "down30_0y": t0.get("down30"), "up30_1y": t1.get("up30"), "down30_1y": t1.get("down30"),
               "rev0y_end": t0.get("end"), "rev0y_avg": t0.get("rev_avg"), "rev1y_end": t1.get("end"), "rev1y_avg": t1.get("rev_avg"),
               "surprise_last": hist[-1]["surprise"] if hist else None}
        for k in SNAP_FIELDS:
            if k not in row:
                row[k] = q.get(k) if k in q else t.get(k)
        rows.append(row)
    return rows


def write_weekly_snapshot(store: FundamentalsStore, syms, archive_dir: Path, today: pd.Timestamp,
                          min_coverage: float = 0.6) -> Path | None:
    iso = today.isocalendar()
    path = archive_dir / f"{iso[0]}-W{iso[1]:02d}.csv.gz"
    if path.exists():
        return None
    syms = list(syms)
    rows = snapshot_rows(store, syms, today)
    if not syms or len(rows) < min_coverage * len(syms):
        return None
    archive_dir.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=SNAP_FIELDS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in SNAP_FIELDS})
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    return path


def load_snapshot_near(archive_dir: Path, target: pd.Timestamp, tolerance_days: int = 12) -> tuple[pd.DataFrame | None, str | None]:
    """Archiv-Schnappschuss, dessen Woche am nächsten am Zieldatum liegt (für Revisionen aus eigener Historie)."""
    if not archive_dir.exists():
        return None, None
    best, best_d = None, None
    for p in archive_dir.glob("*-W*.csv.gz"):
        try:
            y, w = p.name.split(".")[0].split("-W")
            d = pd.Timestamp.fromisocalendar(int(y), int(w), 1)
        except Exception:  # noqa: BLE001
            continue
        dist = abs((d - target).days)
        if dist <= tolerance_days and (best_d is None or dist < abs((best_d - target).days)):
            best, best_d = p, d
    if best is None:
        return None, None
    try:
        df = pd.read_csv(best, dtype={"symbol": str}).set_index("symbol")
    except Exception:  # noqa: BLE001
        return None, None
    return df, best_d.strftime("%Y-%m-%d")
