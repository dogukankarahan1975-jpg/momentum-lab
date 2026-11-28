"""Prüfbericht für die Backtests (läuft in jedem Datenlauf, Ergebnis: archive/audit/latest.json).

1. Simulator auf echten Daten (tools/audit_sim.mjs): Orderkurse = Tageskurse, Käufe nur von Aktien, die am Stichtag
   auf der Liste UND im Index waren, Einzahlungen, Buchhaltung, Steuer unabhängig nachgerechnet.
2. Kursvergleich mit einer zweiten Quelle (Tiingo, falls Schlüssel vorhanden): Monatsrenditen Yahoo vs. Tiingo für
   bis zu 20 große US-Aktien – einmalig geladen und gespeichert.
3. Ausreißer-Suche: Monatsrenditen über +200 % oder unter −80 % (mögliche Datenfehler) zur Sichtprüfung.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import tiingo

# IVV und URTH zuerst: Vergleich der ETF-Sparplan-Linien (S&P 500, MSCI World) mit einer zweiten Quelle
ETF_REFERENCE = {"sp500": ("IVV", "iShares Core S&P 500 ETF (USA)"), "msci_world": ("URTH", "iShares MSCI World ETF (USA)")}
AUDIT_TIINGO_SYMS = ["IVV", "URTH", "AAPL", "MSFT", "AMZN", "JPM", "XOM", "JNJ", "PG", "KO", "WMT", "HD", "CVX", "PFE", "MRK",
                     "INTC", "CSCO", "ORCL", "BAC", "T", "VZ", "DIS"]


def run_node_audit(root: Path, sim_file: Path, membership: dict | None, tmp: Path, log=print) -> dict | None:
    node = shutil.which("node")
    if not node or not sim_file.exists():
        return None
    mem_p = None
    if membership:
        mem_p = tmp / f"audit-membership-{sim_file.stem}.json"
        mem_p.write_text(json.dumps(membership))
    try:
        out = subprocess.run([node, str(root / "tools" / "audit_sim.mjs"), str(sim_file)] + ([str(mem_p)] if mem_p else []),
                             capture_output=True, text=True, timeout=900, cwd=str(root))
        if out.returncode != 0:
            return {"error": (out.stderr or out.stdout)[-400:]}
        return json.loads(out.stdout)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def anomalies(sim: dict, limit: int = 25) -> list:
    out = []
    pts = sim.get("points", [])
    for i, row in enumerate(sim.get("px", [])):
        prev = None
        for k, v in enumerate(row):
            if v is None or not (v > 0):
                prev = None
                continue
            if prev:
                r = v / prev - 1
                if r > 2.0 or r < -0.8:
                    out.append({"symbol": sim["syms"][i], "name": sim["names"][i], "date": pts[k], "return": round(r, 3)})
            prev = v
    out.sort(key=lambda x: -abs(x["return"]))
    return out[:limit]


def price_crosscheck(frames: dict, archive_root: Path, today: pd.Timestamp, log=print) -> dict:
    """Yahoo (bereinigt) vs. Tiingo (bereinigt): Monatsrenditen der Monatsenden seit 2005."""
    arc_dir = archive_root / "audit"
    arc_dir.mkdir(parents=True, exist_ok=True)
    store_p = arc_dir / "tiingo-reference.json"
    store = json.loads(store_p.read_text()) if store_p.exists() else {}
    key = tiingo.api_key()
    if key:
        import requests
        sess = requests.Session()
        st = tiingo.TiingoArchive(archive_root).state
        used = len(st.get("unique", [])) if st.get("month") == today.strftime("%Y-%m") else 0
        budget = max(0, min(10, tiingo.MAX_PER_MONTH - used - 5))
        for s in [x for x in AUDIT_TIINGO_SYMS if x not in store][:budget]:
            try:
                r = sess.get(tiingo.API.format(sym=tiingo.to_tiingo(s)), headers={"Authorization": f"Token {key}"},
                             timeout=40)
                if r.ok:
                    df = tiingo.parse_prices(r.json())
                    if df is not None:
                        m = df["adj"].resample("ME").last().dropna()
                        store[s] = {d.strftime("%Y-%m"): round(float(v), 6) for d, v in m.items() if d.year >= 2005}
                elif r.status_code in (401, 403, 429):
                    break
                time.sleep(1.5)
            except Exception as exc:  # noqa: BLE001
                log(f"[audit] Tiingo {s}: {exc}")
        store_p.write_text(json.dumps(store, separators=(",", ":")))
    res = []
    for s, ref in store.items():
        f = frames.get(s)
        if f is None or not ref:
            continue
        y = f["adj"].resample("ME").last().dropna()
        y.index = y.index.strftime("%Y-%m")
        t = pd.Series(ref)
        both = pd.concat([y.rename("y"), t.rename("t")], axis=1).dropna()
        if len(both) < 24:
            continue
        ry, rt = both["y"].pct_change().dropna(), both["t"].pct_change().dropna()
        d = (ry - rt).abs()
        res.append({"symbol": s, "months": int(len(d)), "median_abs_diff_pct": round(float(d.median()) * 100, 3),
                    "max_abs_diff_pct": round(float(d.max()) * 100, 2), "max_month": str(d.idxmax()),
                    "over_1pct": int((d > 0.01).sum()),
                    "cagr_yahoo_pct": round(float((both["y"].iloc[-1] / both["y"].iloc[0]) ** (12 / len(d)) - 1) * 100, 2),
                    "cagr_tiingo_pct": round(float((both["t"].iloc[-1] / both["t"].iloc[0]) ** (12 / len(d)) - 1) * 100, 2)})
    return {"source": "Tiingo (zweite, unabhängige Kursquelle)", "symbols": res, "pending": [s for s in AUDIT_TIINGO_SYMS if s not in store]}


def etf_crosscheck(sim: dict, fx: pd.DataFrame | None, archive_root: Path) -> list[dict]:
    """ETF-Sparplan-Linien des Simulators (Euro, Yahoo) gegen US-Schwester-ETFs von Tiingo (Dollar, Ausschüttungen
    wieder angelegt), umgerechnet mit dem EZB-Kurs am Monatsende. Erwartete Restabweichung: wenige Zehntel Prozent
    p. a. (Quellensteuer auf US-Dividenden bei irischen ETFs, unterschiedliche Kosten, Handelszeiten)."""
    store_p = archive_root / "audit" / "tiingo-reference.json"
    if fx is None or "USD" not in getattr(fx, "columns", []) or not store_p.exists():
        return []
    store = json.loads(store_p.read_text())
    usd = fx["USD"].dropna()
    pts = pd.DatetimeIndex(sim.get("points", []))
    out = []
    for key, (sym, label) in ETF_REFERENCE.items():
        b = (sim.get("bench") or {}).get(key)
        ref = store.get(sym)
        if not b or not ref or len(pts) != len(b["px"]):
            continue
        ours = pd.Series(b["px"], index=pts, dtype=float).dropna()
        # Simulator-Stichtage sind die ersten Handelstage eines Monats (≈ Schlusskurs des Vormonats); Tiingo-Werte
        # sind Monatsendkurse. Deshalb zählt ein Stichtag in den ersten Tagen eines Monats zum Vormonat.
        ours.index = (ours.index - pd.Timedelta(days=7)).strftime("%Y-%m")
        ours = ours.groupby(level=0).last()
        t = pd.Series(ref, dtype=float)
        rate = usd.resample("ME").last().dropna()
        rate.index = rate.index.strftime("%Y-%m")
        t_eur = (t / rate.reindex(t.index)).dropna()
        both = pd.concat([ours.rename("o"), t_eur.rename("t")], axis=1).dropna()
        if len(both) < 24:
            continue
        n = len(both) - 1
        co = (both["o"].iloc[-1] / both["o"].iloc[0]) ** (12 / n) - 1
        ct = (both["t"].iloc[-1] / both["t"].iloc[0]) ** (12 / n) - 1
        d = (both["o"].pct_change() - both["t"].pct_change()).dropna().abs()
        out.append({"line": key, "ours": b.get("name"), "reference": f"{label} – Tiingo, in Euro (EZB)",
                    "from": both.index[0], "to": both.index[-1], "months": n,
                    "cagr_ours_pct": round(co * 100, 2), "cagr_reference_pct": round(ct * 100, 2),
                    "diff_pa_pct": round((co - ct) * 100, 2),
                    "median_abs_month_diff_pct": round(float(d.median()) * 100, 2),
                    "ok": bool(abs(co - ct) <= 0.01)})
    return out


def write_report(archive_root: Path, report: dict) -> None:
    d = archive_root / "audit"
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
