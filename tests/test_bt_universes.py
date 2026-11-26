"""Backtest-Listen mit damaliger Zusammensetzung: S&P 500 (Wikipedia), DAX-Familie (STOXX-PDF), ACWI (SEC)."""
import io

import numpy as np
import pandas as pd
import pytest

from pipeline import bt_universes as bu

WIKI = """<html><body>
<table id="constituents"><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th></tr>
{cur}
</table>
<table id="changes">
<tr><th rowspan="2">Effective Date</th><th colspan="2">Added</th><th colspan="2">Removed</th><th rowspan="2">Reason</th></tr>
<tr><th>Ticker</th><th>Security</th><th>Ticker</th><th>Security</th></tr>
{chg}
</table></body></html>"""


def wiki_html():
    cur = [f"<tr><td>S{i:03d}</td><td>Firma {i}</td><td>IT</td></tr>" for i in range(499)] + \
          ["<tr><td>BRK.B</td><td>Berkshire</td><td>Fin</td></tr>"]
    chg = ['<tr><td>March 20, 2023</td><td>S001</td><td>Firma 1</td><td>OLD1</td><td>Alt 1</td><td>x</td></tr>',
           '<tr><td>June 1, 2021</td><td>S002</td><td>Firma 2</td><td>OLD2</td><td>Alt 2</td><td>x</td></tr>']
    return WIKI.format(cur="\n".join(cur), chg="\n".join(chg))


def test_sp500_reconstruction():
    cur, chg = bu.parse_sp500(wiki_html())
    assert len(cur) == 500 and len(chg) == 2
    h = bu.sp500_history(cur, chg, pd.Timestamp("2024-01-15"), first="2020-01")
    m = h["months"]
    syms = lambda ym: {r[0] for r in m[ym]}
    assert "BRK-B" in syms("2023-12")
    assert "OLD1" in syms("2023-02") and "S001" not in syms("2023-02")
    assert "OLD1" not in syms("2023-03") and "S001" in syms("2023-03")
    assert "OLD2" in syms("2021-05") and "S002" not in syms("2021-05")
    assert all(len(v) == 500 for v in m.values())


