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
    assert "MDAX" not in parsed          # Anfangsliste ohne folgende Änderungstabelle wird nicht übernommen
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



def test_stoxx_real_layout_label_after_names():
    """Echter Aufbau (Sept. 2026): Namen, dann nur die Beschriftung „DAX®“, Tabellenkopf über zwei Zeilen."""
    w = lambda t, x, y: {"text": t, "x0": x, "x1": x + 6 * len(t), "top": y}
    toc = [w("1.", 50, 10), w("DAX®INDEX", 62, 10), w("COMPOSITION", 140, 10), w("3", 400, 10)]
    page = [w("HISTORICAL", 50, 5), w("INDEX", 120, 5), w("COMPOSITIONS", 160, 5), w("3/59", 500, 5)]
    page += [w("30", 50, 20), w("December", 65, 20), w("1987:", 120, 20), w("Initial", 155, 20), w("Composition", 195, 20)]
    page += [w(f"Firma{i}", 50 + (i % 3) * 170, 40 + (i // 3) * 15) for i in range(30)]
    y = 40 + 10 * 15 + 5
    page += [w("DAX®", 50, y)]
    y += 15
    page += [w("Date", 50, y), w("of", 75, y)]
    y += 12
    page += [w("change", 50, y), w("announcement", 150, y), w("Deletion", 300, y), w("Addition", 430, y)]
    page += [w("18.09.1989", 50, y + 15), w("-", 300, y + 15), w("-", 430, y + 15)]
    page += [w("18.09.1995", 50, y + 30), w("18.07.1995", 150, y + 30), w("Firma3", 300, y + 30), w("SAP", 430, y + 30)]
    esg = [w("1", 50, 20), w("March", 65, 20), w("2020:", 110, 20), w("Initial", 150, 20), w("Composition", 190, 20),
           w("Esg1", 50, 40), w("DAX®", 50, 60), w("50", 85, 60), w("ESG", 100, 60),
           w("Deletion", 300, 80), w("Addition", 430, 80), w("01.01.2021", 50, 95), w("Esg1", 300, 95), w("Esg2", 430, 95)]
    parsed = bu.parse_stoxx_words([toc, page, esg])
    assert list(parsed) == ["DAX"]
    assert len(parsed["DAX"]["initial"][1]) == 30
    assert parsed["DAX"]["changes"] == [("18.09.1989", [], []), ("18.09.1995", ["Firma3"], ["SAP"])]


def test_sp500_snapshots_and_renames():
    csv_text = ("date,tickers\n2010-01-04,\"AAA,BBB,FB,OLD\"\n2015-03-02,\"AAA,BBB,FB,NEW1\"\n"
                "2022-06-09,\"AAA,BBB,META,NEW1\"\n")
    snaps = bu.parse_sp500_snapshots(csv_text * 1 + "".join(f"2009-01-{d:02d},\"AAA,BBB,FB,OLD\"\n" for d in range(1, 29))
                                     + "".join(f"2008-{m:02d}-{d:02d},\"AAA,BBB,FB,OLD\"\n" for m in range(1, 13) for d in range(1, 7)))
    cur = pd.DataFrame({"ticker": ["AAA", "BBB", "META", "NEW1"], "name": ["A", "B", "Meta", "N"], "sector": "",
                        "added": pd.to_datetime(["1990-01-01", "1990-01-01", "2008-01-01", "2015-03-02"])})
    # FB taucht ab Datensatzbeginn auf -> keine sichere Zuordnung; mit späterem Beginn klappt sie
    assert bu.sp500_renames(snaps, cur) == {}
    snaps2 = [(pd.Timestamp("2007-01-02"), ["AAA", "BBB", "OLD"])] + snaps
    assert bu.sp500_renames(snaps2, cur) == {"FB": "META"}
    h = bu.sp500_from_snapshots(snaps2, cur, pd.Timestamp("2022-12-15"), first="2007-01")
    assert h["info"]["renamed"] == 1


def test_weight_coverage_and_currency_conditional():
    rows = [["BIG", "", "", "", 1, "USD", 900.0], ["S1", "", "", "", 1, "USD", 50.0], ["S2", "", "", "", 1, "USD", 50.0]]
    months = {"2024-01": rows, "2024-02": rows}
    start, cov = bu.coverage_start(months, {"BIG"})
    assert start == "2024-01" and abs(cov["2024-01"] - 0.9) < 1e-9          # 1 von 3 Titeln, aber 90 % Gewicht
    assert abs(bu.count_coverage(months, {"BIG"})["2024-01"] - 1 / 3) < 1e-9
    xml = NPORT.replace("<curCd>USD</curCd>", '<currencyConditional curCd="CAD" exchangeRt="1.35"/>')
    r = bu.parse_nport(xml)["rows"][0]
    assert r["cur"] == "CAD" and r["val_usd"] == 19000


def test_parse_nq_acwi_and_name_matching():
    from pathlib import Path
    raw = (Path(__file__).parent / "data_nq_sample.html").read_text()
    d = bu.parse_nq_acwi(raw)
    assert d["date"] == "2015-11-30"
    names = [r[0] for r in d["rows"]]
    assert "Sony Corp." not in names and "Exxon" not in names          # andere Fonds (ex US, Low Carbon) ignoriert
    assert "Apple Inc." in names                                          # Fortsetzungsseite gehört dazu
    assert not any(n.startswith(("iShares", "BlackRock")) for n in names)
    idx = bu.build_name_index([["I1", "Alphabet Inc Class A", "US"], ["I2", "Alphabet Inc Class C", "US"],
                               ["I3", "AES Corp/VA", "US"], ["I4", "America Movil SAB de CV", "MX"]], [])
    assert bu.match_name(idx, "Alphabet Inc. Class C", "US") == "I2"
    assert bu.match_name(idx, "AES Corp. (The)", "US") == "I3"
    assert bu.match_name(idx, "America Movil SAB de CV Series L", "MX") == "I4"
    assert bu.match_name(idx, "Unbekannt AG", "DE") is None


def test_bad_early_mappings():
    idx = pd.date_range("2014-01-01", "2020-12-31", freq="D")
    good = pd.Series(100.0, index=idx)
    wrong = pd.Series(100.0, index=idx)
    wrong[:"2016-12-31"] = 40.0                       # vor 2017 ein ganz anderer Kurs -> falsche Namenszuordnung
    ref = {"2015-05": [["G", "", "", "", 100.0, "USD", 1], ["W", "", "", "", 100.0, "USD", 1]],
           "2016-05": [["G", "", "", "", 100.0, "USD", 1], ["W", "", "", "", 100.0, "USD", 1]],
           "2019-10": [["G", "", "", "", 100.0, "USD", 1], ["W", "", "", "", 100.0, "USD", 1]]}
    bad, st = bu.bad_early_mappings(ref, {"G": good, "W": wrong}, lambda c, e: 1.0, "2019-10")
    assert bad == {"W"} and st["early_checked"] == 2


def test_parse_nq_real_layout_with_source_linebreaks():
    """Echte SEC-Dateien (Donnelley-HTML) haben Zeilenumbrüche mitten in Tabellenzeilen und Kapitälchen-Titel."""
    rows = "".join(f"<TR>\n<TD>Firma {i} Ltd.</TD>\n<TD></TD>\n<TD ALIGN=right>1{i:03d}</TD>\n<TD>$</TD>\n"
                   f"<TD ALIGN=right>2{i:03d}</TD>\n</TR>\n" for i in range(350))
    raw = ("<P><B>Schedule of Investments</B><FONT SIZE=1>(Unaudited)</FONT>\n</P>\n"
           "<P><B>i</B>S<FONT SIZE=2>HARES</FONT><SUP>&reg;</SUP>MSCI ACWI\nI<FONT SIZE=2>NDEX</FONT> F<FONT SIZE=2>UND"
           "</FONT></P>\n<P>October 31, 2010</P>\n<TABLE>\n<TR><TD>COMMON STOCKS&#151;98.24%</TD></TR>\n"
           "<TR><TD>AUSTRALIA&#151;3.40%</TD></TR>\n" + rows + "</TABLE>")
    d = bu.parse_nq_acwi(raw)
    assert d["date"] == "2010-10-31" and len(d["rows"]) == 350
    assert d["rows"][0] == ["Firma 0 Ltd.", "AU", 1000.0, 2000.0]


def test_episode_filter_reused_ticker():
    idx = pd.date_range("2016-01-01", "2026-06-30", freq="D")
    months = {f"{y}-{m:02d}": [["DELL", "", "", "", None, "USD"]] for y in (2010, 2011) for m in range(1, 13)}
    months.update({f"2025-{m:02d}": [["DELL", "", "", "", None, "USD"]] for m in range(1, 13)})
    out, st = bu.episode_filter(months, {"DELL": pd.Series(1.0, index=idx)})
    assert out["2010-05"][0][0] is None and out["2025-05"][0][0] == "DELL"
    assert st["episodes"] == 2 and st["episodes_without_prices"] == 1


def test_dedupe_isin_map_keeps_home_listing():
    from pipeline import bt_universes as bu
    imap = {"CNE1000003G1": "1398.HK", "CNE000001P37": "1398.HK", "US02079K3059": "GOOGL", "US02079K1079": "GOOGL",
            "GRS003003035": "NA.TO", "CA6330671034": "NA.TO", "US0378331005": "AAPL"}
    meta = {"CNE1000003G1": ("INDUSTRIAL AND COMMERCIAL BANK OF CHINA H", "HKD", "CN"),
            "CNE000001P37": ("INDUSTRIAL AND COMMERCIAL BANK OF CHINA A", "CNY", "CN"),
            "US02079K3059": ("ALPHABET INC CLASS A", "USD", "US"), "US02079K1079": ("ALPHABET INC CLASS C", "USD", "US"),
            "GRS003003035": ("NATIONAL BANK OF GREECE SA", "EUR", "GR"), "CA6330671034": ("NATIONAL BANK OF CANADA", "CAD", "CA"),
            "US0378331005": ("APPLE INC", "USD", "US")}
    uni_norm = {"GOOGL": bu.norm_full("Alphabet Inc Class A")}
    w = {"US02079K3059": 1.0, "US02079K1079": 1.2}
    losers = set(bu.dedupe_isin_map(imap, meta, uni_norm, w))
    assert losers == {"CNE000001P37", "US02079K1079", "GRS003003035"}


def test_match_name_ambiguous_prefers_first_filing_and_short_names():
    from pipeline import bt_universes as bu
    rows = [["US30233Q1085", "EXXONMOBIL HOLDINGS CORPORATION", "US", "USD", 1, 10.0],
            ["US30231G1022", "EXXON MOBIL CORPORATION", "US", "USD", 1, 500.0],
            ["GB0007980591", "BP PLC", "GB", "GBP", 1, 50.0]]
    idx = bu.build_name_index(rows, [])
    idx["first"] = {"US30231G1022": "2019-10", "GB0007980591": "2019-10", "US30233Q1085": "2026-04"}
    idx["w"] = {r[0]: r[5] for r in rows}
    assert bu.match_name(idx, "Exxon Mobil Corp.", "US") == "US30231G1022"
    assert bu.match_name(idx, "BP PLC", "GB") == "GB0007980591"
    idx2 = bu.build_name_index(rows, [])        # ohne Zeitinformation bleibt Mehrdeutiges unzugeordnet
    assert bu.match_name(idx2, "Exxon Mobil Corp.", "US") is None


def test_coverage_gap_reports_reasons():
    import pandas as pd
    from pipeline import bt_universes as bu
    raw = {"2020-01": [["A", "Alpha", "US", "", 1, "USD", 50.0], [None, "Unbekannt", "US", "", 1, "USD", 20.0],
                       ["C", "Gamma", "US", "", 1, "USD", 30.0]],
           "2020-02": [["A", "Alpha", "US", "", 1, "USD", 90.0], ["C", "Gamma", "US", "", 1, "USD", 10.0]]}
    fil = {"2020-01": [raw["2020-01"][0], raw["2020-01"][1], [None] + raw["2020-01"][2][1:]], "2020-02": raw["2020-02"]}
    close = {"C": pd.Series([1.0], index=[pd.Timestamp("2020-02-03")])}
    valid = {"A", "C"}
    start, cov = bu.coverage_start(fil, valid)
    assert start == "2020-02"
    g = bu.coverage_gap(raw, fil, valid, cov, start, close)
    assert g["month"] == "2020-01" and g["share"] == 0.5
    assert g["by_reason_pct"] == {"keine Kurse in diesem Zeitraum": 30.0, "keinem Kurskürzel zugeordnet": 20.0}
    assert g["missing"][0]["symbol"] == "C" and "ab 02/2020" in g["missing"][0]["why"]
