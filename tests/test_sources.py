import io
import json
import zipfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from pipeline import details, fx, prices, universe

ISHARES_SAMPLE = '''iShares MSCI World ETF
Fund Holdings as of,"Nov 21, 2026"
Inception Date,"Jan 10, 2012"
Shares Outstanding,"48,300,000.00"
Stock,"-"
Bond,"-"
Cash,"-"
Other,"-"

Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,CUSIP,ISIN,SEDOL,Price,Location,Exchange,Currency,FX Rate,Accrual Date
"NVDA","NVIDIA CORP","Information Technology","Equity","524,315,123.12","5.44","524,315,123.12","2,812,345.00","67066G104","US67066G1040","2379504","186.43","United States","NASDAQ","USD","1.00","-"
"BRKB","BERKSHIRE HATHAWAY INC CLASS B","Financials","Equity","70,123,456.00","0.73","70,123,456.00","140,000.00","084670702","US0846707026","2073390","500.88","United States","New York Stock Exchange Inc.","USD","1.00","-"
"7203","TOYOTA MOTOR CORP","Consumer Discretionary","Equity","30,000,000.00","0.31","30,000,000.00","1,500,000.00","-","JP3633400001","6900643","2,950.00","Japan","Tokyo Stock Exchange","JPY","154.10","-"
"BT.A","BT GROUP PLC","Communication","Equity","3,000,000.00","0.03","3,000,000.00","1,000,000.00","-","GB0030913577","3091357","1.95","United Kingdom","London Stock Exchange","GBP","0.79","-"
"VOLV B","VOLVO CLASS B","Industrials","Equity","5,000,000.00","0.05","5,000,000.00","200,000.00","-","SE0000115446","B1QH830","270.10","Sweden","Nasdaq Omx Nordic","SEK","10.90","-"
"700","TENCENT TEST","Communication","Equity","1.00","0.00","1.00","1.00","-","XX","X","400.00","Hong Kong","Hong Kong Exchanges And Clearing Ltd","HKD","7.80","-"
"MC","LVMH","Consumer Discretionary","Equity","20,000,000.00","0.2","20,000,000.00","30,000.00","-","FR0000121014","4061412","650.00","France","Nyse Euronext - Euronext Paris","EUR","0.93","-"
"GOOGL","ALPHABET INC CLASS A","Communication","Equity","1.00","1.8","1.00","1.00","-","US02079K3059","X","250.0","United States","NASDAQ","USD","1.00","-"
"GOOG","ALPHABET INC CLASS C","Communication","Equity","1.00","1.5","1.00","1.00","-","US02079K1079","X","251.0","United States","NASDAQ","USD","1.00","-"
"USD","USD CASH","Cash and/or Derivatives","Cash","5,000,000.00","0.05","5,000,000.00","5,000,000.00","-","-","-","100.00","United States","-","USD","1.00","-"

"The content contained herein is owned or licensed by BlackRock"
'''


def test_parse_ishares_csv_and_mapping():
    raw, as_of = universe.parse_ishares_csv(ISHARES_SAMPLE)
    assert as_of == "Nov 21, 2026"
    assert len(raw) == 10
    assert raw.loc[raw["ticker"] == "NVDA", "price"].iloc[0] == pytest.approx(186.43)
    assert raw.loc[raw["ticker"] == "7203", "price"].iloc[0] == pytest.approx(2950.0)
    frame, warns = universe.build_from_ishares(raw)
    syms = set(frame["symbol"])
    assert {"NVDA", "BRK-B", "7203.T", "BT-A.L", "VOLV-B.ST", "0700.HK", "MC.PA", "GOOGL", "GOOG"} <= syms
    assert "USD" not in syms  # Cash ausgeschlossen
    row = frame.set_index("symbol").loc["7203.T"]
    assert row["country"] == "Japan" and row["currency_hint"] == "JPY" and row["isin"] == "JP3633400001"
    keys = frame.set_index("symbol")["issuer_key"]
    assert keys["GOOGL"] == keys["GOOG"]
    assert keys["NVDA"] != keys["GOOG"]


