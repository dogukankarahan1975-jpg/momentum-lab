"""Prüfung „in Deutschland handelbar“ über die offizielle Liste der Deutschen Börse.

Quelle: Deutsche Börse, „T7 (Börse Frankfurt) Alle handelbaren Instrumente“ (CSV, kostenlos, öffentlich).
Trade Republic veröffentlicht keine Liste seiner handelbaren Aktien. Eine Notierung an der Börse Frankfurt
ist eine gute, aber keine vollständige Annäherung: Aktien ohne deutsche Notierung (z. B. chinesische A-Aktien)
werden ausgeschlossen; einzelne gelistete Aktien können bei Trade Republic trotzdem fehlen.

Das Dateiformat wird nicht vorausgesetzt: Es werden alle gültigen ISINs (mit Prüfziffer) aus der Datei gelesen.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

import pandas as pd

LIST_PAGE = "https://cashmarket.deutsche-boerse.com/cash-en/trading/Tradable-Instruments-Xetra/boersefrankfurt/4085964!search"
KNOWN_FILES = [
    "https://cashmarket.deutsche-boerse.com/resource/blob/2289108/bd7b5662bedf70820593bd9304e6a8d4/data/t7-xfra-BF-allTradableInstruments.csv",
    "https://cashmarket.deutsche-boerse.com/resource/blob/1790250/b6b59260473530de5da515d8d1308928/data/t7-xfra-BF-allTradableInstruments.zip",
]
MIN_ISINS = 3000
ISIN_RE = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}[0-9])\b")


def isin_valid(isin: str) -> bool:
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin or ""):
        return False
    digits = "".join(str(int(c, 36)) for c in isin[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == int(isin[-1])


def extract_isins(content: bytes) -> set[str]:
    if content[:2] == b"PK":
        out = set()
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            for n in z.namelist():
                out |= extract_isins(z.read(n))
        return out
    text = content.decode("utf-8", errors="ignore")
    return {m for m in ISIN_RE.findall(text) if isin_valid(m)}


def find_file_links(html: str) -> list[str]:
    links = re.findall(r'href="([^"]*t7-xfra-BF-allTradableInstruments\.(?:csv|zip))"', html)
    out = []
    for l in links:
        if l.startswith("/"):
            l = "https://cashmarket.deutsche-boerse.com" + l
        if l not in out:
            out.append(l)
    return out


def load_frankfurt_isins(http_get_bytes, http_get_text, log=print) -> tuple[set[str] | None, dict]:
    status = {"name": "Deutsche Börse – handelbare Instrumente Börse Frankfurt", "type": "official", "ok": False,
              "url": LIST_PAGE, "count": 0, "error": None}
    urls = []
    try:
        urls = find_file_links(http_get_text(LIST_PAGE))
    except Exception as exc:  # noqa: BLE001
        status["error"] = f"Übersichtsseite nicht ladbar: {str(exc)[:120]}"
    for u in urls + [k for k in KNOWN_FILES if k not in urls]:
        try:
            isins = extract_isins(http_get_bytes(u))
            if len(isins) >= MIN_ISINS:
                status.update(ok=True, count=len(isins), file=u, error=None)
                return isins, status
            status["error"] = f"nur {len(isins)} ISINs in {u.rsplit('/', 1)[-1]}"
        except Exception as exc:  # noqa: BLE001
            status["error"] = f"{u.rsplit('/', 1)[-1]}: {str(exc)[:120]}"
    log(f"[handelbar] Liste der Deutschen Börse nicht verfügbar: {status['error']}")
    return None, status


def apply_filter(universe: pd.DataFrame, isins: set[str] | None, archive: Path, today: str) -> tuple[pd.DataFrame, dict]:
    """Behält nur Aktien, deren ISIN an der Börse Frankfurt handelbar ist.

    Ohne frische Liste wird das zuletzt gespeicherte Ergebnis (höchstens 45 Tage alt) verwendet, sonst wird nicht
    gefiltert und das gekennzeichnet. China-A-Aktien (Shanghai/Shenzhen) werden immer ausgeschlossen, weil sie in
    Deutschland nicht gehandelt werden."""
    info = {"checked": False, "source": None, "kept": len(universe), "removed": 0, "removed_examples": [],
            "removed_cn_a": 0}
    u = universe.copy()
    cn_a = u["symbol"].str.endswith((".SS", ".SZ"))
    info["removed_cn_a"] = int(cn_a.sum())
    u = u[~cn_a]
    store = archive / "tradable_de.json"
    has_isin = "isin" in u and (u["isin"].astype(str).str.len() == 12).mean() > 0.8
    if not has_isin:
        info["note"] = "Bestandsliste ohne ISIN – Handelbarkeit nicht geprüft (nur China-A-Aktien ausgeschlossen)."
        info["kept"] = len(u)
        return u.reset_index(drop=True), info
    ok_set, src = None, None
    if isins is not None:
        ok_set = {i for i in u["isin"] if i in isins}
        src = f"Deutsche Börse, Stand {today}"
        archive.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps({"date": today, "isins": sorted(ok_set),
                                     "checked": sorted(set(u["isin"]))}, separators=(",", ":")))
    elif store.exists():
        js = json.loads(store.read_text())
        if (pd.Timestamp(today) - pd.Timestamp(js.get("date"))).days <= 45:
            checked = set(js.get("checked", []))
            # neue Indexmitglieder, die damals noch nicht geprüft wurden, bleiben drin (gekennzeichnet)
            ok_set = set(js.get("isins", [])) | {i for i in u["isin"] if i not in checked}
            src = f"gespeicherte Prüfung vom {js.get('date')}"
    if ok_set is None:
        info["note"] = "Liste der Deutschen Börse nicht verfügbar – Handelbarkeit diesmal nicht geprüft."
        info["kept"] = len(u)
        return u.reset_index(drop=True), info
    no_isin = u["isin"].astype(str).str.len() != 12
    keep = u["isin"].isin(ok_set) | no_isin          # ohne ISIN: nicht prüfbar, bleibt drin
    removed = u[~keep]
    info.update(checked=True, source=src, kept=int(keep.sum()), removed=int(len(removed)), unchecked=int(no_isin.sum()),
                removed_examples=[f"{n} ({c})" for n, c in zip(removed["name"].head(12), removed["country"].head(12))])
    return u[keep].reset_index(drop=True), info
