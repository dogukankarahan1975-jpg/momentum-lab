"""Research-Daten je Aktie: Fundamentaldaten und Nachrichten (nur für die Detail-Auswahl).

Quellenkennzeichnung (wird in der App angezeigt):
  "official"  = offizieller Bericht / Pflichtmitteilung (SEC EDGAR XBRL bzw. SEC-Filings)
  "database"  = Datenbank eines Datenanbieters (Yahoo Finance, inoffiziell)
  "secondary" = Sekundärquelle (Nachrichtenaggregator, Analystenschätzung)
Fundamentaldaten ergänzen nur das Momentum-Screening (Risiko-Hinweise), sie verändern den Score nicht.
"""
from __future__ import annotations

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd

SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenue"],
    "net_income": ["NetIncomeLoss", "ProfitLoss", "ProfitLossAttributableToOwnersOfParent"],
    "op_income": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
    "gross_profit": ["GrossProfit"],
    "eps_diluted": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "DilutedEarningsLossPerShare"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment",
              "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
               "Equity", "EquityAttributableToOwnersOfParent"],
    "lt_debt": ["LongTermDebt", "LongTermDebtNoncurrent", "NoncurrentPortionOfNoncurrentBorrowings"],
    "st_debt": ["LongTermDebtCurrent", "DebtCurrent", "CurrentBorrowings"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding",
                       "WeightedAverageNumberOfSharesOutstandingDiluted"],
}
INSTANT = {"equity", "lt_debt", "st_debt", "cash"}


def sec_headers() -> dict:
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "momentum-lab")
    contact = os.environ.get("SEC_CONTACT") or f"{owner}@users.noreply.github.com"
    return {"User-Agent": f"{owner} MomentumLab {contact}",
            "Accept-Encoding": "gzip, deflate"}


def parse_company_tickers(js: dict) -> dict[str, int]:
    out = {}
    for rec in js.values():
        t = str(rec.get("ticker", "")).upper()
        if t:
            out[t] = int(rec["cik_str"])
    return out


def _series_for(facts: dict, concept_names: list[str], instant: bool) -> tuple[dict, dict, str | None]:
    """Gibt (Jahreswerte {Jahr: Wert}, Quartalswerte {(Jahr,Q): Wert}, Einheit) zurück."""
    for tax in ("us-gaap", "ifrs-full"):
        block = facts.get(tax, {})
        for name in concept_names:
            if name not in block:
                continue
            units = block[name].get("units", {})
            if not units:
                continue
            unit = next(iter(units))
            entries = units[unit]
            annual, quarterly = {}, {}
            for e in entries:
                frame = e.get("frame") or ""
                if instant:
                    m = re.fullmatch(r"CY(\d{4})Q(\d)I", frame)
                    if m:
                        quarterly[(int(m.group(1)), int(m.group(2)))] = e["val"]
                        if m.group(2) == "4":
                            annual[int(m.group(1))] = e["val"]
                else:
                    m = re.fullmatch(r"CY(\d{4})", frame)
                    if m:
                        annual[int(m.group(1))] = e["val"]
                    m = re.fullmatch(r"CY(\d{4})Q(\d)", frame)
                    if m:
                        quarterly[(int(m.group(1)), int(m.group(2)))] = e["val"]
            if annual or quarterly:
                return annual, quarterly, unit
    return {}, {}, None


def _growth(a, b):
    try:
        if a is None or b is None or b == 0:
            return None
        return a / abs(b) - 1.0 if b > 0 else None
    except Exception:  # noqa: BLE001
        return None