def test_yahoo_symbol_cases():
    assert universe.yahoo_symbol("RR.", "London Stock Exchange", "United Kingdom")[0] == "RR.L"
    assert universe.yahoo_symbol("RCI.B", "Toronto Stock Exchange", "Canada")[0] == "RCI-B.TO"
    assert universe.yahoo_symbol("NOVO B", "Omx Nordic Exchange Copenhagen A/S", "Denmark")[0] == "NOVO-B.CO"
    assert universe.yahoo_symbol("SAP", "Xetra", "Germany")[0] == "SAP.DE"
    assert universe.yahoo_symbol("CRH", "New York Stock Exchange Inc.", "Ireland")[0] == "CRH"
    assert universe.yahoo_symbol("NESN", "SIX Swiss Exchange", "Switzerland")[0] == "NESN.SW"
    assert universe.yahoo_symbol("BHP", "Asx - All Markets", "Australia")[0] == "BHP.AX"
    assert universe.yahoo_symbol("NOKIA", "Nasdaq Omx Helsinki Ltd.", "Finland")[0] == "NOKIA.HE"
    assert universe.yahoo_symbol("X", "Unknown Exchange", "Atlantis")[0] is None


def test_parse_number_variants():
    assert universe.parse_number("1,234.5") == 1234.5
    assert universe.parse_number("1.234,5") == 1234.5
    assert universe.parse_number("2,950.00") == 2950.0
    assert universe.parse_number("12,5") == 12.5
    assert universe.parse_number("-") is None


def chart_payload(ts, close, adj, vol, offset=-18000, currency="USD", period=None):
    meta = {"currency": currency, "exchangeName": "NMS", "gmtoffset": offset,
            "exchangeTimezoneName": "America/New_York", "instrumentType": "EQUITY"}
    if period:
        meta["currentTradingPeriod"] = {"regular": period}
    return {"chart": {"result": [{"meta": meta, "timestamp": ts,
                                  "indicators": {"quote": [{"close": close, "volume": vol}],
                                                 "adjclose": [{"adjclose": adj}]}}], "error": None}}


def test_parse_chart_json_dates_and_partial_bar():
    # 14:30 UTC Handelsbeginn NY => lokales Datum
    ts = [1700577000, 1700663400, 1700749800]  # 21., 22., 23.11.2023 14:30 UTC
    js = chart_payload(ts, [10.0, None, 11.0], [9.5, None, 10.5], [100, 0, 200])
    df, info = prices.parse_chart_json(js, now=datetime(2023, 11, 24, tzinfo=timezone.utc))
    assert list(df.index.strftime("%Y-%m-%d")) == ["2023-11-21", "2023-11-23"]
    assert info["currency"] == "USD"
    # Markt noch offen => letzter (Teil-)Balken wird entfernt
    js2 = chart_payload(ts, [10.0, 10.2, 11.0], [9.5, 9.7, 10.5], [1, 1, 1],
                        period={"start": 1700749800, "end": 1700773200})
    df2, _ = prices.parse_chart_json(js2, now=datetime(2023, 11, 23, 17, 0, tzinfo=timezone.utc))
    assert df2.index[-1].strftime("%Y-%m-%d") == "2023-11-22"
    with pytest.raises(ValueError):
        prices.parse_chart_json({"chart": {"result": None, "error": {"description": "No data found"}}})


def test_merge_incremental_dividend_and_split():
    idx_old = pd.bdate_range("2024-01-01", "2024-03-29")
    old = pd.DataFrame({"close": 100.0, "adj": 95.0, "volume": 1000.0}, index=idx_old)
    idx_new = pd.bdate_range("2024-03-01", "2024-04-30")
    # Neue Dividende im April: Adj der Vergangenheit um 2 % gesenkt; 2:1-Split im April
    new = pd.DataFrame({"close": 50.0, "adj": 95.0 * 0.98 / 2, "volume": 2000.0}, index=idx_new)
    merged, info = prices.merge_incremental(old, new)
    assert info["close_factor"] == pytest.approx(0.5)
    assert info["adj_factor"] == pytest.approx(0.49)
    assert merged.loc["2024-01-02", "close"] == pytest.approx(50.0)
    assert merged.loc["2024-01-02", "adj"] == pytest.approx(95.0 * 0.49)
    assert merged.loc["2024-01-02", "volume"] == pytest.approx(2000.0)
    assert merged.index.is_unique and merged.index[-1] == idx_new[-1]
    _, info2 = prices.merge_incremental(old, new.loc["2024-04-15":])
    assert info2["needs_full"]


def test_normalize_units():
    df = pd.DataFrame({"close": [250.0], "adj": [240.0], "volume": [10.0]})
    out, cur = prices.normalize_units(df, "GBp")
    assert cur == "GBP" and out["close"].iloc[0] == 2.5 and out["volume"].iloc[0] == 10.0
    _, cur2 = prices.normalize_units(df, "USD")
    assert cur2 == "USD"


