"""Live-Pfad der Pipeline mit nachgebildeten Antworten von iShares, Yahoo, EZB, SEC und Google News."""
import argparse
import io
import json
import zipfile

import numpy as np
import pandas as pd

from pipeline import details, prices, universe
from pipeline import run as runmod
from pipeline.synthetic import generate

SUFFIX_EXCHANGE = {"": ("NASDAQ", "United States"), ".DE": ("Xetra", "Germany"), ".PA": ("Nyse Euronext - Euronext Paris", "France"),
                   ".L": ("London Stock Exchange", "United Kingdom"), ".T": ("Tokyo Stock Exchange", "Japan"),
                   ".SW": ("SIX Swiss Exchange", "Switzerland"), ".TO": ("Toronto Stock Exchange", "Canada"),
                   ".AX": ("Asx - All Markets", "Australia"), ".ST": ("Nasdaq Omx Nordic", "Sweden")}
CUR = {"": "USD", ".DE": "EUR", ".PA": "EUR", ".L": "GBP", ".T": "JPY", ".SW": "CHF", ".TO": "CAD", ".AX": "AUD", ".ST": "SEK"}


def build_fixtures():
    uni, frames, currency, fx = generate("2026-11-20")
    asof = pd.Timestamp("2026-11-20")
    lines = ["iShares MSCI World ETF", 'Fund Holdings as of,"Nov 20, 2026"', "",
             "Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,CUSIP,ISIN,SEDOL,Price,Location,Exchange,Currency,FX Rate,Accrual Date"]
    for _, r in uni.iterrows():
        sym = r["symbol"]
        suf = "" if "." not in sym else "." + sym.split(".", 1)[1]
        tick = sym.split(".")[0]
        ex, loc = SUFFIX_EXCHANGE[suf]
        price = r["ref_price"] if pd.notna(r["ref_price"]) else ""
        lines.append(f'"{tick}","{r["name"].upper()}","Information Technology","Equity","1,000.00","0.10","1,000.00","10.00","-","{r["isin"]}","-","{price}","{loc}","{ex}","{CUR[suf]}","1.00","-"')
    lines.append('"USD","USD CASH","Cash and/or Derivatives","Cash","1.00","0.01","1.00","1.00","-","-","-","100.00","United States","-","USD","1.00","-"')
    csv_text = "\n".join(lines)
    ecb = io.BytesIO()
    with zipfile.ZipFile(ecb, "w") as zf:
        df = fx.copy()
        df.index.name = "Date"
        zf.writestr("eurofxref-hist.csv", df.sort_index(ascending=False).to_csv(float_format="%.4f"))
    charts = {}
    for sym, d in frames.items():
        d = d[d.index <= asof]
        cur = currency[sym]
        f = 100.0 if cur == "GBP" else 1.0  # Yahoo liefert London in Pence
        ts = [int((t + pd.Timedelta(hours=14)).timestamp()) for t in d.index]
        charts[sym] = {"chart": {"result": [{"meta": {"currency": "GBp" if cur == "GBP" else cur, "gmtoffset": 0,
                                                       "exchangeTimezoneName": "UTC"},
                                              "timestamp": ts,
                                              "indicators": {"quote": [{"close": list(d["close"] * f), "volume": list(d["volume"])}],
                                                             "adjclose": [{"adjclose": list(d["adj"] * f)}]}}], "error": None}}
    return csv_text, ecb.getvalue(), charts


class Resp:
    def __init__(self, code, js=None):
        self.status_code, self._js = code, js

    def json(self):
        return self._js