def parse_companyfacts(js: dict, last_price: float | None = None) -> dict:
    facts = js.get("facts", {})
    out = {"entity": js.get("entityName"), "annual": {}, "metrics": {}, "unit": None}
    series = {}
    for key, names in CONCEPTS.items():
        annual, quarterly, unit = _series_for(facts, names, key in INSTANT)
        series[key] = (annual, quarterly)
        if key == "revenue" and unit:
            out["unit"] = unit
    rev_a = series["revenue"][0]
    years = sorted(rev_a)[-4:] if rev_a else sorted(series["net_income"][0])[-4:]
    for y in years:
        out["annual"][str(y)] = {k: series[k][0].get(y) for k in CONCEPTS}
    m = out["metrics"]
    if years:
        y = years[-1]
        a = {k: series[k][0] for k in CONCEPTS}
        rev, ni = a["revenue"].get(y), a["net_income"].get(y)
        m["fiscal_year"] = y
        m["revenue"] = rev
        m["revenue_growth"] = _growth(rev, a["revenue"].get(y - 1))
        if len(years) >= 4 and a["revenue"].get(years[0]):
            n = years[-1] - years[0]
            try:
                m["revenue_cagr_3y"] = (rev / a["revenue"][years[0]]) ** (1 / n) - 1 if rev and n > 0 and rev > 0 and a["revenue"][years[0]] > 0 else None
            except Exception:  # noqa: BLE001
                m["revenue_cagr_3y"] = None
        m["net_income"] = ni
        m["net_income_growth"] = _growth(ni, a["net_income"].get(y - 1))
        m["net_margin"] = ni / rev if rev and ni is not None else None
        op = a["op_income"].get(y)
        m["op_margin"] = op / rev if rev and op is not None else None
        gp = a["gross_profit"].get(y)
        m["gross_margin"] = gp / rev if rev and gp is not None else None
        eps = a["eps_diluted"].get(y)
        m["eps_diluted"] = eps
        m["eps_growth"] = _growth(eps, a["eps_diluted"].get(y - 1))
        ocf, capex = a["ocf"].get(y), a["capex"].get(y)
        m["fcf"] = (ocf - (capex or 0)) if ocf is not None else None
        m["fcf_margin"] = m["fcf"] / rev if rev and m["fcf"] is not None else None
        eq, eq_prev = a["equity"].get(y), a["equity"].get(y - 1)
        if ni is not None and eq:
            avg_eq = (eq + eq_prev) / 2 if eq_prev else eq
            m["roe"] = ni / avg_eq if avg_eq and avg_eq > 0 else None
        debt = (a["lt_debt"].get(y) or 0) + (a["st_debt"].get(y) or 0)
        m["debt"] = debt if (a["lt_debt"].get(y) is not None or a["st_debt"].get(y) is not None) else None
        m["debt_to_equity"] = debt / eq if m["debt"] is not None and eq and eq > 0 else None
        cash = a["cash"].get(y)
        m["net_debt"] = (debt - cash) if m["debt"] is not None and cash is not None else None
        sh, sh_prev = a["diluted_shares"].get(y), a["diluted_shares"].get(y - 1)
        m["dilution"] = _growth(sh, sh_prev)
        if last_price and eps and eps > 0:
            m["pe"] = last_price / eps
        if last_price and sh and rev:
            m["ps"] = last_price * sh / rev
    # jüngstes Quartal vs. Vorjahresquartal
    rq = series["revenue"][1]
    if rq:
        lq = max(rq)
        prev = (lq[0] - 1, lq[1])
        m["last_quarter"] = f"{lq[0]} Q{lq[1]}"
        m["q_revenue"] = rq[lq]
        m["q_revenue_growth"] = _growth(rq[lq], rq.get(prev))
        eq_ = series["eps_diluted"][1]
        if lq in eq_:
            m["q_eps"] = eq_[lq]
            m["q_eps_growth"] = _growth(eq_[lq], eq_.get(prev))
    return out


def parse_submissions(js: dict, max_items: int = 10) -> dict:
    recent = (js.get("filings") or {}).get("recent") or {}
    forms = recent.get("form", [])
    cik = int(js.get("cik", 0) or 0)
    items = []
    keep = {"8-K", "10-Q", "10-K", "6-K", "20-F", "40-F", "DEF 14A", "S-1", "10-K/A", "10-Q/A"}
    for i, form in enumerate(forms):
        if form not in keep:
            continue
        acc = recent["accessionNumber"][i]
        doc = recent.get("primaryDocument", [""] * len(forms))[i]
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}" if doc else \
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
        items.append({
            "form": form,
            "date": recent["filingDate"][i],
            "title": (recent.get("primaryDocDescription", [""] * len(forms))[i] or form),
            "url": url,
            "source_type": "official",
            "source": "SEC EDGAR",
        })
        if len(items) >= max_items:
            break
    return {"sic": js.get("sicDescription"), "name": js.get("name"), "filings": items,
            "edgar_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=&dateb=&owner=include&count=40"}


def parse_rss(xml_text: str, max_items: int = 8) -> list[dict]:
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate")
        src_el = it.find("source")
        source = src_el.text.strip() if src_el is not None and src_el.text else ""
        try:
            date = parsedate_to_datetime(pub).astimezone(timezone.utc).strftime("%Y-%m-%d") if pub else None
        except Exception:  # noqa: BLE001
            date = None
        if source and title.endswith(" - " + source):
            title = title[: -(len(source) + 3)]
        if title and link:
            items.append({"title": title, "url": link, "date": date, "source": source or "Google News",
                          "source_type": "secondary"})
    items.sort(key=lambda x: x["date"] or "", reverse=True)
    return items[:max_items]