def test_update_prices_with_fake_session_and_cache(tmp_path):
    class Resp:
        def __init__(self, code, js=None):
            self.status_code, self._js = code, js

        def json(self):
            return self._js

    days = pd.bdate_range("2024-01-02", "2024-02-29")
    ts = [int((d + pd.Timedelta(hours=14, minutes=30)).timestamp()) for d in days]

    class Sess:
        calls = 0

        def get(self, url, params=None, timeout=None):
            Sess.calls += 1
            if "MISSING" in url:
                return Resp(404)
            cur = "GBp" if url.endswith(".L") else "USD"
            return Resp(200, chart_payload(ts, list(np.linspace(100, 110, len(ts))), list(np.linspace(99, 109, len(ts))),
                                           [1000] * len(ts), currency=cur))
    store = prices.PriceStore()
    res = prices.update_prices(["AAA", "BBB.L", "MISSING"], store, {"MISSING": "USD"}, False, session=Sess(),
                               delay_s=0, today=pd.Timestamp("2024-03-01"), log=lambda *a: None)
    assert res.stats["ok"] == 2 and res.stats["failed"] == 1
    assert res.currency["BBB.L"] == "GBP" and res.frames["BBB.L"]["close"].iloc[-1] == pytest.approx(1.10)
    p = tmp_path / "prices.pkl.gz"
    store.save(p)
    store2 = prices.PriceStore.load(p)
    assert set(store2.data) == {"AAA", "BBB.L"}


def test_parse_ecb_hist():
    csv = "Date,USD,JPY,GBP,\n2026-11-20,1.0512,160.12,0.8711,\n2026-11-19,1.0490,N/A,0.8700,\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("eurofxref-hist.csv", csv)
    df = fx.parse_ecb_hist(buf.getvalue())
    assert list(df.columns) == ["USD", "JPY", "GBP"]
    assert df.index[-1] == pd.Timestamp("2026-11-20")
    assert np.isnan(df.loc["2026-11-19", "JPY"])
    assert fx.to_eur_factor("USD", df.iloc[-1]) == pytest.approx(1 / 1.0512)
    on = fx.fx_on_index(df, pd.DatetimeIndex(["2026-11-21"]))
    assert on.loc["2026-11-21", "USD"] == pytest.approx(1.0512)


def test_parse_companyfacts_and_submissions():
    def fy(year, val, frame=True):
        return {"end": f"{year}-12-31", "val": val, "fy": year, "fp": "FY", "form": "10-K",
                "frame": f"CY{year}" if frame else None}
    facts = {"entityName": "Test Corp", "facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [fy(2022, 100), fy(2023, 120), fy(2024, 150), fy(2025, 180),
                                       {"val": 50, "frame": "CY2025Q3"}, {"val": 40, "frame": "CY2024Q3"}]}},
        "NetIncomeLoss": {"units": {"USD": [fy(2024, 15), fy(2025, 27)]}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": [fy(2024, 1.5), fy(2025, 2.7)]}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [fy(2025, 40)]}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [fy(2025, 10)]}},
        "StockholdersEquity": {"units": {"USD": [{"val": 100, "frame": "CY2024Q4I"}, {"val": 120, "frame": "CY2025Q4I"}]}},
        "LongTermDebt": {"units": {"USD": [{"val": 60, "frame": "CY2025Q4I"}]}},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [fy(2024, 10), fy(2025, 10.5)]}},
    }}}
    out = details.parse_companyfacts(facts, last_price=54.0)
    m = out["metrics"]
    assert m["fiscal_year"] == 2025
    assert m["revenue_growth"] == pytest.approx(0.2)
    assert m["revenue_cagr_3y"] == pytest.approx((180 / 100) ** (1 / 3) - 1)
    assert m["net_margin"] == pytest.approx(27 / 180)
    assert m["fcf"] == 30 and m["fcf_margin"] == pytest.approx(30 / 180)
    assert m["roe"] == pytest.approx(27 / 110)
    assert m["debt_to_equity"] == pytest.approx(0.5)
    assert m["dilution"] == pytest.approx(0.05)
    assert m["pe"] == pytest.approx(20.0)
    assert m["q_revenue_growth"] == pytest.approx(0.25)
    subs = {"cik": "320193", "sicDescription": "Electronic Computers", "filings": {"recent": {
        "form": ["4", "8-K", "10-Q"], "filingDate": ["2026-11-01", "2026-10-30", "2026-10-31"],
        "accessionNumber": ["a", "0000320193-26-000101", "0000320193-26-000100"],
        "primaryDocument": ["x.xml", "doc8k.htm", "doc10q.htm"], "primaryDocDescription": ["", "8-K", "10-Q"]}}}
    s = details.parse_submissions(subs)
    assert [f["form"] for f in s["filings"]] == ["8-K", "10-Q"]
    assert s["filings"][0]["url"].endswith("/320193/000032019326000101/doc8k.htm")
    assert s["filings"][0]["source_type"] == "official"