def test_live_pipeline_with_mocked_sources(tmp_path, monkeypatch):
    csv_text, ecb_zip, charts = build_fixtures()

    class FakeSession:
        def get(self, url, params=None, timeout=None):
            sym = url.rsplit("/", 1)[-1].replace("%2E", ".")
            return Resp(200, charts[sym]) if sym in charts else Resp(404)

    def fake_http_get(url, headers=None, binary=False, retries=3):
        if "ishares.com" in url:
            return csv_text
        if "eurofxref" in url:
            return ecb_zip
        if "news.google.com" in url:
            return ('<rss><channel><item><title>Demo meldet Rekord - Testquelle</title><link>https://example.org/n</link>'
                    '<pubDate>Fri, 20 Nov 2026 10:00:00 GMT</pubDate><source url="https://example.org">Testquelle</source></item></channel></rss>')
        raise RuntimeError(f"unerwartete URL {url}")

    def fake_http_json(url, headers=None):
        if "company_tickers" in url:
            return {"0": {"cik_str": 1234, "ticker": "DMO021", "title": "Demo"}}
        if "companyfacts" in url:
            return {"entityName": "Demo", "facts": {"us-gaap": {"Revenues": {"units": {"USD": [
                {"val": 100, "frame": "CY2024"}, {"val": 130, "frame": "CY2025"}]}},
                "NetIncomeLoss": {"units": {"USD": [{"val": 13, "frame": "CY2025"}]}},
                "EarningsPerShareDiluted": {"units": {"USD/shares": [{"val": 2.0, "frame": "CY2025"}]}}}}}
        if "submissions" in url:
            return {"cik": "1234", "sicDescription": "Test", "filings": {"recent": {"form": ["8-K"], "filingDate": ["2026-11-19"],
                    "accessionNumber": ["0000001234-26-000001"], "primaryDocument": ["a.htm"], "primaryDocDescription": ["8-K"]}}}
        raise RuntimeError(url)

    monkeypatch.setattr(universe, "MIN_UNIVERSE", 100)
    monkeypatch.setattr(runmod, "http_get", fake_http_get)
    monkeypatch.setattr(runmod, "http_json", fake_http_json)
    monkeypatch.setattr(prices, "make_session", lambda: (FakeSession(), "fake"))
    monkeypatch.setattr(prices.time, "sleep", lambda s: None)
    monkeypatch.setattr(details.time, "sleep", lambda s: None)
    monkeypatch.setattr(details, "fetch_yahoo_info", lambda sym: {"longBusinessSummary": "Test", "trailingPE": 20.0})
    monkeypatch.setattr(runmod.pd.Timestamp, "utcnow", classmethod(lambda cls: pd.Timestamp("2026-11-21", tz="UTC")))
    out, cache, archive = tmp_path / "site" / "data", tmp_path / "cache", tmp_path / "archive"
    args = argparse.Namespace(mode="live", out=str(out), cache=str(cache), archive=str(archive), asof=None,
                              full_refresh=False, skip_backtest=True, force_backtest=False, skip_details=False)
    monkeypatch.setattr(prices.time, "time", lambda: 1_800_000_000.0)
    rc = runmod.run(args)
    assert rc == 0
    status = json.loads((out / "status.json").read_text())
    screen = json.loads((out / "screen.json").read_text())
    assert status["overall"] in ("ok", "warnung"), status["messages"]
    assert screen["universe"]["source"].startswith("iShares")
    assert status["coverage"]["crosschecked"] > 250
    assert status["coverage"]["crosscheck_deviations"] >= 1          # absichtlich falscher Referenzkurs
    assert screen["candidates"] and screen["top_pick"]
    rows = {r[0]: dict(zip(screen["fields"], r)) for r in screen["rows"]}
    gb = [r for s, r in rows.items() if s.endswith(".L") and r["last_close"]]
    assert gb and all(r["currency"] == "GBP" for r in gb)          # Pence -> Pfund
    assert all(r["verified"] is not False for r in gb if "crosscheck" not in r["reasons"])
    det = json.loads((out / "details" / "DMO021.json").read_text())
    assert abs(det["fund"]["sec"]["metrics"]["revenue_growth"] - 0.3) < 1e-9
    assert det["news"][0]["title"] == "Demo meldet Rekord"
    assert (archive / "universe" / "latest.csv").exists() and (archive / "runs.log").exists()
    assert (cache / "last_good" / "screen.json").exists()
    # Zweiter Lauf: Yahoo komplett gesperrt -> Cache wird genutzt, ehrliche Kennzeichnung
    class Blocked:
        def get(self, url, params=None, timeout=None):
            return Resp(429)
    monkeypatch.setattr(prices, "make_session", lambda: (Blocked(), "fake"))
    monkeypatch.setattr(runmod.pd.Timestamp, "utcnow", classmethod(lambda cls: pd.Timestamp("2026-11-30", tz="UTC")))
    rc2 = runmod.run(args)
    status2 = json.loads((out / "status.json").read_text())
    assert any("gesperrt" in m["text"] for m in status2["messages"])
    assert status2["overall"] == "fehler" and rc2 != 0
    screen2 = json.loads((out / "screen.json").read_text())
    assert screen2["candidates"] == [] and screen2["top_pick"] is None   # keine Empfehlungen mit alten Daten
    assert np.isfinite(1.0)