def short_name(name: str) -> str:
    n = re.sub(r"\b(Inc|Corp|Corporation|Ltd|Limited|Plc|Ag|Sa|Nv|Se|Spa|Asa|Ab|Oyj|Holdings?|Group|Co|Class [A-Z]|Cl [A-Z])\b\.?", "",
               name or "", flags=re.I)
    n = re.sub(r"[^\w&' -]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


YF_FIELDS = ["longBusinessSummary", "sector", "industry", "fullTimeEmployees", "website", "marketCap",
             "trailingPE", "forwardPE", "priceToBook", "profitMargins", "operatingMargins", "grossMargins",
             "returnOnEquity", "revenueGrowth", "earningsGrowth", "debtToEquity", "freeCashflow",
             "totalRevenue", "trailingEps", "forwardEps", "dividendYield", "beta", "financialCurrency",
             "earningsTimestamp", "earningsTimestampStart", "numberOfAnalystOpinions", "longName"]


def fetch_yahoo_info(sym: str) -> dict | None:
    try:
        import yfinance as yf
        info = yf.Ticker(sym).info or {}
    except Exception:  # noqa: BLE001
        return None
    if not info:
        return None
    return {k: info.get(k) for k in YF_FIELDS if info.get(k) is not None}


class DetailFetcher:
    def __init__(self, http_get_json, http_get_text, cache_dir: Path, today: pd.Timestamp, log=print):
        self.get_json = http_get_json
        self.get_text = http_get_text
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.today = today
        self.log = log
        self.cik_map = None
        self.status = {"sec": "nicht genutzt", "yahoo_info": "nicht genutzt", "news": "nicht genutzt"}
        self.counts = {"sec_ok": 0, "sec_fail": 0, "yahoo_ok": 0, "yahoo_fail": 0, "news_ok": 0, "news_fail": 0}

    def _cache(self, sym: str) -> dict:
        p = self.cache_dir / (re.sub(r"[^A-Za-z0-9._-]", "_", sym) + ".json")
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:  # noqa: BLE001
                return {}
        return {}

    def _save(self, sym: str, data: dict) -> None:
        p = self.cache_dir / (re.sub(r"[^A-Za-z0-9._-]", "_", sym) + ".json")
        p.write_text(json.dumps(data, default=str))

    def _age_days(self, iso: str | None) -> float:
        if not iso:
            return 1e9
        return (self.today - pd.Timestamp(iso)).days

    def ensure_cik_map(self):
        if self.cik_map is None:
            try:
                self.cik_map = parse_company_tickers(self.get_json(SEC_TICKERS, sec_headers()))
                self.status["sec"] = "ok"
            except Exception as exc:  # noqa: BLE001
                self.cik_map = {}
                self.status["sec"] = f"Fehler: {exc}"

    def fetch(self, sym: str, name: str, is_us: bool, last_price: float | None) -> dict:
        c = self._cache(sym)
        out = {"symbol": sym}
        # Fundamentaldaten (wöchentlich)
        if self._age_days(c.get("fund_date")) > 6:
            fund = {}
            if is_us:
                self.ensure_cik_map()
                cik = self.cik_map.get(sym.upper()) or self.cik_map.get(sym.upper().replace("-", "."))
                if cik:
                    try:
                        facts = self.get_json(SEC_FACTS.format(cik=cik), sec_headers())
                        fund["sec"] = parse_companyfacts(facts, last_price)
                        time.sleep(0.15)
                        subs = self.get_json(SEC_SUBMISSIONS.format(cik=cik), sec_headers())
                        fund["sec_filings"] = parse_submissions(subs)
                        fund["cik"] = cik
                        self.counts["sec_ok"] += 1
                        time.sleep(0.15)
                    except Exception as exc:  # noqa: BLE001
                        self.counts["sec_fail"] += 1
                        fund["sec_error"] = str(exc)[:200]
            info = fetch_yahoo_info(sym)
            if info:
                fund["yahoo"] = info
                self.counts["yahoo_ok"] += 1
            else:
                self.counts["yahoo_fail"] += 1
            if fund:
                c["fund"] = fund
                c["fund_date"] = self.today.strftime("%Y-%m-%d")
            time.sleep(0.3)
        else:
            # Kurs-abhängige Kennzahlen aktualisieren
            sec = (c.get("fund") or {}).get("sec")
            if sec and last_price:
                eps = sec.get("metrics", {}).get("eps_diluted")
                if eps and eps > 0:
                    sec["metrics"]["pe"] = last_price / eps
        # Nachrichten (täglich)
        if self._age_days(c.get("news_date")) >= 1:
            q = f'"{short_name(name)}" stock when:30d'
            try:
                xml_text = self.get_text(GOOGLE_NEWS.format(q=quote_plus(q)))
                c["news"] = parse_rss(xml_text)
                c["news_date"] = self.today.strftime("%Y-%m-%d")
                self.counts["news_ok"] += 1
            except Exception:  # noqa: BLE001
                self.counts["news_fail"] += 1
            time.sleep(0.4)
        self._save(sym, c)
        out.update({k: c.get(k) for k in ("fund", "fund_date", "news", "news_date")})
        return out

    def summary(self) -> dict:
        n = self.counts
        self.status["sec"] = self.status["sec"] if n["sec_ok"] + n["sec_fail"] == 0 else \
            f"{n['sec_ok']} ok / {n['sec_fail']} Fehler"
        self.status["yahoo_info"] = f"{n['yahoo_ok']} ok / {n['yahoo_fail']} Fehler"
        self.status["news"] = f"{n['news_ok']} ok / {n['news_fail']} Fehler"
        return self.status


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