def test_parse_rss():
    xml = """<?xml version="1.0"?><rss><channel>
    <item><title>Firma steigt - Reuters</title><link>https://example.org/a</link>
    <pubDate>Mon, 23 Nov 2026 10:00:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
    <item><title>Älter</title><link>https://example.org/b</link><pubDate>Fri, 20 Nov 2026 10:00:00 GMT</pubDate></item>
    </channel></rss>"""
    items = details.parse_rss(xml)
    assert items[0]["title"] == "Firma steigt" and items[0]["source"] == "Reuters"
    assert items[0]["date"] == "2026-11-23" and items[1]["date"] == "2026-11-20"
    assert details.parse_rss("kaputt") == []
    assert details.short_name("ALPHABET INC CLASS A") == "ALPHABET"


NEW_FORMAT = """iShares MSCI World ETF
Fund Holdings as of,"Nov 23, 2026"
Inception Date,"Jan 10, 2012"
Shares Outstanding,"48,300,000.00"
Stock,"-"
Bond,"-"
Cash,"-"
Other,"-"
 
Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Price,Location,Exchange,Currency,FX Rate,Market Currency,Accrual Date
"AAPL","APPLE INC","Information Technology","Equity","552,982,329.20","5.74","552,982,329.20","1,615,160.00","342.37","United States","NASDAQ","USD","1.00","USD","-"
"8306","MITSUBISHI UFJ FINANCIAL GROUP INC","Financials","Equity","23,984,172.38","0.25","23,984,172.38","1,177,300.00","20.37","Japan","Tokyo Stock Exchange","USD","154.10","JPY","-"
"RR.","ROLLS-ROYCE HOLDINGS PLC","Industrials","Equity","15,497,715.92","0.16","15,497,715.92","919,697.00","16.85","United Kingdom","London Stock Exchange","USD","0.79","GBP","-"
"""


def test_parse_new_ishares_format_converts_usd_prices():
    raw, as_of = universe.parse_ishares_csv(NEW_FORMAT)
    frame, _ = universe.build_from_ishares(raw)
    f = frame.set_index("symbol")
    assert f.at["8306.T", "ref_price"] == pytest.approx(20.37 * 154.10)
    assert f.at["8306.T", "ref_currency"] == "JPY" and f.at["8306.T", "currency_hint"] == "JPY"
    assert f.at["RR.L", "ref_price"] == pytest.approx(16.85 * 0.79)
    assert f.at["AAPL", "ref_price"] == pytest.approx(342.37)


def test_html_instead_of_csv_is_reported():
    with pytest.raises(ValueError, match="HTML"):
        universe.parse_ishares_csv("<!DOCTYPE html><html><head></head></html>")


def test_crosscheck_uses_trading_day_of_list_not_later():
    """Regression: iShares-Liste vom Montag (in Japan Feiertag) darf nicht mit Dienstagskursen verglichen werden."""
    from pipeline.run import crosscheck
    idx = pd.to_datetime(["2026-11-19", "2026-11-20", "2026-11-23", "2026-11-24"])
    close = pd.DataFrame({
        "7203.T": [2900.0, 3000.0, np.nan, 3240.0],      # Mo Feiertag in Japan, Di +8 %
        "AAPL": [190.0, 195.0, 200.0, 210.0],            # Di +5 %
        "WRONG": [50.0, 50.0, 50.0, 50.0],               # falscher Ticker: 20 % daneben
        "BP.L": [4.0, 4.1, 4.2, 4.2],                    # Liste in Pence
    }, index=idx)
    uni = pd.DataFrame({"symbol": ["7203.T", "AAPL", "WRONG", "BP.L"], "ref_price": [3000.0, 200.0, 60.0, 420.0]})
    dev = crosscheck(close, uni, pd.Timestamp("2026-11-23"))
    assert abs(dev["7203.T"]) < 1e-9
    assert abs(dev["AAPL"]) < 1e-9
    assert abs(dev["WRONG"]) > 0.03
    assert abs(dev["BP.L"]) < 1e-9


def test_crosscheck_tolerates_one_day_list_convention():
    from pipeline.run import crosscheck
    idx = pd.to_datetime(["2026-11-20", "2026-11-23"])
    close = pd.DataFrame({"MSFT": [400.0, 420.0]}, index=idx)
    # Liste trägt das Datum 23.11., enthält aber den Kurs vom 20.11.
    dev = crosscheck(close, pd.DataFrame({"symbol": ["MSFT"], "ref_price": [400.0]}), pd.Timestamp("2026-11-23"))
    assert abs(dev["MSFT"]) < 1e-9
