"""Tiingo (kostenloser Starter-Tarif, Registrierung nötig) – nur als Ergänzung für US-Aktien, die bei Yahoo keine
Kurse mehr haben (Pleiten, Übernahmen). Tiingo führt Kurse delisteter Titel, solange das Kürzel nicht neu vergeben ist.

Grenzen des Gratis-Tarifs (tiingo.com/about/pricing, Stand Nov. 2026): 50 Abrufe pro Stunde, 1.000 pro Tag,
500 verschiedene Symbole pro Monat, 1 GB pro Monat, nur private Nutzung. Wir bleiben deutlich darunter:
höchstens 40 Abrufe pro Lauf und 450 Symbole pro Kalendermonat. Jede Aktie wird nur EINMAL geladen und dann im
Repository unter archive/tiingo/ gespeichert (Kurse delisteter Aktien ändern sich nicht mehr).

Ohne Schlüssel (GitHub-Secret TIINGO_API_KEY) passiert nichts.
"""
from __future__ import annotations

import gzip
import io
import json
import os
import time
from pathlib import Path

import pandas as pd

API = "https://api.tiingo.com/tiingo/daily/{sym}/prices?startDate=1995-01-01&format=json"
MAX_PER_RUN = 40
MAX_PER_MONTH = 450


def api_key() -> str | None:
    k = (os.environ.get("TIINGO_API_KEY") or "").strip()
    return k or None


def to_tiingo(sym: str) -> str:
    return sym.replace(".", "-").lower()


def parse_prices(rows: list) -> pd.DataFrame | None:
    """Tiingo-JSON -> DataFrame wie bei Yahoo: close (nur splitbereinigt), adj (split- und dividendenbereinigt)."""
    if not rows:
        return None
    t = pd.DataFrame(rows)
    if "date" not in t or "close" not in t:
        return None
    t.index = pd.to_datetime(t["date"].astype(str).str[:10])
    sf = pd.to_numeric(t["splitFactor"], errors="coerce").fillna(1.0).replace(0, 1.0) if "splitFactor" in t \
        else pd.Series(1.0, index=t.index)
    later = sf[::-1].cumprod()[::-1].shift(-1).fillna(1.0)      # Produkt aller Splits NACH dem jeweiligen Tag
    close = pd.to_numeric(t["close"], errors="coerce") / later
    adj = pd.to_numeric(t.get("adjClose", t["close"]), errors="coerce")
    vol = pd.to_numeric(t["volume"], errors="coerce").fillna(0) if "volume" in t else pd.Series(0.0, index=t.index)
    df = pd.DataFrame({"close": close.values, "adj": adj.values, "volume": vol.values}, index=t.index)
    df = df[df["close"].notna() & (df["close"] > 0)].sort_index()
    return df if len(df) > 20 else None


class TiingoArchive:
    def __init__(self, root: Path):
        self.dir = root / "tiingo"
        self.state_p = self.dir / "state.json"
        self.state = json.loads(self.state_p.read_text()) if self.state_p.exists() else {}

    def path(self, sym: str) -> Path:
        return self.dir / f"{sym.replace('/', '_')}.csv.gz"

    def have(self) -> set[str]:
        return {p.name[:-7] for p in self.dir.glob("*.csv.gz")} if self.dir.exists() else set()

    def load(self, syms) -> dict[str, pd.DataFrame]:
        out = {}
        for s in syms:
            p = self.path(s)
            if p.exists():
                df = pd.read_csv(io.BytesIO(gzip.decompress(p.read_bytes())), index_col=0, parse_dates=True)
                if not df.empty:
                    out[s] = df[["close", "adj", "volume"]].astype(float)
        return out

    def save(self, sym: str, df: pd.DataFrame) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        buf = df.round({"close": 6, "adj": 6}).to_csv(date_format="%Y-%m-%d").encode()
        self.path(sym).write_bytes(gzip.compress(buf, compresslevel=9, mtime=0))

    def save_state(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_p.write_text(json.dumps(self.state, separators=(",", ":"), sort_keys=True))


def fill_missing(symbols: list[str], root: Path, today: pd.Timestamp, log=print, deadline: float = float("inf"),
                 session=None, sleep_s: float = 1.5) -> tuple[dict[str, pd.DataFrame], dict]:
    """Lädt fehlende US-Kurse von Tiingo (falls Schlüssel vorhanden) und gibt alle gespeicherten Tiingo-Kurse zurück."""
    arc = TiingoArchive(root)
    st = arc.state
    month = today.strftime("%Y-%m")
    if st.get("month") != month:
        st["month"], st["unique"] = month, []
    done = st.setdefault("done", {})
    info = {"key": bool(api_key()), "stored": 0, "fetched": 0, "not_found": 0, "errors": 0, "left_month": 0}
    key = api_key()
    todo = [s for s in symbols if s not in done and "." not in s]      # nur US-Kürzel (ohne Börsen-Endung)
    if key and todo:
        import requests
        sess = session or requests.Session()
        budget = min(MAX_PER_RUN, MAX_PER_MONTH - len(st["unique"]))
        n = 0
        for s in todo:
            if n >= budget or time.time() > deadline:
                break
            n += 1
            st["unique"].append(s)
            try:
                r = sess.get(API.format(sym=to_tiingo(s)), headers={"Authorization": f"Token {key}"}, timeout=40)
            except Exception as exc:  # noqa: BLE001
                info["errors"] += 1
                log(f"[tiingo] {s}: {type(exc).__name__}")
                continue
            if r.status_code == 404:
                done[s] = "none"
                info["not_found"] += 1
            elif r.status_code in (401, 403):
                log("[tiingo] Schlüssel abgelehnt – bitte das GitHub-Secret TIINGO_API_KEY prüfen")
                info["errors"] += 1
                st["unique"].pop()
                break
            elif r.status_code == 429:
                log("[tiingo] Abruf-Limit erreicht – Rest im nächsten Lauf")
                st["unique"].pop()
                break
            elif r.ok:
                df = parse_prices(r.json())
                if df is None:
                    done[s] = "none"
                    info["not_found"] += 1
                else:
                    arc.save(s, df)
                    done[s] = "ok"
                    info["fetched"] += 1
            else:
                info["errors"] += 1
            time.sleep(sleep_s)
        arc.save_state()
        log(f"[tiingo] {info['fetched']} geladen, {info['not_found']} ohne Daten, {info['errors']} Fehler; "
            f"diesen Monat {len(st['unique'])}/{MAX_PER_MONTH} Symbole")
    have = arc.load(sorted(set(symbols) & arc.have()))
    info["stored"] = len(have)
    info["left_month"] = max(0, MAX_PER_MONTH - len(st.get("unique", [])))
    info["open"] = sum(1 for s in symbols if s not in done and "." not in s)
    return have, info
