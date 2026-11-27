"""Aktienuniversum aus der täglichen iShares-Bestandsliste.

Standard (ab Pipeline 0.7.0): MSCI ACWI – Large und Mid Caps aus Industrie- und Schwellenländern.
Umschaltbar über config/universe.txt („acwi“ oder „world“).
Quelle 1: iShares-Bestandsliste als CSV (BlackRock, öffentlich). Bevorzugt eine Variante mit ISIN-Spalte,
          weil die ISIN für die Prüfung „in Deutschland handelbar“ gebraucht wird.
Quelle 2: zuletzt erfolgreich geladene Liste (im Repository archiviert).
Quelle 3: statisches Notfall-Universum (seed_universe.py), deutlich kleiner.

Die iShares-Liste liefert außerdem einen unabhängigen Schlusskurs je Aktie,
den die Pipeline zur Gegenprüfung der Yahoo-Kurse und der Ticker-Zuordnung nutzt.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

MIN_UNIVERSE = 500  # weniger Aktien => Liste vermutlich unvollständig

ISHARES_URLS = [
    "https://www.ishares.com/us/products/239696/ishares-msci-world-etf/latest-holdings.csv",
    "https://www.ishares.com/us/products/239696/x/latest-holdings.csv",
    "https://www.ishares.com/us/products/239696/ishares-msci-world-etf/1467271812596.ajax?fileType=csv&fileName=URTH_holdings&dataType=fund",
]

# MSCI ACWI: zuerst Seiten, deren Bestandsliste eine ISIN-Spalte hat (Schweiz/Luxemburg), dann ohne ISIN (UK, USA)
ACWI_URLS = [
    "https://www.ishares.com/ch/individual/en/products/251850/ishares-msci-acwi-ucits-etf/latest-holdings.csv",
    "https://www.ishares.com/ch/professionals/en/products/251850/ishares-msci-acwi-ucits-etf/latest-holdings.csv",
    "https://www.blackrock.com/lu/individual/products/251850/ishares-msci-acwi-ucits-etf/latest-holdings.csv",
    "https://www.ishares.com/uk/individual/en/products/251850/ishares-msci-acwi-ucits-etf/latest-holdings.csv",
    "https://www.ishares.com/us/products/239600/ishares-msci-acwi-etf/latest-holdings.csv",
    "https://www.ishares.com/us/products/239600/x/latest-holdings.csv",
]

# JSON-Variante der US-Bestandsliste: enthält je Position auch CUSIP/ISIN/SEDOL (die CSV nicht)
ISIN_JSON_URLS = {
    "acwi": ["https://www.ishares.com/us/products/239600/ishares-msci-acwi-etf/1467271812596.ajax?tab=all&fileType=json"],
    "world": ["https://www.ishares.com/us/products/239696/ishares-msci-world-etf/1467271812596.ajax?tab=all&fileType=json"],
}

UNIVERSES = {
    "world": {"label": "iShares MSCI World (URTH)", "urls": ISHARES_URLS, "min": 500},
    "acwi": {"label": "iShares MSCI ACWI", "urls": ACWI_URLS, "min": 1500},
}

COLUMN_ALIASES = {
    "ticker": ["ticker", "issuer ticker", "emittententicker"],
    "name": ["name"],
    "sector": ["sector", "sektor"],
    "asset_class": ["asset class", "anlageklasse"],
    "market_value": ["market value", "marktwert"],
    "weight": ["weight (%)", "gewichtung (%)"],
    "price": ["price", "kurs"],
    "location": ["location", "standort"],
    "exchange": ["exchange", "börse", "boerse"],
    "currency": ["market currency", "marktwährung", "marktwaehrung"],
    "price_currency": ["currency", "währung", "waehrung"],
    "fx_rate": ["fx rate", "devisenkurs", "wechselkurs"],
    "isin": ["isin"],
    "sedol": ["sedol"],
    "cusip": ["cusip"],
}

# Börse (Teilstring, klein) -> Yahoo-Suffix. Reihenfolge wichtig (spezifisch vor allgemein).
EXCHANGE_SUFFIX = [
    # Schwellenländer (vor den allgemeinen Einträgen, z. B. „bolsa de“)
    ("shanghai", ".SS"), ("shenzhen", ".SZ"),
    ("gretai", ".TWO"), ("taipei exchange", ".TWO"), ("taiwan", ".TW"),
    ("kosdaq", ".KQ"), ("korea", ".KS"),
    ("national stock exchange of india", ".NS"), ("nse india", ".NS"), ("bombay", ".BO"), ("bse ltd", ".BO"),
    ("bovespa", ".SA"), ("b3 s.a", ".SA"), ("sao paulo", ".SA"), ("são paulo", ".SA"), ("brasil bolsa", ".SA"),
    ("johannesburg", ".JO"),
    ("saudi", ".SR"), ("tadawul", ".SR"),
    ("mexican", ".MX"), ("bolsa mexicana", ".MX"),
    ("santiago", ".SN"), ("colombia", ".CL"), ("lima", ".LM"),
    ("thailand", ".BK"), ("bursa malaysia", ".KL"), ("indonesia", ".JK"), ("philippine", ".PS"),
    ("istanbul", ".IS"), ("warsaw", ".WA"), ("budapest", ".BD"), ("prague", ".PR"), ("athens", ".AT"),
    ("qatar", ".QA"), ("abu dhabi", ".AD"), ("dubai", ".AE"), ("kuwait", ".KW"), ("egyptian", ".CA"),
    ("nyse euronext - euronext paris", ".PA"), ("euronext paris", ".PA"),
    ("euronext amsterdam", ".AS"), ("euronext brussels", ".BR"), ("euronext lisbon", ".LS"),
    ("euronext dublin", ".IR"), ("irish stock exchange", ".IR"),
    ("nasdaq omx helsinki", ".HE"), ("helsinki", ".HE"),
    ("copenhagen", ".CO"), ("stockholm", ".ST"),
    ("oslo", ".OL"),
    ("xetra", ".DE"), ("deutsche b", ".DE"), ("frankfurt", ".DE"),
    ("london", ".L"),
    ("tokyo", ".T"),
    ("toronto", ".TO"), ("tsx venture", ".V"),
    ("six swiss", ".SW"), ("swiss", ".SW"),
    ("borsa italiana", ".MI"), ("milan", ".MI"),
    ("madrid", ".MC"), ("bolsa de", ".MC"),
    ("wiener", ".VI"), ("vienna", ".VI"),
    ("asx", ".AX"), ("australian securities", ".AX"),
    ("hong kong", ".HK"),
    ("singapore", ".SI"),
    ("tel aviv", ".TA"),
    ("new zealand", ".NZ"),
    ("nasdaq", ""), ("new york", ""), ("nyse", ""), ("cboe", ""), ("arca", ""), ("bats", ""),
]

LOCATION_SUFFIX = {
    "united states": "", "canada": ".TO", "japan": ".T", "united kingdom": ".L",
    "germany": ".DE", "france": ".PA", "netherlands": ".AS", "switzerland": ".SW",
    "italy": ".MI", "spain": ".MC", "sweden": ".ST", "denmark": ".CO", "finland": ".HE",
    "norway": ".OL", "belgium": ".BR", "portugal": ".LS", "austria": ".VI", "ireland": ".IR",
    "australia": ".AX", "hong kong": ".HK", "singapore": ".SI", "israel": ".TA",
    "new zealand": ".NZ",
    "taiwan": ".TW", "korea (south)": ".KS", "south korea": ".KS", "korea": ".KS", "india": ".NS", "brazil": ".SA",
    "south africa": ".JO", "saudi arabia": ".SR", "mexico": ".MX", "chile": ".SN", "colombia": ".CL",
    "thailand": ".BK", "malaysia": ".KL", "indonesia": ".JK", "philippines": ".PS", "turkey": ".IS",
    "poland": ".WA", "hungary": ".BD", "czech republic": ".PR", "greece": ".AT", "qatar": ".QA",
    "kuwait": ".KW", "egypt": ".CA",
}

SUFFIX_CURRENCY = {
    "": "USD", ".TO": "CAD", ".V": "CAD", ".T": "JPY", ".L": "GBp", ".DE": "EUR", ".PA": "EUR",
    ".AS": "EUR", ".BR": "EUR", ".LS": "EUR", ".IR": "EUR", ".HE": "EUR", ".MI": "EUR",
    ".MC": "EUR", ".VI": "EUR", ".SW": "CHF", ".ST": "SEK", ".CO": "DKK", ".OL": "NOK",
    ".AX": "AUD", ".HK": "HKD", ".SI": "SGD", ".TA": "ILA", ".NZ": "NZD",
    ".SS": "CNY", ".SZ": "CNY", ".TW": "TWD", ".TWO": "TWD", ".KS": "KRW", ".KQ": "KRW", ".NS": "INR",
    ".BO": "INR", ".SA": "BRL", ".JO": "ZAc", ".SR": "SAR", ".MX": "MXN", ".SN": "CLP", ".CL": "COP",
    ".LM": "PEN", ".BK": "THB", ".KL": "MYR", ".JK": "IDR", ".PS": "PHP", ".IS": "TRY", ".WA": "PLN",
    ".BD": "HUF", ".PR": "CZK", ".AT": "EUR", ".QA": "QAR", ".AD": "AED", ".AE": "AED", ".KW": "KWF",
    ".CA": "EGP",
}

SUFFIX_COUNTRY = {
    "": "USA", ".TO": "Kanada", ".V": "Kanada", ".T": "Japan", ".L": "Großbritannien",
    ".DE": "Deutschland", ".PA": "Frankreich", ".AS": "Niederlande", ".BR": "Belgien",
    ".LS": "Portugal", ".IR": "Irland", ".HE": "Finnland", ".MI": "Italien", ".MC": "Spanien",
    ".VI": "Österreich", ".SW": "Schweiz", ".ST": "Schweden", ".CO": "Dänemark",
    ".OL": "Norwegen", ".AX": "Australien", ".HK": "Hongkong", ".SI": "Singapur",
    ".TA": "Israel", ".NZ": "Neuseeland",
    ".SS": "China", ".SZ": "China", ".TW": "Taiwan", ".TWO": "Taiwan", ".KS": "Südkorea", ".KQ": "Südkorea",
    ".NS": "Indien", ".BO": "Indien", ".SA": "Brasilien", ".JO": "Südafrika", ".SR": "Saudi-Arabien",
    ".MX": "Mexiko", ".SN": "Chile", ".CL": "Kolumbien", ".LM": "Peru", ".BK": "Thailand", ".KL": "Malaysia",
    ".JK": "Indonesien", ".PS": "Philippinen", ".IS": "Türkei", ".WA": "Polen", ".BD": "Ungarn",
    ".PR": "Tschechien", ".AT": "Griechenland", ".QA": "Katar", ".AD": "VAE", ".AE": "VAE", ".KW": "Kuwait",
    ".CA": "Ägypten",
}

LOCATION_DE = {
    "united states": "USA", "canada": "Kanada", "japan": "Japan", "united kingdom": "Großbritannien",
    "germany": "Deutschland", "france": "Frankreich", "netherlands": "Niederlande",
    "switzerland": "Schweiz", "italy": "Italien", "spain": "Spanien", "sweden": "Schweden",
    "denmark": "Dänemark", "finland": "Finnland", "norway": "Norwegen", "belgium": "Belgien",
    "portugal": "Portugal", "austria": "Österreich", "ireland": "Irland", "australia": "Australien",
    "hong kong": "Hongkong", "singapore": "Singapur", "israel": "Israel", "new zealand": "Neuseeland",
    "luxembourg": "Luxemburg", "bermuda": "Bermuda", "jersey": "Jersey", "cayman islands": "Kaimaninseln",
    "curacao": "Curaçao", "macau": "Macau", "china": "China", "puerto rico": "Puerto Rico",
    "taiwan": "Taiwan", "korea (south)": "Südkorea", "south korea": "Südkorea", "korea": "Südkorea",
    "india": "Indien", "brazil": "Brasilien", "south africa": "Südafrika", "saudi arabia": "Saudi-Arabien",
    "mexico": "Mexiko", "chile": "Chile", "colombia": "Kolumbien", "peru": "Peru", "thailand": "Thailand",
    "malaysia": "Malaysia", "indonesia": "Indonesien", "philippines": "Philippinen", "turkey": "Türkei",
    "poland": "Polen", "hungary": "Ungarn", "czech republic": "Tschechien", "greece": "Griechenland",
    "qatar": "Katar", "united arab emirates": "VAE", "kuwait": "Kuwait", "egypt": "Ägypten",
}

# Schwellenländer (MSCI-Einstufung), für Anzeige und Auswertung
EMERGING = {"China", "Taiwan", "Südkorea", "Indien", "Brasilien", "Südafrika", "Saudi-Arabien", "Mexiko", "Chile",
            "Kolumbien", "Peru", "Thailand", "Malaysia", "Indonesien", "Philippinen", "Türkei", "Polen", "Ungarn",
            "Tschechien", "Griechenland", "Katar", "VAE", "Kuwait", "Ägypten"}

SECTOR_DE = {
    "information technology": "IT", "financials": "Finanzen", "health care": "Gesundheit",
    "consumer discretionary": "Zyklischer Konsum", "communication": "Kommunikation",
    "communication services": "Kommunikation", "industrials": "Industrie",
    "consumer staples": "Basiskonsum", "energy": "Energie", "utilities": "Versorger",
    "real estate": "Immobilien", "materials": "Rohstoffe",
    "IT": "IT", "FIN": "Finanzen", "HC": "Gesundheit", "CD": "Zyklischer Konsum",
    "COM": "Kommunikation", "IND": "Industrie", "CS": "Basiskonsum", "EN": "Energie",
    "UT": "Versorger", "RE": "Immobilien", "MAT": "Rohstoffe",
}

US_OVERRIDES = {
    "BRKB": "BRK-B", "BRK.B": "BRK-B", "BRK/B": "BRK-B", "BFB": "BF-B", "BF.B": "BF-B",
    "LENB": "LEN-B", "LEN.B": "LEN-B", "HEIA": "HEI-A", "HEI.A": "HEI-A",
    "MKCV": "MKC-V", "UHALB": "UHAL-B", "UHAL.B": "UHAL-B",
}

CLASS_TOKENS = (r"(CLASS [A-Z]|CL [A-Z]|SERIES [A-Z]|NON[- ]VOTING|NON VTG|PREFERRED|PREF|PRF|PFD|VORZUG|VZO|"
                r"SDR|ADR|REIT|UNITS?|PS|PC|NV|INC|CORP|CORPORATION|CO|LTD|LIMITED|AG|SA|PLC|SE|SPA|ASA|AB|"
                r"OYJ|KGAA|& CO|[A-Z])")


@dataclass
class UniverseResult:
    frame: pd.DataFrame
    source: str
    as_of: str | None
    warnings: list[str] = field(default_factory=list)


def parse_number(s: str) -> float | None:
    if s is None:
        return None
    s = str(s).strip().replace(" ", "")
    if s in ("", "-", "--", "N/A"):
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) != 3:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _norm_header(h: str) -> str:
    return h.strip().strip("﻿").strip('"').strip().lower()


def parse_ishares_csv(text: str) -> tuple[pd.DataFrame, str | None]:
    lines = text.splitlines()
    as_of = None
    header_idx = None
    for i, line in enumerate(lines[:40]):
        low = line.lower()
        if "holdings as of" in low or "bestände per" in low or "positionen per" in low:
            parts = next(csv.reader([line]))
            if len(parts) > 1:
                as_of = parts[1].strip()
        first = _norm_header(line.split(",")[0]) if line else ""
        if first in ("ticker", "emittententicker", "issuer ticker"):
            header_idx = i
            break
    if header_idx is None:
        head = text[:120].replace("\n", " ")
        kind = "HTML-Seite statt CSV" if "<html" in text[:2000].lower() else "unbekanntes Format"
        raise ValueError(f"Kopfzeile 'Ticker' nicht gefunden ({kind}: {head!r})")
    reader = csv.reader(io.StringIO("\n".join(lines[header_idx:])))
    header = [_norm_header(h) for h in next(reader)]
    colmap = {}
    for key, aliases in COLUMN_ALIASES.items():
        for j, h in enumerate(header):
            if h in aliases and key not in colmap:
                colmap[key] = j
    for required in ("ticker", "name", "asset_class"):
        if required not in colmap:
            raise ValueError(f"Spalte '{required}' fehlt in der iShares-Datei")
    rows = []
    for row in reader:
        if len(row) < max(colmap.values()) + 1 or not row[colmap["ticker"]].strip():
            if rows:
                break
            continue
        rec = {k: row[j].strip() for k, j in colmap.items()}
        rows.append(rec)
    df = pd.DataFrame(rows)
    for num in ("market_value", "weight", "price", "fx_rate"):
        if num in df:
            df[num] = df[num].map(parse_number)
    # US-Liste: Kurs in USD, FX Rate = Landeswährung je USD -> Kurs in Landeswährung umrechnen
    if "currency" not in df and "price_currency" in df:
        df["currency"] = df["price_currency"]
    if {"price", "fx_rate", "price_currency", "currency"} <= set(df.columns):
        conv = (df["price_currency"].str.upper() == "USD") & (df["currency"].str.upper() != "USD") & df["fx_rate"].notna()
        df.loc[conv, "price"] = df.loc[conv, "price"] * df.loc[conv, "fx_rate"]
    return df, as_of


def yahoo_symbol(ticker: str, exchange: str, location: str) -> tuple[str | None, str]:
    """Liefert (Yahoo-Symbol, Suffix) oder (None, '') wenn keine Zuordnung möglich ist."""
    t = (ticker or "").strip().upper().replace("*", "").strip()
    if not t or t in ("-", "CASH", "USD", "EUR"):
        return None, ""
    ex = (exchange or "").strip().lower()
    loc = (location or "").strip().lower()
    suffix = None
    for key, suf in EXCHANGE_SUFFIX:
        if key in ex:
            suffix = suf
            break
    if suffix is None:
        suffix = LOCATION_SUFFIX.get(loc)
    if suffix is None:
        return None, ""
    if ex.startswith("nasdaq omx nordic") or ex == "omx nordic exchange":
        suffix = LOCATION_SUFFIX.get(loc, suffix)
    if suffix == "":
        if t in US_OVERRIDES:
            return US_OVERRIDES[t], ""
        return re.sub(r"[./ ]", "-", t), ""
    if suffix == ".HK":
        digits = re.sub(r"\D", "", t)
        return (digits.zfill(4) + suffix, suffix) if digits else (None, "")
    if suffix == ".T":
        return t.replace(" ", "") + suffix, suffix
    if suffix in (".TW", ".TWO", ".KS", ".KQ", ".SS", ".SZ", ".SR", ".QA", ".KW") and re.fullmatch(r"\d+[A-Z]?", t.replace(" ", "")):
        return t.replace(" ", "") + suffix, suffix
    core = t.rstrip(".")
    core = re.sub(r"[./ ]+", "-", core)
    return core + suffix, suffix


def issuer_key(name: str, country: str) -> str:
    n = (name or "").upper()
    n = re.sub(r"[^A-Z0-9& ]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    prev = None
    while prev != n:
        prev = n
        n = re.sub(rf"\s{CLASS_TOKENS}$", "", n).strip()
    return f"{country}|{n}"


def build_from_ishares(df: pd.DataFrame, label: str = "iShares MSCI World (URTH)") -> tuple[pd.DataFrame, list[str]]:
    warnings = []
    eq = df[df["asset_class"].str.lower().isin(["equity", "aktien"])].copy()
    recs = []
    unmapped = []
    skipped_ru = 0
    for _, r in eq.iterrows():
        sym, suf = yahoo_symbol(r.get("ticker", ""), r.get("exchange", ""), r.get("location", ""))
        loc = str(r.get("location", "")).strip().lower()
        if sym is None:
            exch = str(r.get("exchange", ""))
            if "forts" in exch.lower() or "moscow" in exch.lower() or str(r.get("ticker", "")).strip() in ("-", ""):
                skipped_ru += 1          # russische Titel (seit 2022 eingefroren) und Platzhalter ohne Kürzel
                continue
            unmapped.append(f"{r.get('ticker')} ({r.get('exchange')})")
            continue
        country = LOCATION_DE.get(loc, SUFFIX_COUNTRY.get(suf, r.get("location", "")))
        sector_raw = str(r.get("sector", "")).strip()
        recs.append({
            "symbol": sym,
            "name": str(r.get("name", "")).strip().title(),
            "source_ticker": r.get("ticker"),
            "exchange": r.get("exchange", ""),
            "country": country,
            "sector": SECTOR_DE.get(sector_raw.lower(), sector_raw or "Unbekannt"),
            "currency_hint": SUFFIX_CURRENCY.get(suf, r.get("currency", "")),
            "isin": r.get("isin") or "",
            "index_weight": r.get("weight"),
            "ref_price": r.get("price"),
            "ref_currency": r.get("currency", ""),
            "universe_source": label,
            "emerging": country in EMERGING,
        })
    out = pd.DataFrame(recs)
    if unmapped:
        warnings.append(f"{len(unmapped)} Positionen ohne Ticker-Zuordnung: " + ", ".join(unmapped[:15]))
    if not out.empty:
        dup_sym = out[out.duplicated("symbol", keep="first")]
        if len(dup_sym):
            warnings.append(f"{len(dup_sym)} doppelte Symbole entfernt")
        out = out.drop_duplicates("symbol", keep="first")
        out["issuer_key"] = [issuer_key(n, c) for n, c in zip(out["name"], out["country"])]
    return out.reset_index(drop=True), warnings


def from_seed() -> pd.DataFrame:
    from .seed_universe import SEED
    recs = []
    for sym, name, sector in SEED:
        suf = "" if "." not in sym else "." + sym.split(".", 1)[1]
        recs.append({
            "symbol": sym, "name": name, "source_ticker": sym, "exchange": "",
            "country": SUFFIX_COUNTRY.get(suf, ""), "sector": SECTOR_DE.get(sector, sector),
            "currency_hint": SUFFIX_CURRENCY.get(suf, ""), "isin": "", "index_weight": None,
            "ref_price": None, "ref_currency": "", "universe_source": "Notfall-Universum (statisch)",
        })
    df = pd.DataFrame(recs).drop_duplicates("symbol")
    df["issuer_key"] = [issuer_key(n, c) for n, c in zip(df["name"], df["country"])]
    return df.reset_index(drop=True)


def _norm_name(x: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(x).upper())[:12]


def isin_map_from_json(text: str) -> dict:
    """Liest (Ticker, Name) -> ISIN aus der iShares-JSON-Bestandsliste. Formatunabhängig: je Zeile wird die erste
    gültige ISIN (mit Prüfziffer) genommen."""
    from .tradable import isin_valid
    js = json.loads(text.lstrip("\ufeff"))
    rows = js.get("aaData") if isinstance(js, dict) else js
    out = {}
    for row in rows or []:
        if not isinstance(row, list) or len(row) < 3:
            continue
        vals = [v.get("raw", v.get("display")) if isinstance(v, dict) else v for v in row]
        isin = next((v for v in vals if isinstance(v, str) and isin_valid(v.strip())), None)
        if isin and isinstance(vals[0], str):
            out.setdefault(vals[0].strip().upper(), []).append((_norm_name(vals[1]), isin.strip()))
    return out


def add_isins(frame: pd.DataFrame, http_get, kind: str) -> tuple[pd.DataFrame, str | None]:
    for url in ISIN_JSON_URLS.get(kind, []):
        try:
            m = isin_map_from_json(http_get(url))
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:120]
            continue
        if not m:
            last = "keine ISIN in der JSON-Liste"
            continue
        f = frame.copy()
        isins = []
        for t, n in zip(f["source_ticker"].astype(str).str.upper(), f["name"]):
            c = m.get(t.strip(), [])
            if len(c) == 1:
                isins.append(c[0][1])
            elif c:
                nn = _norm_name(n)
                hit = [i for nm, i in c if nm[:5] == nn[:5]]
                isins.append(hit[0] if len(hit) == 1 else "")
            else:
                isins.append("")
        f["isin"] = isins
        return f, None
    return frame, locals().get("last", "keine JSON-Liste")


def isins_from_sec(frame: pd.DataFrame, store: Path) -> tuple[pd.DataFrame, float]:
    """ISIN aus den SEC-Meldungen (N-PORT) des iShares MSCI ACWI ETF ergänzen – dieselben Daten wie im Backtest.
    Zuordnung über das dort ermittelte Symbol; zur Sicherheit muss der Firmenname grob passen (erste 4 Zeichen),
    sonst bleibt die ISIN leer (Aktie wird dann nicht geprüft, aber auch nicht entfernt)."""
    import gzip
    if not store.exists() or frame.empty:
        return frame, 0.0
    try:
        st = json.loads(gzip.decompress(store.read_bytes()).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return frame, 0.0
    imap = st.get("isin_map", {})
    by_sym: dict[str, tuple[str, str, str]] = {}
    fl = sorted(st.get("filings", {}).values(), key=lambda f: f.get("date") or "")
    home = {"DE": "DE", "MC": "ES", "PA": "FR", "AS": "NL", "MI": "IT", "L": "GB", "SW": "CH", "ST": "SE",
            "CO": "DK", "HE": "FI", "OL": "NO", "BR": "BE", "LS": "PT", "VI": "AT", "IR": "IE", "T": "JP",
            "HK": None, "AX": "AU", "TO": "CA", "NS": "IN", "BO": "IN", "KS": "KR", "KQ": "KR", "TW": "TW",
            "TWO": "TW", "SA": "BR", "MX": "MX", "JO": "ZA", "SR": "SA", "TA": "IL", "SI": "SG", "NZ": "NZ"}
    for f in fl[-1:]:                                # nur die neueste Meldung: keine veralteten ISINs
        for r in f.get("rows", []):
            sym = imap.get(r[0])
            if not sym or sym in by_sym:
                continue
            suf = sym.rsplit(".", 1)[1] if "." in sym else None
            want = home.get(suf) if suf else None
            if want and not r[0].startswith(want):
                continue                             # z. B. ENR.DE mit indischer ISIN -> verwerfen
            by_sym[sym] = (r[0], r[1], f.get("date") or "")
    from .bt_universes import norm_name

    def same(a: str, b: str) -> bool:
        x, y = norm_name(a), norm_name(b)
        k = min(4, len(x), len(y))
        return k >= 2 and x[:k] == y[:k]
    f = frame.copy()
    if "isin" not in f:
        f["isin"] = ""
    out = []
    for sym, name, cur in zip(f["symbol"], f["name"], f["isin"].astype(str)):
        if len(cur) == 12:
            out.append(cur)
            continue
        hit = by_sym.get(sym)
        out.append(hit[0] if hit and same(hit[1], name) else "")
    f["isin"] = out
    rel = ~f["symbol"].astype(str).str.endswith((".SS", ".SZ"))     # China-A wird ohnehin ausgeschlossen
    return f, float((f.loc[rel, "isin"].astype(str).str.len() == 12).mean()) if rel.any() else 0.0


def load_universe(http_get, snapshot_dir: Path, offline: bool = False, kind: str = "acwi") -> UniverseResult:
    """http_get(url) -> str. Fällt schrittweise auf Archiv und Notfall-Universum zurück."""
    warnings: list[str] = []
    spec = UNIVERSES.get(kind, UNIVERSES["acwi"])
    if not offline:
        best = None
        for url in spec["urls"]:
            try:
                text = http_get(url)
                raw, as_of = parse_ishares_csv(text)
                frame, w = build_from_ishares(raw, spec["label"])
                if len(frame) < spec["min"]:
                    raise ValueError(f"nur {len(frame)} Aktien erkannt – Liste unvollständig")
                has_isin = "isin" in frame and (frame["isin"].astype(str).str.len() == 12).mean() > 0.8
                cand = (frame, as_of, w, has_isin, url)
                if best is None or (has_isin and not best[3]):
                    best = cand
                if has_isin:
                    break
            except Exception as exc:  # noqa: BLE001 – jede Störung führt zum nächsten Versuch
                warnings.append(f"iShares-Liste nicht ladbar ({url.split('/products/')[0].split('//')[1]}): {str(exc)[:160]}")
        if best is not None:
            frame, as_of, w, has_isin, url = best
            if not has_isin:
                frame, err = add_isins(frame, http_get, kind)
                share = (frame["isin"].astype(str).str.len() == 12).mean() if "isin" in frame else 0.0
                has_isin = share > 0.8
                src = "iShares-JSON-Liste"
                if not has_isin:
                    frame, share = isins_from_sec(frame, snapshot_dir / "bt-acwi.json.gz")
                    has_isin, src = share > 0.8, "SEC-Meldungen (N-PORT) des iShares MSCI ACWI ETF"
                w = w + ([] if has_isin else
                         [f"Bestandsliste ohne ISIN – Prüfung „in Deutschland handelbar“ nicht möglich ({err or f'nur {share:.0%} zugeordnet'})"])
            warnings = w
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            # nur stabile Spalten archivieren: Datei ändert sich nur, wenn sich die Indexmitglieder ändern
            stable = frame.drop(columns=[c for c in ("ref_price", "index_weight", "ref_currency") if c in frame])
            stable.to_csv(snapshot_dir / f"latest-{kind}.csv", index=False)
            if kind == "world":
                stable.to_csv(snapshot_dir / "latest.csv", index=False)
            month = pd.Timestamp.utcnow().strftime("%Y-%m")
            if not (snapshot_dir / f"{month}-{kind}.csv").exists():
                stable.to_csv(snapshot_dir / f"{month}-{kind}.csv", index=False)
            return UniverseResult(frame, spec["label"], as_of, warnings)
    for name in (f"latest-{kind}.csv", "latest.csv"):
        latest = snapshot_dir / name
        if latest.exists():
            frame = pd.read_csv(latest, keep_default_na=False, na_values=[""])
            frame["universe_source"] = "Archivierte iShares-Liste"
            frame["ref_price"] = None      # alter Referenzkurs ist für die Gegenprüfung ungeeignet
            frame["index_weight"] = None
            warnings.append(f"Universum aus Archiv verwendet ({name})")
            return UniverseResult(frame, "Archiv", None, warnings)
    warnings.append("Notfall-Universum verwendet – deutlich kleiner als MSCI World")
    return UniverseResult(from_seed(), "Notfall-Universum", None, warnings)
