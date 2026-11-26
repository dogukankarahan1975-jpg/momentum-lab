"""Historische Indexzusammensetzung („point in time“) für den Backtest.

Quelle: iShares-Bestandslisten zu vergangenen Stichtagen (Parameter asOfDate auf der US-Fondsseite, öffentlich).
  MSCI ACWI: iShares MSCI ACWI ETF (seit 03/2008)   MSCI World: iShares MSCI World ETF (seit 01/2012)
Der Backtest verwendet dann in jedem Monat nur die Aktien, die damals im Index waren.

Grenzen (werden angezeigt):
- Aktien, die es heute nicht mehr gibt, haben bei Yahoo meist keine Kurse mehr. Sie können im Backtest nicht
  ausgewählt werden (Rest-Verzerrung, siehe Korrektur im Simulator).
- Ein Symbol wird nur verwendet, wenn die Yahoo-Kurse zu den iShares-Kursen der Stichtage passen (schützt vor
  wiederverwendeten Tickern, die heute zu einer anderen Firma gehören).
- Die Liste wird schrittweise aufgebaut (mehrere Nächte), immer vom jüngsten Monat rückwärts.
"""
from __future__ import annotations

import gzip
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .universe import build_from_ishares, parse_ishares_csv

START = {"acwi": "2008-04", "world": "2012-02"}
URL = {
    "acwi": "https://www.ishares.com/us/products/239600/ishares-msci-acwi-etf/1467271812596.ajax?fileType=csv&fileName=ACWI_holdings&dataType=fund&asOfDate={d}",
    "world": "https://www.ishares.com/us/products/239696/ishares-msci-world-etf/1467271812596.ajax?fileType=csv&fileName=URTH_holdings&dataType=fund&asOfDate={d}",
}
MIN_ROWS = {"acwi": 1000, "world": 700}
MIN_MONTHS = 24        # darunter wird die historische Zusammensetzung noch nicht verwendet


def path_for(archive_dir: Path, kind: str) -> Path:
    return archive_dir / f"history-{kind}.json.gz"


def load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"version": 1, "months": {}, "failed": {}, "dead": {}}


def save(path: Path, h: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(h, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), 9))


def month_list(start: str, today: pd.Timestamp) -> list[str]:
    last = (today.normalize().replace(day=1) - pd.Timedelta(days=1)).strftime("%Y-%m")
    return [p.strftime("%Y-%m") for p in pd.period_range(start, last, freq="M")]


def _weekdays_at_month_end(ym: str, n: int = 6) -> list[pd.Timestamp]:
    end = pd.Period(ym, freq="M").to_timestamp(how="end").normalize()
    days = pd.bdate_range(end - pd.Timedelta(days=12), end)
    return list(reversed(days))[:n]


