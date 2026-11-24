"""Aktienuniversum: MSCI-World-Bestandteile aus der täglichen iShares-Bestandsliste.

Quelle 1: iShares MSCI World ETF (URTH) – Bestandsliste als CSV (BlackRock, öffentlich).
Quelle 2: zuletzt erfolgreich geladene Liste (im Repository archiviert).
Quelle 3: statisches Notfall-Universum (seed_universe.py), deutlich kleiner.

Die iShares-Liste liefert außerdem einen unabhängigen Schlusskurs je Aktie,
den die Pipeline zur Gegenprüfung der Yahoo-Kurse und der Ticker-Zuordnung nutzt.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

MIN_UNIVERSE = 500  # weniger Aktien => Liste vermutlich unvollständig

ISHARES_URLS = [
    "https://www.ishares.com/us/products/239696/ishares-msci-world-etf/1467271812596.ajax?fileType=csv&fileName=URTH_holdings&dataType=fund",
]

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
    "currency": ["currency", "market currency", "marktwährung", "marktwaehrung"],
    "isin": ["isin"],
    "sedol": ["sedol"],
    "cusip": ["cusip"],
}

# Börse (Teilstring, klein) -> Yahoo-Suffix. Reihenfolge wichtig (spezifisch vor allgemein).
EXCHANGE_SUFFIX = [
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
}

SUFFIX_CURRENCY = {
    "": "USD", ".TO": "CAD", ".V": "CAD", ".T": "JPY", ".L": "GBp", ".DE": "EUR", ".PA": "EUR",
    ".AS": "EUR", ".BR": "EUR", ".LS": "EUR", ".IR": "EUR", ".HE": "EUR", ".MI": "EUR",
    ".MC": "EUR", ".VI": "EUR", ".SW": "CHF", ".ST": "SEK", ".CO": "DKK", ".OL": "NOK",
    ".AX": "AUD", ".HK": "HKD", ".SI": "SGD", ".TA": "ILA", ".NZ": "NZD",
}

SUFFIX_COUNTRY = {
    "": "USA", ".TO": "Kanada", ".V": "Kanada", ".T": "Japan", ".L": "Großbritannien",
    ".DE": "Deutschland", ".PA": "Frankreich", ".AS": "Niederlande", ".BR": "Belgien",
    ".LS": "Portugal", ".IR": "Irland", ".HE": "Finnland", ".MI": "Italien", ".MC": "Spanien",
    ".VI": "Österreich", ".SW": "Schweiz", ".ST": "Schweden", ".CO": "Dänemark",
    ".OL": "Norwegen", ".AX": "Australien", ".HK": "Hongkong", ".SI": "Singapur",
    ".TA": "Israel", ".NZ": "Neuseeland",
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
}

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
        raise ValueError("Kopfzeile 'Ticker' nicht gefunden – Format der iShares-Datei hat sich geändert")
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
    for num in ("market_value", "weight", "price"):
        if num in df:
            df[num] = df[num].map(parse_number)
    return df, as_of


def yahoo_symbol(ticker: str, exchange: str, location: str) -> tuple[str | None, str]:
    """Liefert (Yahoo-Symbol, Suffix) oder (None, '') wenn keine Zuordnung möglich ist."""
    t = (ticker or "").strip().upper()
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


def build_from_ishares(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    warnings = []
    eq = df[df["asset_class"].str.lower().isin(["equity", "aktien"])].copy()
    recs = []
    unmapped = []
    for _, r in eq.iterrows():
        sym, suf = yahoo_symbol(r.get("ticker", ""), r.get("exchange", ""), r.get("location", ""))
        loc = str(r.get("location", "")).strip().lower()
        if sym is None:
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
            "universe_source": "iShares MSCI World (URTH)",
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


def load_universe(http_get, snapshot_dir: Path, offline: bool = False) -> UniverseResult:
    """http_get(url) -> str. Fällt schrittweise auf Archiv und Notfall-Universum zurück."""
    warnings: list[str] = []
    if not offline:
        for url in ISHARES_URLS:
            try:
                text = http_get(url)
                raw, as_of = parse_ishares_csv(text)
                frame, w = build_from_ishares(raw)
                warnings += w
                if len(frame) < MIN_UNIVERSE:
                    raise ValueError(f"nur {len(frame)} Aktien erkannt – Liste unvollständig")
                snapshot_dir.mkdir(parents=True, exist_ok=True)
                # nur stabile Spalten archivieren: Datei ändert sich nur, wenn sich die Indexmitglieder ändern
                stable = frame.drop(columns=[c for c in ("ref_price", "index_weight", "ref_currency") if c in frame])
                stable.to_csv(snapshot_dir / "latest.csv", index=False)
                month = pd.Timestamp.utcnow().strftime("%Y-%m")
                if not (snapshot_dir / f"{month}.csv").exists():
                    stable.to_csv(snapshot_dir / f"{month}.csv", index=False)
                return UniverseResult(frame, "iShares MSCI World (URTH)", as_of, warnings)
            except Exception as exc:  # noqa: BLE001 – jede Störung führt zum Fallback
                warnings.append(f"iShares-Liste nicht ladbar: {exc}")
    latest = snapshot_dir / "latest.csv"
    if latest.exists():
        frame = pd.read_csv(latest, keep_default_na=False, na_values=[""])
        frame["universe_source"] = "Archivierte iShares-Liste"
        frame["ref_price"] = None      # alter Referenzkurs ist für die Gegenprüfung ungeeignet
        frame["index_weight"] = None
        warnings.append("Universum aus Archiv verwendet (letzte erfolgreiche Liste)")
        return UniverseResult(frame, "Archiv", None, warnings)
    warnings.append("Notfall-Universum verwendet – deutlich kleiner als MSCI World")
    return UniverseResult(from_seed(), "Notfall-Universum", None, warnings)
