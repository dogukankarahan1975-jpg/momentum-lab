"""Backtest-Aktienlisten mit der damaligen Indexzusammensetzung (point in time).

Quellen (alle kostenlos):
- S&P 500: Wikipedia „List of S&P 500 companies“ – aktuelle Liste und Liste der Aufnahmen/Streichungen.
  Rückwärts rekonstruiert; nur Monate, in denen die Rekonstruktion 480–520 Aktien ergibt, gelten als gesichert.
- DAX-Familie (DAX, MDAX, SDAX, TecDAX): STOXX „Historical Index Compositions“ (offizielles PDF des Index-
  anbieters) – Anfangszusammensetzung und alle Änderungen. Firmennamen werden über die Yahoo-Suche Symbolen
  zugeordnet (Abweichungen in config/name_map.txt korrigierbar).
- MSCI ACWI: SEC-Meldungen (Formular N-PORT) des iShares MSCI ACWI ETF, vierteljährlich seit Ende 2019, mit ISIN.
  ISIN -> Börsensymbol über OpenFIGI (offizielle kostenlose Schnittstelle von Bloomberg).

Jede Liste wird gegen die Kursdaten geprüft: Ein Monat zählt nur, wenn mindestens 85 % der damaligen Mitglieder
passende Kurse haben. Der Backtest beginnt beim ersten Monat, ab dem das durchgehend gilt.
"""
from __future__ import annotations

import gzip
import io
import json
import math
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

BT_UNIVERSES = {
    "sp500": {"label": "S&P 500", "providers": ["sp500"]},
    "dax": {"label": "DAX-Familie (DAX, MDAX, SDAX, TecDAX)", "providers": ["dax"]},
    "spdax": {"label": "S&P 500 + DAX-Familie", "providers": ["sp500", "dax"]},
    "acwi": {"label": "MSCI ACWI (SEC-Meldungen)", "providers": ["acwi"]},
}
MIN_COVERAGE = 0.85
MIN_MONTHS = 24

WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
STOXX_PDF = "https://www.stoxx.com/document/Indices/Common/Indexguide/Historical_Index_Compositions.pdf"
SEC_MF = "https://www.sec.gov/files/company_tickers_mf.json"
SEC_SERIES_ATOM = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={series}&type=NPORT-P"
                   "&dateb=&owner=include&count=100&output=atom")
OPENFIGI = "https://api.openfigi.com/v3/mapping"
YAHOO_SEARCH = "https://query2.finance.yahoo.com/v1/finance/search?q={q}&quotesCount=8&newsCount=0"


# ------------------------------------------------------------------ allgemein
def store_path(archive_dir: Path, name: str) -> Path:
    return archive_dir / f"bt-{name}.json.gz"


def load_store(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def save_store(path: Path, d: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), 9))


def month_ends(first: str, last: str) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(first, last, freq="M")]


def last_month(today: pd.Timestamp) -> str:
    return (today.normalize().replace(day=1) - pd.Timedelta(days=1)).strftime("%Y-%m")


def _me(ym: str) -> pd.Timestamp:
    return pd.Period(ym, freq="M").to_timestamp(how="end").normalize()


def norm_name(x: str) -> str:
    x = unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode()
    x = re.sub(r"\b(AG|SE|KGAA|KG|GMBH|CO|INC|CORP|CORPORATION|LTD|LIMITED|PLC|NV|N V|SA|S A|HOLDINGS?|GROUP|THE|"
               r"VZ|ST|STAMMAKTIEN|VORZUGSAKTIEN|NAMENSAKTIEN|INHABERAKTIEN|CLASS [A-Z])\b", " ", x.upper())
    return re.sub(r"[^A-Z0-9]", "", x)


# ------------------------------------------------------------------ S&P 500 (Wikipedia)
def _flat(cols) -> list[str]:
    out = []
    for c in cols:
        if isinstance(c, tuple):
            parts = [str(p) for p in c if p and not str(p).startswith("Unnamed")]
            out.append(" ".join(dict.fromkeys(parts)))
        else:
            out.append(str(c))
    return out