def update_history(http_get, path: Path, kind: str, today: pd.Timestamp, max_downloads: int = 80,
                   log=print) -> tuple[dict, dict]:
    """Lädt fehlende Monats-Bestandslisten nach (jüngste zuerst). Gibt (Historie, Info) zurück."""
    h = load(path)
    months = month_list(START[kind], today)
    if h.get("disabled_until") and today < pd.Timestamp(h["disabled_until"]):
        cov = coverage(h, months)
        return h, {"kind": kind, "months_total": len(months), "months_have": len(h["months"]), "downloads": 0,
                   "coverage_from": cov[0], "coverage_to": cov[1], "coverage_months": cov[2],
                   "error": f"iShares liefert keine alten Listen (nächster Versuch ab {h['disabled_until']})"}
    todo = []
    for m in reversed(months):
        if m in h["months"]:
            continue
        f = h["failed"].get(m)
        if f and (today - pd.Timestamp(f["at"])).days < 30:
            continue
        todo.append(m)
    downloads, fails_in_row, err = 0, 0, None
    for m in todo:
        if downloads >= max_downloads:
            break
        got = None
        for d in _weekdays_at_month_end(m):
            if downloads >= max_downloads:
                break
            downloads += 1
            try:
                raw, as_of = parse_ishares_csv(http_get(URL[kind].format(d=d.strftime("%Y%m%d"))))
                if not as_of:
                    raise ValueError("ohne Stichtag")
                got_date = pd.Timestamp(pd.to_datetime(as_of))
                if abs((got_date - d).days) > 7:
                    raise ValueError(f"Stichtag {got_date.date()} statt {d.date()} – iShares liefert keine alte Liste")
                frame, _ = build_from_ishares(raw, "iShares-Historie")
                if len(frame) < MIN_ROWS[kind]:
                    raise ValueError(f"nur {len(frame)} Aktien")
                got = (got_date, frame)
                break
            except Exception as exc:  # noqa: BLE001
                err = str(exc)[:160]
        if got is None:
            h["failed"][m] = {"at": today.strftime("%Y-%m-%d"), "error": err}
            fails_in_row += 1
            if fails_in_row >= 4:
                log(f"[historie] 4 Monate in Folge ohne Liste – Abbruch für heute ({err})")
                if not h["months"]:
                    # Quelle liefert grundsätzlich keine alten Listen: 30 Tage Pause statt täglicher Fehlabrufe
                    h["disabled_until"] = (today + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
                break
            continue
        fails_in_row = 0
        d, fr = got
        h["months"][m] = {"asof": d.strftime("%Y-%m-%d"), "rows": [
            [r.symbol, r.name, r.country, r.sector, None if pd.isna(r.ref_price) else float(r.ref_price),
             str(r.ref_currency or ""), str(r.currency_hint or "")]
            for r in fr.itertuples()]}
        h["failed"].pop(m, None)
    save(path, h)
    cov = coverage(h, months)
    info = {"kind": kind, "months_total": len(months), "months_have": len(h["months"]), "downloads": downloads,
            "coverage_from": cov[0], "coverage_to": cov[1], "coverage_months": cov[2], "error": err if downloads and not cov[2] else None}
    log(f"[historie] {kind}: {len(h['months'])}/{len(months)} Monate, zusammenhängend {cov[0]}–{cov[1]} ({cov[2]}), "
        f"{downloads} Abrufe heute")
    return h, info


def coverage(h: dict, months: list[str]) -> tuple[str | None, str | None, int]:
    """Zusammenhängender Block vom jüngsten vorhandenen Monat rückwärts."""
    have = h["months"]
    block = []
    started = False
    for m in reversed(months):
        if m in have:
            block.append(m)
            started = True
        elif started:
            break
    if not block:
        return None, None, 0
    return block[-1], block[0], len(block)


def all_symbols(h: dict) -> dict:
    """Symbol -> (Name, Land, Sektor, Währungs-Hinweis) aus der jüngsten Erwähnung."""
    out = {}
    for m in sorted(h["months"]):
        for s, name, country, sector, _p, _c, hint in h["months"][m]["rows"]:
            out[s] = (name, country, sector, hint)
    return out


def validate(h: dict, close: dict) -> tuple[set, dict]:
    """Prüft je Symbol, ob die Yahoo-Kurse (Landeswährung, splitbereinigt) zu den iShares-Kursen der Stichtage
    passen. Das Verhältnis Yahoo/iShares muss über die Zeit fast konstant sein (Sprünge nur bei Aktiensplits)."""
    pts: dict[str, list] = {}
    for m in sorted(h["months"]):
        d = pd.Timestamp(h["months"][m]["asof"])
        for s, _n, _c, _sec, p, _cur, _hint in h["months"][m]["rows"]:
            if p and p > 0:
                pts.setdefault(s, []).append((d, p))
    ok, stats = set(), {"checked": 0, "no_prices": 0, "mismatch": 0, "ok": 0}
    split_like = [math.log(x) for x in (1, 2, 3, 4, 5, 8, 10, 20, 1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10, 1 / 20, 100, 0.01)]
    for s, lst in pts.items():
        stats["checked"] += 1
        ser = close.get(s)
        if ser is None or ser.dropna().empty:
            stats["no_prices"] += 1
            continue
        ser = ser.dropna()
        lr = []
        for d, p in lst:
            if d < ser.index[0] or d > ser.index[-1] + pd.Timedelta(days=10):
                continue
            v = ser.asof(d)
            if v and v > 0:
                lr.append(math.log(v / p))
        if not lr:
            stats["no_prices"] += 1
            continue
        if len(lr) >= 3:
            good = float(np.mean(np.abs(np.diff(lr)) < 0.08)) >= 0.7
        else:
            good = any(abs(x - k) < 0.1 for x in lr for k in split_like)
        if good:
            ok.add(s)
            stats["ok"] += 1
        else:
            stats["mismatch"] += 1
    return ok, stats


def membership(h: dict, valid: set, months: list[str]) -> dict:
    return {m: {r[0] for r in h["months"][m]["rows"] if r[0] in valid} for m in months if m in h["months"]}
