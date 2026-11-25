"""Live-Pfad der Pipeline mit nachgebildeten Antworten von iShares, Yahoo, EZB, SEC und Google News."""
import argparse
import io
import json
import zipfile

import numpy as np
import pandas as pd

from pipeline import details, prices, universe
from pipeline import run as runmod
from pipeline.synthetic import demo_fundamentals, generate

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
    def __init__(self, code, js=None, text=""):
        self.status_code, self._js, self.text = code, js, text

    def json(self):
        if self._js is None:
            raise ValueError("kein JSON")
        return self._js


def _w(v):
    return {"raw": v} if v is not None else {}


def qs_json(rec):
    """Demo-Kennzahlen im Antwortformat von Yahoo quoteSummary."""
    trend = [{"period": per, "endDate": t["end"],
              "earningsEstimate": {"avg": _w(t["eps_avg"]), "numberOfAnalysts": _w(t["eps_n"]), "growth": _w(t["eps_growth"])},
              "revenueEstimate": {"avg": _w(t["rev_avg"]), "numberOfAnalysts": _w(t["rev_n"]), "growth": _w(t["rev_growth"])},
              "epsTrend": {"current": _w(t["eps_now"]), "7daysAgo": _w(t["eps_7d"]), "30daysAgo": _w(t["eps_30d"]),
                           "60daysAgo": _w(t["eps_60d"]), "90daysAgo": _w(t["eps_90d"])},
              "epsRevisions": {"upLast7days": _w(t["up7"]), "upLast30days": _w(t["up30"]), "downLast30days": _w(t["down30"]),
                               "downLast7Days": _w(t["down7"])}} for per, t in rec["trend"].items()]
    hist = [{"quarter": {"raw": int(pd.Timestamp(h["quarter"]).timestamp())}, "epsActual": _w(h["eps_actual"]),
             "epsEstimate": _w(h["eps_est"]), "surprisePercent": _w(h["surprise"])} for h in rec["history"]]
    return {"quoteSummary": {"error": None, "result": [{
        "price": {"currency": rec["currency"], "regularMarketPrice": _w(rec["price"]), "marketCap": _w(rec["market_cap"]),
                  "longName": rec["name"]},
        "financialData": {"financialCurrency": rec["fin_currency"], "currentPrice": _w(rec["price"]),
                          "totalRevenue": _w(rec["revenue"]), "ebitda": _w(rec["ebitda"]), "freeCashflow": _w(rec["fcf"]),
                          "debtToEquity": _w(rec["de_pct"]), "currentRatio": _w(rec["current_ratio"]),
                          "returnOnEquity": _w(rec["roe"]), "returnOnAssets": _w(rec["roa"]),
                          "operatingMargins": _w(rec["op_margin"]), "profitMargins": _w(rec["profit_margin"]),
                          "revenueGrowth": _w(rec["rev_growth"]), "earningsGrowth": _w(rec["eps_growth"]),
                          "numberOfAnalystOpinions": _w(rec["analysts"])},
        "defaultKeyStatistics": {"forwardPE": _w(rec["pe_fwd"]), "forwardEps": _w(rec["eps_fwd"]), "trailingEps": _w(rec["eps_ttm"]),
                                 "priceToBook": _w(rec["pb"]), "enterpriseToEbitda": _w(rec["ev_ebitda"])},
        "summaryDetail": {"trailingPE": _w(rec["pe_ttm"]), "priceToSalesTrailing12Months": _w(rec["ps"])},
        "earningsTrend": {"trend": trend}, "earningsHistory": {"history": hist},
        "calendarEvents": {"earnings": {"earningsDate": [{"raw": int(pd.Timestamp(rec["next_earnings"]).timestamp())}]}},
    }]}}


def ts_json(t):
    """Demo-Jahreswerte im Antwortformat der Yahoo-Fundamentals-Zeitreihen (so gebaut, dass die Kennzahlen stimmen)."""
    def item(name, vals):
        return {"meta": {"type": [name]}, name: [{"asOfDate": d, "currencyCode": "USD", "reportedValue": {"raw": v}} for d, v in vals]}
    res = [item("annualDilutedAverageShares", [("2024-12-31", 1e9), ("2025-12-31", 1e9 * (1 + t["dilution"]))])]
    if t.get("roic_pre") is not None:
        rev, m = 1e10, t["op_margin_fy"]
        ebit = t["roic_pre"] * 5e9
        res += [item("annualTotalRevenue", [("2024-12-31", rev), ("2025-12-31", rev)]),
                item("annualOperatingIncome", [("2024-12-31", rev * (m - t["margin_change"])), ("2025-12-31", rev * m)]),
                item("annualEBIT", [("2025-12-31", ebit)]), item("annualInvestedCapital", [("2025-12-31", 5e9)]),
                item("annualInterestExpense", [("2025-12-31", ebit / t["interest_cov"])])]
    return {"timeseries": {"error": None, "result": res}}