def make_pdf() -> bytes:
    """Nachbau des STOXX-Layouts: Anfangsliste vor der Überschrift, Seitenkopf, Änderungen mit Folgezeilen."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(50, 800, "CONTENTS"); c.drawString(50, 780, "1. DAX® INDEX COMPOSITION 3"); c.showPage()
    y = 800
    c.drawString(50, y, "HISTORICAL INDEX COMPOSITIONS OF EQUITY AND STRATEGY INDICES"); y -= 15
    c.drawString(50, y, "3/59"); y -= 20
    c.drawString(50, y, "30 December 1987: Initial Composition"); y -= 20
    names = ["Bayer. Hypo.- und Wechsel-Bank", "Feldmühle Nobel", "Nixdorf"] + [f"Firma {i}" for i in range(27)]
    for i in range(0, 30, 3):
        for j, n in enumerate(names[i:i + 3]):
            c.drawString(40 + j * 190, y, n)
        y -= 15
    c.drawString(50, y, "DAX®"); y -= 15
    c.drawString(50, y, "1. DAX® INDEX COMPOSITION"); y -= 25
    c.drawString(50, y, "Date of"); y -= 12
    c.drawString(50, y, "change"); c.drawString(150, y, "Date of"); y -= 12
    c.drawString(150, y, "announcement"); c.drawString(300, y, "Deletion"); c.drawString(430, y, "Addition"); y -= 15
    rows = [("18.09.1989", "-", "-", "-"), ("03.09.1990", "22.05.1990", "Feldmühle Nobel", "Metallgesellschaft"),
            (None, None, "Nixdorf *", "Preussag"), ("18.09.1995", "18.07.1995", "Firma 3", "SAP"),
            ("20.09.2021", "03.09.2021", "-", "Neu A")]
    for d1, d2, de, ad in rows:
        if d1:
            c.drawString(50, y, d1); c.drawString(150, y, d2)
        c.drawString(300, y, de); c.drawString(430, y, ad)
        y -= 15
    for k in range(9):
        c.drawString(430, y, f"Neu {k}"); y -= 15
    c.showPage()
    c.drawString(50, 800, "HISTORICAL INDEX COMPOSITIONS OF EQUITY AND STRATEGY INDICES")
    c.drawString(50, 780, "11 April 1994: Initial Composition"); c.drawString(50, 760, "Alpha"); c.drawString(50, 740, "3. MDAX® INDEX COMPOSITION")
    c.showPage(); c.save()
    return buf.getvalue()


def test_stoxx_pdf_parse_and_history():
    pytest.importorskip("reportlab")      # nur lokal zum Erzeugen des Test-PDFs
    pytest.importorskip("pdfplumber")
    parsed = bu.parse_stoxx_words(bu.pdf_words(make_pdf()))
    dax = parsed["DAX"]
    assert dax["initial"][0] == "30 December 1987" and len(dax["initial"][1]) == 30
    assert "Bayer. Hypo.- und Wechsel-Bank" in dax["initial"][1]
    assert dax["changes"][1] == ("03.09.1990", ["Feldmühle Nobel", "Nixdorf *"], ["Metallgesellschaft", "Preussag"])
    assert dax["changes"][3][2][:2] == ["Neu A", "Neu 0"] and len(dax["changes"][3][2]) == 10
    assert parsed["MDAX"]["initial"] == ("11 April 1994", ["Alpha"])
    h = bu.stoxx_history({"DAX": dax}, pd.Timestamp("2022-01-15"))
    assert "Preussag" in h["names"]["1990-09"] and "Nixdorf" not in h["names"]["1990-09"]
    assert "SAP" in h["names"]["1995-12"] and "Firma 3" not in h["names"]["1995-12"]
    assert len(h["names"]["2021-10"]) == 40 and h["info"]["DAX"]["months_bad_size"] == 0


def test_stoxx_words_parse_without_pdf():
    w = lambda t, x, y: {"text": t, "x0": x, "x1": x + 6 * len(t), "top": y}
    page = [w("30", 50, 10), w("December", 65, 10), w("1987:", 120, 10), w("Initial", 155, 10), w("Composition", 195, 10)]
    page += [w(f"Firma{i}", 50 + (i % 3) * 170, 30 + (i // 3) * 15) for i in range(30)]
    y = 30 + 10 * 15
    page += [w("1.", 50, y), w("DAX®", 62, y), w("INDEX", 100, y), w("COMPOSITION", 140, y)]
    y += 20
    page += [w("announcement", 150, y), w("Deletion", 300, y), w("Addition", 430, y)]
    page += [w("18.09.1995", 50, y + 15), w("18.07.1995", 150, y + 15), w("Firma3", 300, y + 15), w("SAP", 430, y + 15)]
    parsed = bu.parse_stoxx_words([page])
    assert len(parsed["DAX"]["initial"][1]) == 30 and parsed["DAX"]["changes"] == [("18.09.1995", ["Firma3"], ["SAP"])]


NPORT = """<?xml version="1.0"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nport"><formData>
<genInfo><seriesId>S000009999</seriesId><repPdDate>2023-07-31</repPdDate></genInfo>
<invstOrSecs>
<invstOrSec><name>Apple Inc</name><title>Apple Inc</title><identifiers><isin value="US0378331005"/></identifiers>
<balance>100</balance><units>NS</units><curCd>USD</curCd><valUSD>19000</valUSD><payoffProfile>Long</payoffProfile><assetCat>EC</assetCat><invCountry>US</invCountry></invstOrSec>
<invstOrSec><name>Cash</name><identifiers><isin value="XX0000000000"/></identifiers><balance>1</balance><valUSD>1</valUSD><assetCat>STIV</assetCat></invstOrSec>
</invstOrSecs></formData></edgarSubmission>"""


def test_nport_and_figi_mapping():
    d = bu.parse_nport(NPORT)
    assert d["date"] == "2023-07-31" and d["series"] == "S000009999"
    assert len(d["rows"]) == 1 and abs(d["rows"][0]["px_usd"] - 190) < 1e-9
    assert bu.find_series({"fields": ["cik", "seriesId", "classId", "symbol"],
                           "data": [[1100663, "S000009999", "C1", "ACWI"]]}) == (1100663, "S000009999")
    data = [{"ticker": "7203", "exchCode": "JT"}, {"ticker": "TOM", "exchCode": "GR"}]
    assert bu.figi_to_yahoo(data, "JP") == "7203.T"
    assert bu.figi_to_yahoo([{"ticker": "700", "exchCode": "HK"}], "CN") == "0700.HK"
    assert bu.figi_to_yahoo([{"ticker": "BRK/B", "exchCode": "UN"}], "US") == "BRK-B"


def test_validation_coverage_and_quarterly_fill():
    months = {"2020-01": [["A", "A", "", "", 10.0, "USD"], ["B", "B", "", "", 10.0, "USD"]],
              "2020-04": [["A", "A", "", "", 11.0, "USD"], ["C", "C", "", "", 5.0, "USD"]],
              "2020-07": [["A", "A", "", "", 12.0, "USD"], ["C", "C", "", "", 6.0, "USD"]],
              "2020-10": [["A", "A", "", "", 13.0, "USD"], ["C", "C", "", "", 7.0, "USD"]]}
    idx = pd.bdate_range("2019-01-01", "2021-01-31")
    a = pd.Series(np.interp(np.arange(len(idx)), [0, len(idx) - 1], [9, 14]), index=idx)
    for m, rows in months.items():
        a[bu._me(m)] = rows[0][4]
    a = a.sort_index()
    c = pd.Series(np.linspace(100, 1, len(idx)), index=idx)   # passt nicht zu 5/6/7 USD
    valid, st = bu.validate_rows(months, {"A": a, "C": c}, lambda cur, e: 1.0)
    assert valid == {"A"} and st["no_prices"] == 1 and st["mismatch"] == 1
    start, cov = bu.coverage_start(months, {"A", "C"})
    assert start == "2020-04" and cov["2020-01"] == 0.5
    q = bu.fill_quarterly(months, "2020-12")
    assert q["2020-05"] == months["2020-04"] and q["2020-12"] == months["2020-10"]