def parse_sp500(html: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    tables = pd.read_html(io.StringIO(html))
    cur, chg = None, None
    for t in tables:
        cols = _flat(t.columns)
        low = [c.lower() for c in cols]
        if cur is None and any(c.startswith("symbol") for c in low) and any("security" in c for c in low):
            t = t.copy()
            t.columns = cols
            sym = cols[low.index(next(c for c in low if c.startswith("symbol")))]
            sec = cols[low.index(next(c for c in low if "security" in c))]
            sect = next((cols[i] for i, c in enumerate(low) if "sector" in c), None)
            cur = pd.DataFrame({"ticker": t[sym].astype(str).str.strip(), "name": t[sec].astype(str).str.strip(),
                                "sector": t[sect].astype(str) if sect else ""})
        elif chg is None and any("added" in c for c in low) and any("removed" in c for c in low):
            t = t.copy()
            t.columns = cols

            def pick(*keys):
                for i, c in enumerate(low):
                    if all(k in c for k in keys):
                        return cols[i]
                return None
            dcol = pick("date") or cols[0]
            out = pd.DataFrame({
                "date": pd.to_datetime(t[dcol].astype(str).str.replace(r"\[.*?\]", "", regex=True), errors="coerce"),
                "add": t[pick("added", "ticker")].astype(str) if pick("added", "ticker") else "",
                "add_name": t[pick("added", "security")].astype(str) if pick("added", "security") else "",
                "rem": t[pick("removed", "ticker")].astype(str) if pick("removed", "ticker") else "",
                "rem_name": t[pick("removed", "security")].astype(str) if pick("removed", "security") else "",
            })
            chg = out.dropna(subset=["date"])
    if cur is None or chg is None:
        raise ValueError("Tabellen auf der Wikipedia-Seite nicht gefunden")
    for c in ("add", "rem", "add_name", "rem_name"):
        chg[c] = chg[c].replace({"nan": "", "None": ""}).str.strip()
    return cur, chg.sort_values("date").reset_index(drop=True)


def yahoo_us(t: str) -> str:
    return str(t).strip().upper().replace(".", "-").replace("/", "-")


def sp500_history(cur: pd.DataFrame, chg: pd.DataFrame, today: pd.Timestamp, first: str = "1996-01") -> dict:
    """Monatsenden -> Mitglieder, rückwärts aus der aktuellen Liste und den Änderungen."""
    names = {yahoo_us(t): n for t, n in zip(cur["ticker"], cur["name"])}
    sectors = {yahoo_us(t): s for t, s in zip(cur["ticker"], cur["sector"])}
    members = {yahoo_us(t) for t in cur["ticker"]}
    months = month_ends(first, last_month(today))
    ch = chg.sort_values("date", ascending=False).to_dict("records")
    j = 0
    out = {}
    for ym in reversed(months):
        e = _me(ym)
        while j < len(ch) and ch[j]["date"] > e:      # Änderungen nach dem Stichtag zurücknehmen
            a, r = ch[j]["add"], ch[j]["rem"]
            if a:
                members.discard(yahoo_us(a))
            if r:
                members.add(yahoo_us(r))
                names.setdefault(yahoo_us(r), ch[j]["rem_name"] or r)
            j += 1
        out[ym] = sorted(members)
    sizes = {m: len(v) for m, v in out.items()}
    ok_from = None
    for ym in reversed(months):                        # zusammenhängend plausible Größe vom heutigen Monat rückwärts
        if 480 <= sizes[ym] <= 520:
            ok_from = ym
        else:
            break
    rows = {m: [[s, names.get(s, s), "USA", sectors.get(s, ""), None, "USD"] for s in v]
            for m, v in out.items() if ok_from and m >= ok_from}
    return {"source": "Wikipedia: List of S&P 500 companies (Aufnahmen/Streichungen)", "months": rows,
            "info": {"changes": len(chg), "plausible_from": ok_from,
                     "size_min": min(sizes[m] for m in rows) if rows else None,
                     "size_max": max(sizes[m] for m in rows) if rows else None}}


# ------------------------------------------------------------------ DAX-Familie (STOXX-PDF)
SECTIONS = {"DAX": "DAX", "TECDAX": "TecDAX", "MDAX": "MDAX", "SDAX": "SDAX"}
EXPECTED = {  # Sollgröße je Zeitraum (Stichtag der Regeländerung)
    "DAX": [("1987-12", 30), ("2021-09", 40)],
    "MDAX": [("1996-01", 70), ("2003-03", 50), ("2018-09", 60), ("2021-09", 50)],
    "SDAX": [("1999-06", 100), ("2003-03", 50), ("2018-09", 70)],
    "TecDAX": [("2003-03", 30)],
}
DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")


def _lines(words: list[dict], tol: float = 3.0) -> list[list[dict]]:
    words = sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
    lines, cur, top = [], [], None
    for w in words:
        if top is None or abs(w["top"] - top) <= tol:
            cur.append(w)
            top = w["top"] if top is None else top
        else:
            lines.append(sorted(cur, key=lambda x: x["x0"]))
            cur, top = [w], w["top"]
    if cur:
        lines.append(sorted(cur, key=lambda x: x["x0"]))
    return lines


def _cells(ln: list[dict], gap: float = 14.0) -> list[str]:
    """Teilt eine Zeile an großen Lücken in Zellen (mehrspaltige Namenslisten)."""
    out, cur, x_end = [], [], None
    for w in ln:
        x1 = w.get("x1", w["x0"] + 5 * len(w["text"]))
        if cur and w["x0"] - x_end > gap:
            out.append(" ".join(cur))
            cur = []
        cur.append(w["text"])
        x_end = x1
    if cur:
        out.append(" ".join(cur))
    return out


def parse_stoxx_words(pages: list[list[dict]]) -> dict:
    """pages: je Seite Wörter (text, x0, top) wie von pdfplumber. Ergebnis je Index:
    {"initial": (Datum, [Namen]), "changes": [(Datum, [gestrichen], [aufgenommen])]}"""
    res: dict = {}
    section = None
    mode = None
    cols = None
    rec = None
    for words in pages:
        for ln in _lines(words):
            text = " ".join(w["text"] for w in ln).strip()
            up = text.upper().replace("®", "")
            if "CONTENTS" in up:
                section = None
                continue
            m = re.match(r"^(?:\d+\.\s*)?(DAX|TECDAX|MDAX|SDAX)\s+INDEX COMPOSITION\s*$", up)
            if m:
                section = SECTIONS[m.group(1)]
                res.setdefault(section, {"initial": None, "changes": []})
                mode, cols, rec = "initial", None, None
                continue
            if re.search(r"INDEX COMPOSITION", up):      # andere Indizes (ESG usw.)
                section = None
                continue
            if section is None:
                continue
            if "DELETION" in up and "ADDITION" in up:
                xd = next(w["x0"] for w in ln if w["text"].upper().startswith("DELETION"))
                xa = next(w["x0"] for w in ln if w["text"].upper().startswith("ADDITION"))
                cols = (xd - 4, xa - 4)
                mode = "changes"
                continue
            if mode == "initial":
                dm = re.search(r"(\d{2}\.\d{2}\.\d{4})", text)
                if res[section]["initial"] is None:
                    if dm:
                        res[section]["initial"] = (dm.group(1), [])
                    continue
                if dm and not res[section]["initial"][1]:
                    continue
                for part in _cells(ln):
                    if part and not DATE_RE.match(part) and len(part) > 1 and not part.lower().startswith("page"):
                        res[section]["initial"][1].append(part.strip())
                continue
            if mode == "changes" and cols:
                first = ln[0]["text"]
                dele = " ".join(w["text"] for w in ln if cols[0] <= w["x0"] < cols[1]).strip()
                add = " ".join(w["text"] for w in ln if w["x0"] >= cols[1]).strip()
                if DATE_RE.match(first):
                    rec = [first, [], []]
                    res[section]["changes"].append(rec)
                elif rec is None:
                    continue
                for txt, lst in ((dele, rec[1]), (add, rec[2])):
                    if not txt or txt == "-":
                        continue
                    if lst and (txt[:1].islower() or lst[-1].endswith(("-", "&", " und", ",")) or txt.startswith(("&", "("))):
                        lst[-1] = (lst[-1] + ("" if lst[-1].endswith("-") else " ") + txt).strip()
                    else:
                        lst.append(txt)
    for v in res.values():
        v["changes"] = [(d, a, b) for d, a, b in v["changes"]]
    return res


def pdf_words(pdf_bytes: bytes) -> list[list[dict]]:
    import pdfplumber
    out = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            out.append([{"text": w["text"], "x0": w["x0"], "x1": w["x1"], "top": w["top"]}
                        for w in p.extract_words(keep_blank_chars=False, use_text_flow=False)])
    return out


def _clean_company(n: str) -> str:
    return re.sub(r"\s+", " ", n.replace("*", "")).strip()


def stoxx_history(parsed: dict, today: pd.Timestamp) -> dict:
    """Monatsenden -> Namen je Index (vorwärts aus Anfangszusammensetzung und Änderungen)."""
    out_names: dict[str, set] = {}
    info = {}
    last = last_month(today)
    for idx, v in parsed.items():
        if not v.get("initial"):
            continue
        d0 = pd.to_datetime(v["initial"][0], dayfirst=True)
        members = {_clean_company(n) for n in v["initial"][1]}
        chg = sorted(((pd.to_datetime(d, dayfirst=True), [_clean_company(x) for x in a], [_clean_company(x) for x in b])
                      for d, a, b in v["changes"]), key=lambda x: x[0])
        months = month_ends(d0.strftime("%Y-%m"), last)
        j = 0
        sizes = {}
        bad = 0
        for ym in months:
            e = _me(ym)
            while j < len(chg) and chg[j][0] <= e:
                for x in chg[j][1]:
                    members.discard(x)
                for x in chg[j][2]:
                    members.add(x)
                j += 1
            sizes[ym] = len(members)
            exp = [n for f, n in EXPECTED.get(idx, []) if f <= ym]
            if exp and abs(len(members) - exp[-1]) > 2:
                bad += 1
                continue
            out_names.setdefault(ym, set()).update(members)
        info[idx] = {"from": d0.strftime("%Y-%m"), "changes": len(chg), "months_bad_size": bad,
                     "size_now": sizes.get(last)}
    return {"names": {m: sorted(v) for m, v in out_names.items()}, "info": info}


def yahoo_symbol_for_name(http_json, name: str) -> str | None:
    q = re.sub(r"\s+", "+", re.sub(r"[^\w\s\-&]", " ", name)).strip("+")
    try:
        js = http_json(YAHOO_SEARCH.format(q=q))
    except Exception:  # noqa: BLE001
        return None
    nn = norm_name(name)
    best = None
    for qt in js.get("quotes", []):
        sym = str(qt.get("symbol", ""))
        if not (sym.endswith(".DE") or sym.endswith(".F")) or qt.get("quoteType") not in (None, "EQUITY"):
            continue
        ln = norm_name(qt.get("longname") or qt.get("shortname") or "")
        if not ln or not (ln[:6] == nn[:6] or nn.startswith(ln[:8]) or ln.startswith(nn[:8])):
            continue
        if best is None or (sym.endswith(".DE") and not best.endswith(".DE")):
            best = sym
    return best


def read_name_map(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                k, v = line.split("=", 1)
                out[norm_name(k)] = v.strip() or None
    return out


def dax_rows(hist_names: dict, name_to_sym: dict) -> dict:
    return {m: [[name_to_sym[n], n, "Deutschland", "", None, "EUR"] for n in v if name_to_sym.get(n)]
            for m, v in hist_names.items()}


# ------------------------------------------------------------------ MSCI ACWI (SEC N-PORT)
def find_series(mf_json: dict, ticker: str = "ACWI") -> tuple[int, str] | None:
    fields = mf_json.get("fields", [])
    for row in mf_json.get("data", []):
        rec = dict(zip(fields, row))
        if str(rec.get("symbol", "")).upper() == ticker:
            return int(rec["cik"]), str(rec["seriesId"])
    return None


def parse_atom_filings(atom: str) -> list[str]:
    acc = re.findall(r"/Archives/edgar/data/\d+/(\d{18})/", atom)
    acc += [a.replace("-", "") for a in re.findall(r"accession-n(?:umber|o)>\s*([\d-]{20})", atom)]
    return list(dict.fromkeys(acc))


def parse_nport(xml_text: str) -> dict:
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)

    def find(el, tag):
        return el.find(f".//{{*}}{tag}")
    rep = find(root, "repPdDate")
    series = find(root, "seriesId")
    rows = []
    for inv in root.iter():
        if not inv.tag.endswith("invstOrSec"):
            continue
        g = {c.tag.split("}")[-1]: c for c in inv}
        if (g.get("assetCat") is not None and g["assetCat"].text != "EC") or \
                (g.get("payoffProfile") is not None and g["payoffProfile"].text != "Long"):
            continue
        isin_el = find(inv, "isin")
        isin = isin_el.get("value") if isin_el is not None else None
        try:
            bal = float(g["balance"].text)
            val = float(g["valUSD"].text)
        except Exception:  # noqa: BLE001
            continue
        if not isin or bal <= 0:
            continue
        rows.append({"isin": isin, "name": (g["name"].text or "").strip() if g.get("name") is not None else "",
                     "country": g["invCountry"].text if g.get("invCountry") is not None else "",
                     "cur": g["curCd"].text if g.get("curCd") is not None else "",
                     "px_usd": val / bal})
    return {"date": rep.text if rep is not None else None, "series": series.text if series is not None else None,
            "rows": rows}


# Bloomberg-Börsenkürzel (OpenFIGI) -> Yahoo-Endung
EXCH_SUFFIX = {
    "US": "", "UN": "", "UW": "", "UQ": "", "UA": "", "UR": "", "UF": "", "UV": "",
    "JT": ".T", "JP": ".T", "HK": ".HK", "LN": ".L", "GY": ".DE", "GR": ".DE", "GF": ".F",
    "FP": ".PA", "NA": ".AS", "BB": ".BR", "IM": ".MI", "SQ": ".MC", "SM": ".MC", "SS": ".ST", "DC": ".CO",
    "NO": ".OL", "FH": ".HE", "SW": ".SW", "SE": ".SW", "VX": ".SW", "AV": ".VI", "PL": ".LS", "ID": ".IR",
    "CN": ".TO", "CT": ".TO", "AT": ".AX", "AU": ".AX", "NZ": ".NZ", "SP": ".SI", "IT": ".TA",
    "KS": ".KS", "KQ": ".KQ", "TT": ".TW", "TO": ".TWO", "IS": ".NS", "IN": ".NS", "IB": ".BO",
    "BZ": ".SA", "BS": ".SA", "SJ": ".JO", "MM": ".MX", "MF": ".MX", "AB": ".SR", "TB": ".BK", "MK": ".KL",
    "IJ": ".JK", "PM": ".PS", "TI": ".IS", "PW": ".WA", "CI": ".SN", "CB": ".CL", "QD": ".QA", "UH": ".AE",
    "DH": ".AE", "KK": ".KW", "EY": ".CA", "GA": ".AT", "HB": ".BD", "CP": ".PR", "PE": ".LM",
}
HOME = {"US": ["US", "UN", "UW", "UQ", "UA"], "JP": ["JT"], "GB": ["LN"], "DE": ["GY", "GR"], "FR": ["FP"],
        "CH": ["SW", "SE", "VX"], "NL": ["NA"], "CA": ["CN", "CT"], "AU": ["AT", "AU"], "HK": ["HK"],
        "CN": ["HK"], "KR": ["KS", "KQ"], "TW": ["TT", "TO"], "IN": ["IS", "IN", "IB"], "BR": ["BZ", "BS"],
        "ZA": ["SJ"], "MX": ["MM"], "SA": ["AB"], "TH": ["TB"], "MY": ["MK"], "ID": ["IJ"], "PH": ["PM"],
        "TR": ["TI"], "PL": ["PW"], "CL": ["CI"], "CO": ["CB"], "QA": ["QD"], "AE": ["UH", "DH"], "KW": ["KK"],
        "EG": ["EY"], "GR": ["GA"], "HU": ["HB"], "CZ": ["CP"], "IT": ["IM"], "ES": ["SQ", "SM"],
        "SE": ["SS"], "DK": ["DC"], "NO": ["NO"], "FI": ["FH"], "BE": ["BB"], "AT": ["AV"], "PT": ["PL"],
        "IE": ["ID", "LN"], "IL": ["IT"], "SG": ["SP"], "NZ": ["NZ"], "PE": ["PE"]}


def figi_to_yahoo(data: list[dict], country: str) -> str | None:
    prefs = HOME.get(country, [])
    cands = [d for d in data if d.get("exchCode") in EXCH_SUFFIX and d.get("ticker")]
    if not cands:
        return None
    cands.sort(key=lambda d: (prefs.index(d["exchCode"]) if d["exchCode"] in prefs else 99))
    d = cands[0]
    t, ex = str(d["ticker"]).upper(), d["exchCode"]
    suf = EXCH_SUFFIX[ex]
    if ex == "HK" and t.isdigit():
        t = t.zfill(4)
    t = t.replace("/", "-").replace(" ", "-")
    if suf in (".L",):
        t = t.rstrip(".").replace("-", "-")
    return t + suf


def map_isins_openfigi(http_post_json, isins: list[str], countries: dict, log=print, max_requests: int = 120) -> dict:
    out = {}
    req = 0
    for i in range(0, len(isins), 10):
        if req >= max_requests:
            break
        chunk = isins[i:i + 10]
        try:
            res = http_post_json(OPENFIGI, [{"idType": "ID_ISIN", "idValue": x} for x in chunk])
        except Exception as exc:  # noqa: BLE001
            log(f"[openfigi] Fehler: {str(exc)[:120]}")
            time.sleep(10)
            req += 1
            continue
        req += 1
        for x, r in zip(chunk, res if isinstance(res, list) else []):
            out[x] = figi_to_yahoo(r.get("data", []) or [], countries.get(x, "")) if isinstance(r, dict) else None
        time.sleep(2.6)       # ohne Schlüssel: höchstens 25 Anfragen pro Minute
    return out


# ------------------------------------------------------------------ Prüfung und Abdeckung
def validate_rows(months: dict, close: dict, fx_local_per_usd=None) -> tuple[set, dict]:
    """Ein Symbol gilt, wenn Kurse im Mitgliedszeitraum vorhanden sind; mit Referenzkursen (USD) zusätzlich,
    wenn das Verhältnis Yahoo/Referenz über die Stichtage stabil ist (Sprünge nur bei Splits)."""
    member_months: dict[str, list] = {}
    refs: dict[str, list] = {}
    for m, rows in months.items():
        e = _me(m)
        for r in rows:
            member_months.setdefault(r[0], []).append(e)
            if r[4] and r[4] > 0 and fx_local_per_usd is not None:
                refs.setdefault(r[0], []).append((e, r[4], r[5]))
    ok, st = set(), {"checked": 0, "no_prices": 0, "mismatch": 0, "ok": 0}
    for s, ms in member_months.items():
        st["checked"] += 1
        ser = close.get(s)
        if ser is None or ser.dropna().empty:
            st["no_prices"] += 1
            continue
        ser = ser.dropna()
        have = sum(1 for e in ms if ser.index[0] <= e <= ser.index[-1] + pd.Timedelta(days=10))
        if have < 0.8 * len(ms):
            st["no_prices"] += 1
            continue
        pts = refs.get(s)
        if pts:
            lr = []
            for e, pu, cur in pts:
                try:
                    k = fx_local_per_usd(cur, e)
                except Exception:  # noqa: BLE001
                    k = None
                v = ser.asof(e)
                if k and v and v > 0:
                    lr.append(math.log(v / (pu * k)))
            if len(lr) >= 3 and float(np.mean(np.abs(np.diff(lr)) < 0.12)) < 0.7:
                st["mismatch"] += 1
                continue
            if len(lr) in (1, 2) and min(abs(x - math.log(f)) for x in lr for f in
                                         (1, 2, 3, 4, 5, 10, 20, 100, .5, 1 / 3, .25, .2, .1, .05, .01)) > 0.15:
                st["mismatch"] += 1
                continue
        ok.add(s)
        st["ok"] += 1
    return ok, st


def coverage_start(months: dict, valid: set) -> tuple[str | None, dict]:
    cov = {m: (sum(1 for r in rows if r[0] in valid) / len(rows) if rows else 0.0) for m, rows in months.items()}
    start = None
    for m in sorted(cov, reverse=True):
        if cov[m] >= MIN_COVERAGE:
            start = m
        else:
            break
    return start, cov


def monthly_membership(months: dict, valid: set, start: str) -> dict:
    return {m: {r[0] for r in rows if r[0] in valid} for m, rows in months.items() if m >= start}


def fill_quarterly(months: dict, last: str) -> dict:
    """Vierteljährliche Stichtage auf jeden Monat übertragen (letzte bekannte Zusammensetzung gilt weiter)."""
    if not months:
        return {}
    keys = sorted(months)
    out = {}
    j = 0
    for m in month_ends(keys[0], last):
        while j + 1 < len(keys) and keys[j + 1] <= m:
            j += 1
        out[m] = months[keys[j]]
    return out