def _setup(tmp_path, monkeypatch):
    csv_text, ecb_zip, charts = build_fixtures()
    uni, frames, _, _ = generate("2026-11-20")
    fund_recs = demo_fundamentals(uni, frames, "2026-11-20")
    seen = {"crumb": 0, "qs": 0, "ts": 0}

    class FakeSession:
        def get(self, url, params=None, timeout=None):
            if "fc.yahoo.com" in url:
                return Resp(404)
            if "getcrumb" in url:
                return Resp(200, text="crumb123")
            if "quoteSummary/" in url:
                assert params and params.get("crumb") == "crumb123"
                seen["qs"] += 1
                sym = url.rsplit("/", 1)[-1].replace("%2E", ".")
                return Resp(200, qs_json(fund_recs[sym]["qs"])) if sym in fund_recs else Resp(404)
            if "fundamentals-timeseries" in url:
                seen["ts"] += 1
                sym = url.rsplit("/", 1)[-1].replace("%2E", ".")
                return Resp(200, ts_json(fund_recs[sym]["ts"])) if sym in fund_recs else Resp(404)
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
    monkeypatch.setattr(prices.time, "time", lambda: 1_800_000_000.0)
    out, cache, archive = tmp_path / "site" / "data", tmp_path / "cache", tmp_path / "archive"
    args = argparse.Namespace(mode="live", out=str(out), cache=str(cache), archive=str(archive), asof=None,
                              full_refresh=False, skip_backtest=True, force_backtest=False, skip_details=False)
    return args, out, cache, archive, seen


def test_live_pipeline_with_mocked_sources(tmp_path, monkeypatch):
    args, out, cache, archive, seen = _setup(tmp_path, monkeypatch)
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
    # Autopilot: Monatsplan auch ohne Backtest (vorläufige Regel), archiviert
    apj = json.loads((out / "autopilot.json").read_text())
    assert apj["status"] == "ok" and apj["plan"]["available"] and apj["rule"]["provisional"]
    assert apj["plan"]["buy_list"] and apj["plan"]["status"]
    assert list((archive / "autopilot").glob("*.json"))
    # Stage 2: automatisch berechnet, über den echten Parser-Pfad (Crumb, quoteSummary, Zeitreihen)
    s2 = json.loads((out / "stage2.json").read_text())
    assert seen["qs"] > 250 and seen["ts"] > 100
    assert s2["status"] == "ok", s2["messages"]
    assert [r["symbol"] for r in s2["ranking"]] and {r["symbol"] for r in s2["ranking"]} == set(screen["candidates"])
    assert all(r["decision"]["code"] in ("EXCEPTIONAL", "STRONG_BUY", "WATCHLIST", "NO_ENTRY", "REJECT", "HARD_RISK",
                                         "INSUFFICIENT_DATA") for r in s2["ranking"])
    scores = [r["stage2"]["score"] for r in s2["ranking"] if r["stage2"]["score"] is not None]
    assert scores == sorted(scores, reverse=True)                    # finale Rangfolge nach Stage-2-Score
    assert s2["reference"]["fundamentals_coverage"] >= 0.6
    assert status["sources"]["fundamentals_stage2"]["ok"] is True
    assert status["stage2"]["scored"] == len(scores)
    assert (cache / "fundamentals.json.gz").exists()
    assert list((archive / "fundamentals").glob("*.csv.gz")), "Wochen-Schnappschuss fehlt"
    assert (archive / "stage2" / "latest.json").exists()
    assert json.loads((out / "methodology.json").read_text())["stage2"]["version"]
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
    s2b = json.loads((out / "stage2.json").read_text())
    assert s2b["status"] == "fehler" and s2b["ranking"] == [] and s2b["eligible"] == []
    assert np.isfinite(1.0)


def test_stage2_failure_does_not_break_stage1(tmp_path, monkeypatch):
    args, out, cache, archive, _ = _setup(tmp_path, monkeypatch)

    def boom(**kw):
        raise RuntimeError("absichtlicher Testfehler")
    monkeypatch.setattr(runmod, "stage2_block", boom)
    rc = runmod.run(args)
    assert rc == 0
    status = json.loads((out / "status.json").read_text())
    screen = json.loads((out / "screen.json").read_text())
    s2 = json.loads((out / "stage2.json").read_text())
    assert screen["candidates"] and screen["top_pick"]               # Stage 1 vollständig
    assert s2["status"] == "fehler" and "Testfehler" in s2["messages"][0]["text"]
    assert status["overall"] == "warnung" and any("Stage 2" in m["text"] for m in status["messages"])
