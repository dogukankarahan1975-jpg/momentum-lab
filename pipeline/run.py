"""Täglicher Datenlauf: Universum -> Kurse -> Qualität -> Momentum -> Details -> Backtest -> JSON.

Aufruf (GitHub Actions):  python -m pipeline.run --out site/data
Demo/Test (offline):      python -m pipeline.run --mode demo --out site/data
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from . import core
from .config import (BENCHMARKS, MSCI_WORLD_BACKFILL, METHODOLOGY, METHODOLOGY_VERSION, PIPELINE_VERSION, REGIME_SYMBOL_ORDER,
                     BACKTEST_VARIANTS, COST_SCENARIOS, TAX, BACKTEST, params_hash, STAGE2, STAGE2_VERSION,
                     STAGE2_CATEGORIES, STAGE2_MIN, STAGE2_BACKTEST, FUNDAMENTALS, stage2_params_hash)
from .fx import fx_on_index, load_fx
from .prices import PriceStore, to_wide, update_prices
from .universe import SUFFIX_COUNTRY, SUFFIX_CURRENCY, load_universe

ROOT = Path(__file__).resolve().parent.parent
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) "
              "Version/18.0 Safari/605.1.15")


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {msg}", flush=True)


# ------------------------------------------------------------------ HTTP (nur im Live-Modus)
def _session():
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = BROWSER_UA
    return s


_S = None


def http_get(url: str, headers: dict | None = None, binary: bool = False, retries: int = 3):
    global _S
    if _S is None:
        _S = _session()
    err = None
    for attempt in range(retries):
        try:
            r = _S.get(url, headers=headers or {}, timeout=40)
            if r.status_code == 429:
                time.sleep(10 * (attempt + 1))
                err = "429"
                continue
            r.raise_for_status()
            return r.content if binary else r.text
        except Exception as exc:  # noqa: BLE001
            err = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{url.split('?')[0]}: {err}")


def http_json(url: str, headers: dict | None = None):
    return json.loads(http_get(url, headers))


def http_post_json(url: str, payload, retries: int = 3):
    global _S
    if _S is None:
        _S = _session()
    err = None
    for attempt in range(retries):
        try:
            r = _S.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=40)
            if r.status_code == 429:
                time.sleep(20 * (attempt + 1))
                err = "429"
                continue
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            err = exc
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{url}: {err}")


def make_bench(bench_frames: dict, frames: dict, currency: dict, fx: pd.DataFrame) -> tuple[dict, list]:
    bench_eur = {}
    for key, b in BENCHMARKS.items():
        df = bench_frames.get(b["symbol"])
        if df is None:
            continue
        s = df["adj"].dropna()
        c = currency.get(b["symbol"], b["currency"])
        if c != "EUR":
            if c not in fx.columns:
                continue
            s = s / fx_on_index(fx, s.index)[c]
        bench_eur[key] = {"name": b["name"], "eur": s.dropna()}
    backfill = []
    for b in MSCI_WORLD_BACKFILL:
        df = frames.get(b["symbol"])
        if df is None or df.empty:
            continue
        s = df["adj"].dropna()
        c = currency.get(b["symbol"], b["currency"])
        if c != "EUR":
            if c not in fx.columns:
                continue
            s = s / fx_on_index(fx, s.index)[c]
        backfill.append({"symbol": b["symbol"], "name": b["name"], "eur": s.dropna()})
    return bench_eur, backfill


# ------------------------------------------------------------------ Hilfsfunktionen
def r5(x, digits: int = 5):
    if x is None:
        return None
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    if x == 0:
        return 0.0
    return float(f"{x:.{digits}g}")


def iso(d) -> str | None:
    if d is None or (isinstance(d, float) and math.isnan(d)) or pd.isna(d):
        return None
    return pd.Timestamp(d).strftime("%Y-%m-%d")


def determine_asof(adj: pd.DataFrame) -> pd.Timestamp:
    tail = adj.iloc[-12:]
    counts = tail.notna().sum(axis=1)
    thr = 0.5 * counts.max()
    ok = counts[counts >= thr]
    return ok.index[-1]


FX_FROM_YAHOO = ["TWD", "SAR", "AED", "QAR", "KWD", "CLP", "COP", "PEN", "EGP"]


def demo_bt_sources(universe: pd.DataFrame, frames: dict) -> dict:
    """DEMO: synthetische Stichtagslisten (wie S&P 500 / DAX / ACWI aufgebaut)."""
    h = demo_history(universe, frames)
    months = {m: [[r[0], r[1], "USA", "", None, "USD"] for r in v["rows"]] for m, v in h["months"].items()}
    half = {m: rows[: len(rows) // 2] for m, rows in months.items()}
    rest = {m: rows[len(rows) // 2:] for m, rows in months.items()}
    return {"sp500": {"months": half, "source": "DEMO", "info": {}},
            "dax": {"months": rest, "source": "DEMO", "info": {}},
            "acwi": {"months": {m: v for m, v in months.items() if m >= "2019-10"}, "source": "DEMO", "info": {}}}


def demo_history(universe: pd.DataFrame, frames: dict) -> dict:
    """DEMO: synthetische historische Zusammensetzung (rotierend ein Teil der Aktien nicht im Index)."""
    syms = list(universe["symbol"])
    h = {"version": 1, "months": {}, "failed": {}, "dead": {}}
    for i, per in enumerate(pd.period_range("2012-01", "2026-10", freq="M")):
        d = per.to_timestamp(how="end").normalize()
        rows = []
        for j, x in enumerate(syms):
            if (j + i // 12) % 7 == 0:
                continue
            if x not in frames:
                continue
            c = frames[x]["close"].dropna()
            p = float(c.asof(d)) if not c.empty and d >= c.index[0] else None
            rows.append([x, x, "", "", p, "", ""])
        h["months"][per.strftime("%Y-%m")] = {"asof": d.strftime("%Y-%m-%d"), "rows": rows}
    return h


def read_universe_kind(path: Path) -> str:
    """config/universe.txt: „acwi“ (Standard) oder „world“."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            w = line.split("#", 1)[0].strip().lower()
            if w in ("acwi", "world"):
                return w
    return "acwi"


def read_watchlist(path: Path) -> list[str]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.split("#", 1)[0].strip().upper()
        if s and re.fullmatch(r"[A-Z0-9.\-^=]{1,20}", s):
            out.append(s)
    return sorted(set(out))


def parse_ishares_date(s: str | None) -> pd.Timestamp | None:
    if not s:
        return None
    for fmt in ("%b %d, %Y", "%d.%m.%Y", "%d/%b/%Y", "%Y-%m-%d"):
        try:
            return pd.Timestamp(datetime.strptime(s.strip(), fmt))
        except ValueError:
            continue
    try:
        return pd.Timestamp(s)
    except Exception:  # noqa: BLE001
        return None


def crosscheck(close: pd.DataFrame, universe: pd.DataFrame, ref_date: pd.Timestamp | None) -> pd.Series:
    """Abweichung des Yahoo-Schlusskurses vom iShares-Kurs desselben Handelstags.

    Verglichen wird nur mit Kursen bis einschließlich Stichtag der iShares-Liste (nie danach, sonst
    würde ein Tagesgewinn als Datenfehler gelten). Feiertage: letzter Kurs davor, wie beim Fonds.
    Weil die Datumskonvention der Liste um einen Handelstag abweichen kann, zählt die kleinere
    Abweichung von Stichtagskurs und Vortageskurs. Ein falsch zugeordneter Ticker oder eine falsche
    Einheit fällt trotzdem auf.
    """
    dev = pd.Series(np.nan, index=close.columns)
    if "ref_price" not in universe or universe["ref_price"].isna().all():
        return dev
    for _, r in universe.dropna(subset=["ref_price"]).iterrows():
        sym, ref = r["symbol"], float(r["ref_price"])
        if sym not in close.columns or not ref or ref <= 0:
            continue
        s = close[sym].dropna()
        if s.empty:
            continue
        cands = [float(s.iloc[-1])]
        if ref_date is not None:
            s = s[s.index <= ref_date]
            if s.empty or (ref_date - s.index[-1]).days > 4:
                continue
            cands = [float(s.iloc[-1])]
            if len(s) >= 2 and (ref_date - s.index[-2]).days <= 6:
                cands.append(float(s.iloc[-2]))
        best = None
        for px in cands:
            ratio = px / ref
            for unit in (100.0, 0.01):  # Pence/Pfund o. Ä.
                if abs(ratio / unit - 1) < 0.03:
                    ratio = ratio / unit
            d = ratio - 1
            if best is None or abs(d) < abs(best):
                best = d
        dev[sym] = best
    return dev


def sanitize_crosscheck(dev: pd.Series, cur: pd.Series, tol: float) -> tuple[pd.Series, dict]:
    """Weicht in einer Währung mehr als die Hälfte der Kurse ab, liegt ein Konventionsproblem der Zweitquelle vor
    (z. B. Kurs in USD statt Landeswährung). Dann wird die Gegenprüfung für diese Währung ausgesetzt, statt alle
    Aktien als fehlerhaft auszuschließen."""
    dev = dev.copy()
    off = {}
    c = cur.reindex(dev.index)
    for cc in c.dropna().unique():
        sub = dev[(c == cc) & dev.notna()]
        if len(sub) >= 8 and (sub.abs() > tol).mean() > 0.5:
            off[cc] = float((sub.abs() > tol).mean())
            dev[sub.index] = np.nan
    return dev, off


def find_duplicates(universe: pd.DataFrame, liq: pd.Series) -> set:
    dups = set()
    if "issuer_key" not in universe:
        return dups
    for key, grp in universe.groupby("issuer_key"):
        syms = [s for s in grp["symbol"] if s in liq.index]
        if len(syms) < 2:
            continue
        best = max(syms, key=lambda s: (liq.get(s) if pd.notna(liq.get(s)) else -1))
        dups.update(s for s in syms if s != best)
    return dups


def market_regime(bench_frames: dict, fx: pd.DataFrame, elig_above_ma: pd.Series) -> dict:
    out = {"proxy": None}
    for sym in REGIME_SYMBOL_ORDER:
        df = bench_frames.get(sym)
        if df is None or len(df) < 600:
            continue
        s = df["adj"].dropna()
        last = s.iloc[-1]
        ma = s.iloc[-200:].mean()
        ret = lambda days: last / s[s.index <= s.index[-1] - pd.Timedelta(days=days)].iloc[-1] - 1  # noqa: E731
        dret = s.pct_change()
        vol3m = dret.rolling(63, min_periods=50).std() * math.sqrt(250)
        me = vol3m.groupby([vol3m.index.year, vol3m.index.month]).tail(1).dropna()
        deltas = (me / me.shift(1) - 1).dropna()
        cur_delta = deltas.iloc[-1] if len(deltas) else np.nan
        thr = np.percentile(deltas.iloc[:-1], 95) if len(deltas) > 36 else np.nan
        out = {
            "proxy": sym, "name": next((b["name"] for b in BENCHMARKS.values() if b["symbol"] == sym), sym),
            "date": iso(s.index[-1]), "above_ma200": bool(last > ma), "dist_ma200": r5(last / ma - 1),
            "dd_from_high": r5(last / s.max() - 1), "ret_12m": r5(ret(365)), "ret_24m": r5(ret(730)),
            "vol_3m": r5(vol3m.iloc[-1]), "vol_change": r5(cur_delta), "vol_shock_threshold": r5(thr),
            "vol_shock": bool(np.isfinite(thr) and np.isfinite(cur_delta) and cur_delta > thr),
        }
        out["bear_state"] = bool(out["ret_24m"] is not None and out["ret_24m"] < 0)
        break
    valid = elig_above_ma.dropna()
    out["breadth_above_ma200"] = r5(valid.mean()) if len(valid) else None
    return out


# ------------------------------------------------------------------ Hauptablauf
def run(args) -> int:
    t0 = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "details").mkdir(exist_ok=True)
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    archive = Path(args.archive)
    demo = args.mode == "demo"
    messages: list[dict] = []
    sources: dict = {}

    def msg(level, text):
        messages.append({"level": level, "text": text})
        log(f"[{level}] {text}")

    # 1) Universum
    if demo:
        from .synthetic import generate
        universe, frames, currency, fx = generate(args.asof or "2026-11-20")
        uni_as_of = args.asof or "2026-11-20"
        sources["universe"] = {"name": "DEMO (synthetisch)", "ok": True, "type": "demo"}
        sources["prices"] = {"name": "DEMO (synthetisch)", "ok": True, "type": "demo"}
        sources["fx"] = {"name": "DEMO (synthetisch)", "ok": True, "type": "demo", "last_date": iso(fx.index[-1])}
        price_status = {s: "ok" for s in frames}
        pstats = {"requested": len(frames), "ok": len(frames), "failed": 0, "cached_only": 0}
        watch = []
        hist, pit_frames, pit_currency, kind = demo_history(universe, frames), {}, {}, "acwi"
    else:
        kind = read_universe_kind(ROOT / "config" / "universe.txt")
        ures = load_universe(lambda u: http_get(u), archive / "universe", offline=False, kind=kind)
        universe, uni_as_of = ures.frame, ures.as_of
        for w in ures.warnings:
            msg("warnung", w)
        sources["universe"] = {"name": ures.source, "ok": ures.source.startswith("iShares"),
                               "as_of": uni_as_of, "size_index": int(len(universe)), "type": "database", "kind": kind,
                               "url": ("https://www.ishares.com/uk/individual/en/products/251850/ishares-msci-acwi-ucits-etf"
                                       if kind == "acwi" else "https://www.ishares.com/us/products/239696/ishares-msci-world-etf")}
        # Nur Aktien, die in Deutschland (Börse Frankfurt) handelbar sind – Annäherung an das Trade-Republic-Angebot
        from .tradable import apply_filter, load_frankfurt_isins
        isins, tstat = (None, {"name": "Deutsche Börse – handelbare Instrumente Börse Frankfurt", "type": "official",
                               "ok": False, "error": "nicht benötigt"})
        if "isin" in universe and (universe["isin"].astype(str).str.len() == 12).mean() > 0.8:
            isins, tstat = load_frankfurt_isins(lambda u: http_get(u, binary=True), lambda u: http_get(u), log)
        universe, tinfo = apply_filter(universe, isins, archive / "universe", iso(pd.Timestamp.utcnow().tz_localize(None)))
        untradable = set(tinfo.pop("removed_symbols", []))
        tstat["filter"] = tinfo
        tstat["ok"] = bool(tinfo.get("checked"))
        sources["tradable_de"] = tstat
        sources["universe"]["size"] = int(len(universe))
        if tinfo.get("note"):
            msg("warnung", tinfo["note"])
        log(f"Universum: {sources['universe']['size_index']} im Index, {len(universe)} nach Handelbarkeits-Prüfung "
            f"({tinfo.get('removed', 0)} nicht in Frankfurt, {tinfo.get('removed_cn_a', 0)} China-A)")
        watch = read_watchlist(ROOT / "config" / "watchlist.txt")
        bench_syms = ([b["symbol"] for b in BENCHMARKS.values()] + [b["symbol"] for b in MSCI_WORLD_BACKFILL]
                      + [f"EUR{c}=X" for c in FX_FROM_YAHOO])
        symbols = list(dict.fromkeys(list(universe["symbol"]) + watch + bench_syms))
        hints = dict(zip(universe["symbol"], universe.get("currency_hint", pd.Series(dtype=str))))
        for s in watch + bench_syms:
            if s not in hints:
                suf = "" if "." not in s else "." + s.split(".", 1)[1]
                hints[s] = SUFFIX_CURRENCY.get(suf)
        store = PriceStore.load(cache / "prices.pkl.gz")
        log(f"Kurse laden für {len(symbols)} Symbole (Cache: {len(store.data)})")
        res = update_prices(symbols, store, hints, full_refresh=args.full_refresh, log=log)
        frames, currency, price_status, pstats = res.frames, res.currency, res.status, res.stats
        # Historische Indexzusammensetzung für den Backtest (point in time) und Kurse ehemaliger Mitglieder
        try:
            from . import pit
            today_ts = pd.Timestamp.utcnow().tz_localize(None).normalize()
            hist_path = pit.path_for(archive / "universe", kind)
            hist, hinfo = pit.update_history(lambda u: http_get(u), hist_path, kind, today_ts, log=log)
            hsyms = pit.all_symbols(hist)
            cur_set = set(universe["symbol"])
            pit_only = [x for x in hsyms if x not in cur_set and x not in untradable and not x.endswith((".SS", ".SZ"))]
            dead = {x for x, d in hist.get("dead", {}).items() if (today_ts - pd.Timestamp(d)).days < 60}
            phints = {x: hsyms[x][3] or SUFFIX_CURRENCY.get("." + x.split(".", 1)[1] if "." in x else "") for x in pit_only}
            log(f"[historie] {len(pit_only)} ehemalige Indexmitglieder, davon {len(dead)} zuletzt ohne Kurse")
            pres = update_prices(pit_only, store, phints, full_refresh=False, deadline_s=1800, log=log,
                                 refresh_if_older_days=7, fallback=False, skip=dead)
            for x, st in pres.status.items():
                if st.startswith("Fehler: nicht gefunden"):
                    hist.setdefault("dead", {})[x] = today_ts.strftime("%Y-%m-%d")
            pit.save(hist_path, hist)
            pit_frames, pit_currency = pres.frames, pres.currency
            hinfo["former_members"] = len(pit_only)
            hinfo["former_with_prices"] = len(pit_frames)
            sources["history"] = {"name": "iShares-Bestandslisten zu früheren Stichtagen", "type": "database",
                                  "ok": hinfo["coverage_months"] >= pit.MIN_MONTHS, "info": hinfo,
                                  "detail": f"{hinfo['months_have']} von {hinfo['months_total']} Monaten geladen, zusammenhängend "
                                            f"{hinfo['coverage_from'] or '–'} bis {hinfo['coverage_to'] or '–'}; "
                                            f"{len(pit_only)} ehemalige Mitglieder, davon {len(pit_frames)} mit Kursen"
                                            + (f"; Fehler: {hinfo['error']}" if hinfo.get("error") else "")}
        except Exception as exc:  # noqa: BLE001 – Historie ist optional, das Screening läuft auch ohne
            log(f"[historie] Fehler: {exc}")
            hist, pit_frames, pit_currency = None, {}, {}
            sources["history"] = {"name": "iShares-Bestandslisten zu früheren Stichtagen", "type": "database",
                                  "ok": False, "error": str(exc)[:200]}
        store.save(cache / "prices.pkl.gz")
        sources["prices"] = {"name": "Yahoo Finance (inoffiziell)", "ok": pstats["ok"] > 0.8 * len(symbols),
                             "type": "database", "stats": pstats}
        if pstats.get("blocked"):
            msg("fehler", "Yahoo Finance hat die Abrufe gesperrt/gedrosselt – ältere Kurse aus dem Cache verwendet.")
        fx, fxs = load_fx(lambda u: http_get(u, binary=True), cache / "fx.pkl")
        sources["fx"] = {"name": fxs["source"], "ok": fxs["ok"], "from_cache": fxs["from_cache"],
                         "last_date": fxs["last_date"], "error": fxs["error"], "type": "official",
                         "url": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html"}
        if fx is None:
            msg("fehler", "Keine Wechselkurse verfügbar – Screening nicht möglich.")
        else:
            # Währungen, die die EZB nicht veröffentlicht (z. B. TWD, SAR): Yahoo-Devisenkurse (inoffiziell)
            added = []
            for c in FX_FROM_YAHOO:
                df = frames.get(f"EUR{c}=X")
                if c in fx.columns or df is None or df.empty:
                    continue
                ser = df["close"].dropna()
                ser = ser[ser > 0]
                if len(ser) < 250:
                    continue
                fx[c] = ser.reindex(fx.index.union(ser.index)).sort_index().ffill().reindex(fx.index)
                added.append(c)
            if added:
                sources["fx_yahoo"] = {"name": "Yahoo Finance Devisenkurse (inoffiziell)", "ok": True, "type": "database",
                                       "detail": "für " + ", ".join(added) + " (nicht bei der EZB)"}

    bench_frames = {b["symbol"]: frames.get(b["symbol"]) for b in BENCHMARKS.values() if frames.get(b["symbol"]) is not None}
    uni_syms = [s for s in universe["symbol"] if s in frames]
    watch_only = [s for s in watch if s in frames and s not in set(universe["symbol"])]
    stock_syms = uni_syms + watch_only
    if not stock_syms or fx is None:
        return _fail(out, messages, sources, demo, "Keine verwertbaren Kursdaten.", cache)

    adj = to_wide({s: frames[s] for s in stock_syms}, "adj", "2000-01-01")
    close = to_wide({s: frames[s] for s in stock_syms}, "close", "2000-01-01")
    volume = to_wide({s: frames[s] for s in stock_syms}, "volume", "2000-01-01")
    asof = determine_asof(adj)
    today = pd.Timestamp.utcnow().tz_localize(None).normalize() if not demo else asof
    data_age = (today - asof).days
    log(f"Datenstand (as-of): {asof.date()}, Alter {data_age} Tage")
    cur_series = pd.Series({s: currency.get(s) for s in stock_syms})
    fx_idx = fx_on_index(fx, adj.index)
    fx_row = fx_idx.loc[asof]

    # 2) Qualität
    panel = core.prepare_panel(adj, close, volume)
    ref_date = parse_ishares_date(uni_as_of) if not demo else asof
    dev = crosscheck(close, universe, ref_date)
    dev, off = sanitize_crosscheck(dev, cur_series, METHODOLOGY["crosscheck_tolerance"])
    for c, share in off.items():
        msg("warnung", f"Gegenprüfung für {c}-Kurse ausgesetzt: {share:.0%} weichen ab – vermutlich andere Kurs-Konvention "
                       "in der iShares-Liste, kein Fehler einzelner Aktien.")
    has_ref = universe.set_index("symbol")["ref_price"].reindex(stock_syms).notna() if "ref_price" in universe else pd.Series(False, index=stock_syms)
    pre = core.quality_at(panel, asof, cur_series, fx_row, METHODOLOGY, dev)
    dups = find_duplicates(universe[universe["symbol"].isin(uni_syms)], pre["liq_eur"])
    q = core.quality_at(panel, asof, cur_series, fx_row, METHODOLOGY, dev, dups)
    for s in watch_only:
        q.at[s, "reasons"] = q.at[s, "reasons"] + ["watchlist"]
        q.at[s, "eligible"] = False
    f = core.features_at(panel, asof)
    elig = q["eligible"] & f["vol"].notna()
    for s in q.index[q["eligible"] & f["vol"].isna()]:
        q.at[s, "reasons"] = q.at[s, "reasons"] + ["no_vol"]
    sc = core.scores_at(f, elig, "ra")
    verified = pd.Series({s: (bool(abs(dev[s]) <= METHODOLOGY["crosscheck_tolerance"]) if pd.notna(dev.get(s)) else False)
                          for s in stock_syms})
    cands = core.select_candidates(f, sc, elig, METHODOLOGY["top_n"])
    top_pick, tp_info = core.pick_top(cands, f, sc, elig, METHODOLOGY, verified)
    hs = core.hold_state(sc["pct"], f["m12"], q["data_ok"], sc["score_valid"])

    # Vormonat (für 2-stufige Verkaufsbestätigung und "neu in Top 10")
    prev_d = core.last_trading_day_of_prev_month(adj.index, asof)
    prev_cands, hs_prev, sc_prev = [], None, None
    if prev_d is not None:
        q_p = core.quality_at(panel, prev_d, cur_series, fx_idx.loc[prev_d], METHODOLOGY, None, dups)
        f_p = core.features_at(panel, prev_d, light=True)
        el_p = q_p["eligible"] & f_p["vol"].notna()
        for s in watch_only:
            el_p[s] = False
        sc_prev = core.scores_at(f_p, el_p, "ra")
        hs_prev = core.hold_state(sc_prev["pct"], f_p["m12"], q_p["data_ok"], sc_prev["score_valid"])
        prev_cands = core.select_candidates(f_p, sc_prev, el_p, METHODOLOGY["top_n"])

    # 3) Status / Qualitätsgate
    n_uni = len(universe)
    n_priced = len(uni_syms)
    coverage = n_priced / n_uni if n_uni else 0
    fresh = int(((asof - q.loc[uni_syms, "last_date"]).dt.days <= METHODOLOGY["stale_days"]).sum())
    fresh_share = fresh / n_uni if n_uni else 0
    n_elig = int(elig.loc[uni_syms].sum())
    cc_n = int(dev.notna().sum())
    cc_bad = int((dev.abs() > METHODOLOGY["crosscheck_tolerance"]).sum())
    sources["crosscheck"] = {"name": "iShares-Bestandsliste (Schlusskurse)", "ok": cc_n > 0.5 * n_priced,
                             "checked": cc_n, "deviations": cc_bad, "type": "database"}
    overall = "ok"
    if demo:
        msg("warnung", "DEMO-DATEN: synthetische Kurse und erfundene Unternehmen – keine echten Signale.")
    if fresh_share < 0.5 or data_age > 6:
        overall = "fehler"
        msg("fehler", f"Nur {fresh_share:.0%} des Universums mit aktuellen Kursen bzw. Daten {data_age} Tage alt – "
                      "keine Empfehlungen.")
    elif fresh_share < 0.8 or data_age > 3 or not sources["universe"]["ok"] or pstats.get("blocked"):
        overall = "warnung"
        if fresh_share < 0.8:
            msg("warnung", f"Nur {fresh_share:.0%} des Universums mit aktuellen Kursen.")
        if data_age > 3:
            msg("warnung", f"Datenstand ist {data_age} Tage alt.")
    if cc_n < 0.5 * max(n_priced, 1) and not demo:
        overall = "warnung" if overall == "ok" else overall
        msg("warnung", "Gegenprüfung der Kurse nur eingeschränkt möglich – kein Top Pick ohne Verifizierung.")
    if overall == "fehler":
        cands, top_pick = [], None

    # 4) Zeilen für screen.json
    meta = universe.set_index("symbol")
    fields = ["symbol", "name", "country", "sector", "currency", "exchange", "isin", "index_weight", "in_universe",
              "eligible", "data_ok", "reasons", "last_date", "last_close", "last_close_eur", "m6", "m12", "vol",
              "z6", "z12", "Z", "rank", "pct", "ret_1m", "ret_3m", "ret_6m", "ret_12m", "ret_ytd", "dd_52w",
              "maxdd_1y", "ma200", "above_ma200", "dist_ma200", "liq_eur", "history_years", "crosscheck_dev",
              "verified", "H", "severe", "H_prev", "prev_rank", "prev_pct", "has_detail", "price_status"]
    detail_set = list(dict.fromkeys(cands + list(sc["rank"].dropna().sort_values().index[:50]) + prev_cands + watch_only))
    hist_file = archive / "candidates_history.json"
    cand_hist = json.loads(hist_file.read_text()) if hist_file.exists() else {}
    cutoff = (asof - pd.DateOffset(months=24)).strftime("%Y-%m-%d")
    for s, last_seen in list(cand_hist.items()):
        if last_seen >= cutoff and s in stock_syms and s not in detail_set:
            detail_set.append(s)
    for s in cands:
        cand_hist[s] = iso(asof)
    rows = []
    for s in sorted(set(universe["symbol"]) | set(watch_only)):
        in_uni = s in set(universe["symbol"])
        if s not in stock_syms:
            m = meta.loc[s] if in_uni else {}
            suf = "" if "." not in s else "." + s.split(".", 1)[1]
            rows.append([s, m.get("name", s), m.get("country", SUFFIX_COUNTRY.get(suf, "")), m.get("sector", ""),
                         m.get("currency_hint", ""), m.get("exchange", ""), m.get("isin", "") or "",
                         r5(m.get("index_weight")), in_uni, False, False, ["no_data"]] + [None] * (len(fields) - 13)
                        + [price_status.get(s, "nicht geladen")])
            continue
        m = meta.loc[s] if in_uni else {}
        cur = cur_series.get(s)
        eur_f = 1.0 if cur == "EUR" else (1 / fx_row.get(cur) if pd.notna(fx_row.get(cur, np.nan)) else np.nan)
        fx_ = f.loc[s]
        rows.append([
            s, (m.get("name") if in_uni else s), (m.get("country") if in_uni else SUFFIX_COUNTRY.get("." + s.split(".", 1)[1] if "." in s else "", "")),
            (m.get("sector") if in_uni else "Beobachtungsliste"), cur, (m.get("exchange", "") if in_uni else ""),
            (m.get("isin", "") or "") if in_uni else "", r5(m.get("index_weight")) if in_uni else None, in_uni,
            bool(elig.get(s, False)), bool(q.at[s, "data_ok"]), list(q.at[s, "reasons"]), iso(q.at[s, "last_date"]),
            r5(fx_["last_close"], 6), r5(fx_["last_close"] * eur_f, 6), r5(fx_["m6"]), r5(fx_["m12"]), r5(fx_["vol"]),
            r5(sc.at[s, "z6"]), r5(sc.at[s, "z12"]), r5(sc.at[s, "Z"]),
            int(sc.at[s, "rank"]) if pd.notna(sc.at[s, "rank"]) else None, r5(sc.at[s, "pct"]),
            r5(fx_["ret_1m"]), r5(fx_["ret_3m"]), r5(fx_["ret_6m"]), r5(fx_["ret_12m"]), r5(fx_["ret_ytd"]),
            r5(fx_["dd_52w"]), r5(fx_["maxdd_1y"]), r5(fx_["ma200"], 6),
            None if pd.isna(fx_["above_ma200"]) else bool(fx_["above_ma200"]), r5(fx_["dist_ma200"]),
            r5(q.at[s, "liq_eur"], 3), r5(q.at[s, "history_years"], 3), r5(dev.get(s)),
            (bool(verified[s]) if has_ref.get(s, False) else None),
            bool(hs.at[s, "H"]), bool(hs.at[s, "severe"]),
            (bool(hs_prev.at[s, "H"]) if hs_prev is not None and s in hs_prev.index else None),
            (int(sc_prev.at[s, "rank"]) if sc_prev is not None and s in sc_prev.index and pd.notna(sc_prev.at[s, "rank"]) else None),
            (r5(sc_prev.at[s, "pct"]) if sc_prev is not None and s in sc_prev.index else None),
            s in detail_set, price_status.get(s, ""),
        ])

    # 5) Details (Kursreihen, Fundamentaldaten, Nachrichten)
    det_stats = {}
    if not args.skip_details:
        det_stats = write_details(out, detail_set, panel, meta, f, cur_series, demo, cache, asof)
        sources.update(det_stats.get("sources", {}))

    # 5b) Stage 2 – Fortsetzungsanalyse der Kandidaten. Eigener Fehlerbereich: Stage 1 bleibt in jedem Fall gültig.
    s2 = None
    try:
        s2 = stage2_block(demo=demo, universe=universe, meta=meta, panel=panel, fx=fx, fx_row=fx_row,
                          cur_series=cur_series, bench_frames=bench_frames, currency=currency, asof=asof, today=today,
                          f=f, sc=sc, q=q, elig=elig, cands=cands, top_pick=top_pick, verified=verified,
                          watch_only=watch_only, frames=frames, cache=cache, archive=archive, sources=sources,
                          stage1_failed=(overall == "fehler"))
        for m in s2.get("messages", []):
            if m["level"] in ("warnung", "fehler"):
                msg("warnung", f"Stage 2: {m['text']}")
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        msg("warnung", f"Stage 2 fehlgeschlagen ({exc}). Stage 1 ist davon nicht betroffen.")
        s2 = {"schema": 2, "stage2_version": "2.0.0", "status": "fehler", "asof": iso(asof), "demo": demo,
              "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "messages": [{"level": "fehler", "text": f"Stage 2 konnte nicht berechnet werden: {str(exc)[:240]}"}],
              "ranking": [], "buy": []}
        if overall == "ok":
            overall = "warnung"
    (out / "stage2.json").write_text(json.dumps(sanitize(s2), default=_json_default, ensure_ascii=False,
                                                separators=(",", ":"), allow_nan=False))

    # 6) Monatsreihen für Depot-Historie (10 Jahre, splitbereinigte Schlusskurse)
    write_monthly(out, close, fx_idx, cur_series, bench_frames, fx, asof)

    # 7) Markt
    regime = market_regime(bench_frames, fx, f.loc[elig[elig].index, "above_ma200"] if elig.any() else pd.Series(dtype=float))
    if regime.get("bear_state"):
        msg("warnung", "Marktphase: 24-Monats-Rendite des Marktes negativ – historisch erhöhtes Risiko für Momentum-Crashs.")
    if regime.get("vol_shock"):
        msg("warnung", "Volatilitätsschock (MSCI-Regel): MSCI würde jetzt ad hoc nur mit 6-Monats-Momentum neu gewichten.")

    # 8a) Historische Indexzusammensetzung (point in time) für den Backtest
    members, pit_info, bt_syms = None, None, list(uni_syms)
    bt_frames, bt_currency = frames, dict(currency)
    if hist is not None:
        try:
            from . import pit
            months = pit.month_list(pit.START[kind], today)
            cov = pit.coverage(hist, months)
            close_local = {x: frames[x]["close"] for x in uni_syms}
            close_local.update({x: df["close"] for x, df in pit_frames.items()})
            valid, vstats = pit.validate(hist, close_local)
            hsyms = pit.all_symbols(hist)
            valid |= {x for x in uni_syms if x not in hsyms}
            pit_info = {"active": False, "kind": kind, "coverage_from": cov[0], "coverage_to": cov[1],
                        "months": cov[2], "symbols_total": len(hsyms), "validation": vstats}
            if cov[2] >= pit.MIN_MONTHS:
                mem = pit.membership(hist, valid, months)
                members = {m: v for m, v in mem.items() if cov[0] <= m <= cov[1]}
                extra = sorted({x for v in members.values() for x in v if x in pit_frames} - set(uni_syms))
                bt_syms = list(uni_syms) + extra
                bt_frames = {**frames, **{x: pit_frames[x] for x in extra}}
                bt_currency.update({x: pit_currency.get(x) for x in extra})
                in_hist = {x for v in members.values() for x in v}
                pit_info.update(active=True, former_members_used=len(extra),
                                members_without_prices=int(sum(1 for x in hsyms if x not in valid)))
                log(f"[historie] Backtest mit historischer Zusammensetzung {cov[0]}–{cov[1]}: {len(in_hist)} Aktien, "
                    f"davon {len(extra)} ehemalige; {pit_info['members_without_prices']} ohne passende Kurse")
            else:
                msg("info", f"Historische Indexzusammensetzung wird aufgebaut ({cov[2]} von mindestens {pit.MIN_MONTHS} "
                            "Monaten) – Backtest bis dahin mit der heutigen Aktienliste.")
        except Exception as exc:  # noqa: BLE001
            log(f"[historie] nicht verwendet: {exc}")
            members, pit_info = None, {"active": False, "error": str(exc)[:200]}

    # 8) Backtest (nur bei neuem Monat, Methodikänderung oder auf Wunsch)
    bt_path_cache = cache / "backtest.json"
    bt_key = (f"{PIPELINE_VERSION}|{params_hash()}|{stage2_params_hash()}|{prev_d.strftime('%Y-%m') if prev_d is not None else ''}"
              f"|{len(uni_syms)//50}|{'demo' if demo else 'live'}"
              f"|pit{(pit_info or {}).get('coverage_from')}-{len(bt_syms)//50}")
    bt_res = None
    bt_ctx = None
    if not args.skip_backtest:
        if bt_path_cache.exists() and not args.force_backtest:
            cached = json.loads(bt_path_cache.read_text())
            if cached.get("key") == bt_key:
                bt_res = cached
                log("Backtest aus Cache (gleicher Monat und gleiche Methodik)")
        if bt_res is None:
            try:
                bench_eur, backfill = make_bench(bench_frames, frames, currency, fx)
                if members:
                    badj = to_wide({x: bt_frames[x] for x in bt_syms}, "adj", "2000-01-01")
                    bclose = to_wide({x: bt_frames[x] for x in bt_syms}, "close", "2000-01-01")
                    bvol = to_wide({x: bt_frames[x] for x in bt_syms}, "volume", "2000-01-01")
                    upanel = core.prepare_panel(badj, bclose, bvol)
                    bcur = pd.Series({x: bt_currency.get(x) for x in bt_syms})
                    hs = pit.all_symbols(hist)
                    extra_meta = pd.DataFrame([{"symbol": x, "name": hs[x][0], "country": hs[x][1], "sector": hs[x][2]}
                                               for x in bt_syms if x not in set(uni_syms) and x in hs]).set_index("symbol") \
                        if len(bt_syms) > len(uni_syms) else None
                    bt_meta = pd.concat([meta, extra_meta]) if extra_meta is not None else meta
                else:
                    upanel = core.prepare_panel(adj[uni_syms], close[uni_syms], volume[uni_syms])
                    bcur = cur_series.reindex(uni_syms)
                    bt_meta = meta
                ctx = bt.Context(upanel, bcur, fx, dups, asof, bench_eur, log=log, membership=members)
                bt_res = bt.run_backtest(ctx, log=log)
                if bt_res.get("available"):
                    try:
                        from .simulator import build_sim_data
                        sim = build_sim_data(ctx, bt_meta, bench_eur, asof, log=log, backfill=backfill, pit_info=pit_info)
                        sim["key"] = bt_key
                        sim["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                        (cache / "simulator.json").write_text(json.dumps(sanitize(sim), separators=(",", ":"),
                                                                         ensure_ascii=False, allow_nan=False))
                    except Exception as exc:  # noqa: BLE001
                        traceback.print_exc()
                        msg("warnung", f"Simulator-Daten konnten nicht erstellt werden: {exc}")
                bt_ctx = ctx
                bt_res["key"] = bt_key
                bt_res["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                bt_path_cache.write_text(json.dumps(bt_res, default=_json_default))
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                msg("warnung", f"Backtest fehlgeschlagen: {exc}")
                bt_res = {"available": False, "reason": f"Fehler: {exc}"}
    if bt_res is not None:
        bt_res = dict(bt_res, demo=demo, methodology_version=METHODOLOGY_VERSION)
        (out / "backtest.json").write_text(json.dumps(sanitize(bt_res), default=_json_default, separators=(",", ":"), allow_nan=False))

    # 8b) Backtests mit damaliger Indexzusammensetzung (S&P 500, DAX-Familie, Kombination, ACWI ab 2019)
    if not args.skip_backtest and not getattr(args, "skip_pit", False):
        try:
            from .bt_run import run_all
            from .simulator import build_sim_data
            b_eur, b_fill = make_bench(bench_frames, frames, currency, fx)
            idx = run_all(
                http_get=http_get, http_json=http_json, http_post_json=http_post_json, archive=archive / "universe",
                cache=cache, out=out, root=ROOT, universe=universe, frames=frames, currency=currency,
                store=None if demo else store, fx=fx, asof=asof, today=today, bench_eur=b_eur, backfill=b_fill,
                build_sim_data=build_sim_data, sanitize=sanitize, log=log,
                price_deadline_s=max(0, min(2400, 115 * 60 - (time.time() - t0) - 25 * 60)),
                key_base=f"{PIPELINE_VERSION}|{params_hash()}|{stage2_params_hash()}|{prev_d.strftime('%Y-%m') if prev_d is not None else ''}",
                sources=demo_bt_sources(universe, frames) if demo else None)
            if not demo:
                store.save(cache / "prices.pkl.gz")
            (out / "simulators.json").write_text(json.dumps(sanitize({"generated_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"), "universes": idx}), ensure_ascii=False, separators=(",", ":"), allow_nan=False))
            if demo:
                for e in idx:
                    f = out / f"simulator-{e['key']}.json"
                    if f.exists():
                        f.write_text(f.read_text().replace('"schema":1,', '"schema":1,"demo":true,', 1))
            for e in idx:
                log(f"[bt] {e['label']}: {'ok ab ' + str(e.get('coverage_from')) if e['available'] else e.get('reason')}")
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            msg("warnung", f"Backtests mit damaliger Indexzusammensetzung fehlgeschlagen: {exc}")

    sim_cache = cache / "simulator.json"
    if sim_cache.exists():
        sim_txt = sim_cache.read_text()
        if demo:
            sim_txt = sim_txt.replace('"schema":1,', '"schema":1,"demo":true,', 1)
        (out / "simulator.json").write_text(sim_txt)

    # 9) Schreiben
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fx_rates = {c: r5(fx_row[c], 6) for c in fx_row.index if pd.notna(fx_row[c])}
    excluded = {}
    for s in uni_syms:
        for code in q.at[s, "reasons"]:
            excluded[code] = excluded.get(code, 0) + 1
    excluded["no_data"] = excluded.get("no_data", 0) + (n_uni - n_priced)
    screen = {
        "schema": 1, "demo": demo, "generated_at": now, "asof": iso(asof), "data_age_days": int(data_age),
        "prev_month_end": iso(prev_d), "methodology_version": METHODOLOGY_VERSION, "params_hash": params_hash(),
        "pipeline_version": PIPELINE_VERSION, "status": overall,
        "universe": {"source": sources["universe"]["name"], "as_of": uni_as_of, "size": n_uni, "priced": n_priced,
                     "eligible": n_elig, "excluded_by_reason": excluded, "watchlist": watch_only,
                     "kind": sources["universe"].get("kind", "demo"), "size_index": sources["universe"].get("size_index"),
                     "tradable": (sources.get("tradable_de") or {}).get("filter"),
                     "emerging": int(universe["emerging"].sum()) if "emerging" in universe else None},
        "fx": {"date": iso(fx.index[fx.index <= asof].max()), "rates": fx_rates},
        "market": regime, "candidates": cands, "top_pick": top_pick,
        "top_pick_checks": {k: v for k, v in tp_info["checks"].items()}, "top_pick_vol_limit": r5(tp_info["vol_limit"]),
        "prev_candidates": prev_cands, "params": METHODOLOGY, "reason_text": core.REASON_TEXT | {"watchlist": "Nicht im Universum (Beobachtungsliste)"},
        "fields": fields, "rows": rows,
    }
    (out / "screen.json").write_text(json.dumps(sanitize(screen), default=_json_default, separators=(",", ":"), ensure_ascii=False))
    status = {
        "schema": 1, "demo": demo, "generated_at": now, "asof": iso(asof), "data_age_days": int(data_age),
        "overall": overall, "messages": messages, "sources": sources,
        "coverage": {"universe": n_uni, "priced": n_priced, "fresh": fresh, "eligible": n_elig,
                     "crosschecked": cc_n, "crosscheck_deviations": cc_bad},
        "candidates": len(cands), "top_pick": top_pick, "methodology_version": METHODOLOGY_VERSION,
        "pipeline_version": PIPELINE_VERSION, "runtime_s": round(time.time() - t0, 1),
        "backtest_available": bool(bt_res and bt_res.get("available")),
        "stage2": {"version": (s2 or {}).get("stage2_version"), "status": (s2 or {}).get("status"),
                   "top5": (s2 or {}).get("buy", []),
                   "scored": sum(1 for r in (s2 or {}).get("ranking", []) if (r.get("stage2") or {}).get("score") is not None),
                   "fundamentals_coverage": (s2 or {}).get("fundamentals_coverage")},
    }
    (out / "status.json").write_text(json.dumps(status, default=_json_default, ensure_ascii=False, indent=1))
    write_methodology(out)
    # Archiv (wird vom Workflow eingecheckt)
    if not demo:
        archive.mkdir(parents=True, exist_ok=True)
        hist_file.write_text(json.dumps(cand_hist, indent=1, sort_keys=True))
        snap_dir = archive / "screenings"
        snap_dir.mkdir(exist_ok=True)
        snap = {k: screen[k] for k in ("asof", "methodology_version", "params_hash", "pipeline_version", "status",
                                         "candidates", "top_pick", "market", "universe")}
        snap["top50"] = [[r[0], r[1], r[20], r[21], r[16], r[15]] for r in rows if r[21] and r[21] <= 50]
        (snap_dir / "latest.json").write_text(json.dumps(snap, default=_json_default, ensure_ascii=False, indent=1))
        if prev_d is not None and sc_prev is not None:
            month_file = snap_dir / f"{prev_d.strftime('%Y-%m')}.json"
            if not month_file.exists():
                ms = {"asof": iso(prev_d), "methodology_version": METHODOLOGY_VERSION, "params_hash": params_hash(),
                      "candidates": prev_cands,
                      "top50": [[s, int(sc_prev.at[s, 'rank']), r5(sc_prev.at[s, 'Z'])] for s in
                                sc_prev["rank"].dropna().sort_values().index[:50]]}
                month_file.write_text(json.dumps(ms, ensure_ascii=False, indent=1))
        if s2 and s2.get("ranking") is not None and s2.get("status") != "fehler":
            write_stage2_archive(archive / "stage2v2", s2, close, cur_series, fx_row)
        with (archive / "runs.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{now} asof={iso(asof)} status={overall} priced={n_priced}/{n_uni} eligible={n_elig} "
                     f"candidates={len(cands)} top={top_pick} v={METHODOLOGY_VERSION}\n")
        # Archiv-Index für die App
        (out / "archive").mkdir(exist_ok=True)
        idx = sorted(p.stem for p in snap_dir.glob("20*.json"))
        for pth in snap_dir.glob("20*.json"):
            (out / "archive" / pth.name).write_text(pth.read_text())
        (out / "archive" / "index.json").write_text(json.dumps({"months": idx}))
    if overall != "fehler":
        import shutil
        lg = cache / "last_good"
        if lg.exists():
            shutil.rmtree(lg)
        shutil.copytree(out, lg)
    log(f"Fertig: Status={overall}, Kandidaten={len(cands)}, Top Pick={top_pick}, Laufzeit {time.time() - t0:.0f}s")
    return 0 if overall != "fehler" else 3


def eur_prices(adj: pd.DataFrame, cur: pd.Series, fx: pd.DataFrame) -> pd.DataFrame:
    """Kurse in EUR (EZB-Referenzkurse, Vortageskurs an EZB-Feiertagen)."""
    fx_idx = fx_on_index(fx, adj.index)
    out = pd.DataFrame(np.nan, index=adj.index, columns=adj.columns)
    c = cur.reindex(adj.columns)
    for code, syms in c.groupby(c).groups.items():
        syms = list(syms)
        if code == "EUR":
            out[syms] = adj[syms]
        elif code in fx_idx.columns:
            out[syms] = adj[syms].div(fx_idx[code], axis=0)
    return out


def stage2_block(*, demo, universe, meta, panel, fx, fx_row, cur_series, bench_frames, currency, asof, today, f, sc, q,
                 elig, cands, top_pick, verified, watch_only, frames, cache, archive, sources, stage1_failed) -> dict:
    """Kennzahlen aktualisieren und Stage 2 berechnen. Wirft bei unerwarteten Fehlern (wird oben abgefangen)."""
    from . import fundamentals as fund
    from . import stage2
    adj = panel.adj
    win = adj.loc[adj.index > asof - pd.DateOffset(years=3, months=4)]
    eur = eur_prices(win, cur_series, fx)
    mdf = bench_frames.get("EUNL.DE")
    mkt = None
    if mdf is not None:
        mkt = mdf["adj"].dropna()
        mc = currency.get("EUNL.DE", "EUR")
        if mc and mc != "EUR":
            mkt = (mkt / fx_on_index(fx, mkt.index)[mc]).dropna()
    pool = core.select_candidates(f, sc, elig, 10 ** 6) if not stage1_failed else []
    elig_syms = [s for s in elig.index if bool(elig.get(s))]
    if demo:
        from .synthetic import demo_fundamentals
        store = fund.FundamentalsStore(demo_fundamentals(universe, frames, iso(asof), cands=list(cands)))
        stats = {"demo": True}
    else:
        store = fund.FundamentalsStore.load(cache / "fundamentals.json.gz")
        # Stage 2 v2 braucht Analystendaten nur für Kandidaten und die Momentum-Vergleichsgruppe
        qs_list, ts_list, boot = fund.plan_refresh(store, today, list(cands) + list(watch_only), pool, list(pool), FUNDAMENTALS)
        log(f"[stage2] Kennzahlen fällig: {len(qs_list)}, Jahreswerte fällig: {len(ts_list)}{' (Aufbauphase)' if boot else ''}")
        stats = fund.refresh(store, qs_list, ts_list, today, FUNDAMENTALS, boot, log=log)
        store.save(cache / "fundamentals.json.gz")
        snap = fund.write_weekly_snapshot(store, list(dict.fromkeys(list(cands) + list(pool))), archive / "fundamentals", today)
        if snap:
            log(f"[stage2] Wochen-Schnappschuss {snap.name} archiviert")
    snap90, snap_date = fund.load_snapshot_near(archive / "fundamentals", today - pd.Timedelta(days=90))
    cov = fund.coverage(store, list(pool) or elig_syms, today, STAGE2["fund_max_age_days"])
    stats["coverage"] = round(cov, 3)
    if demo:
        sources["fundamentals_stage2"] = {"name": "DEMO (synthetisch)", "ok": True, "type": "demo"}
    else:
        detail = (f"{stats.get('qs_ok', 0)} Kennzahlen- und {stats.get('ts_ok', 0)} Jahreswert-Abrufe ok, "
                  f"{stats.get('qs_fail', 0) + stats.get('ts_fail', 0)} Fehler, Abdeckung {cov:.0%}"
                  + (", Aufbauphase" if stats.get("boot") else "")
                  + (", gedrosselt – der Rest folgt im nächsten Lauf" if stats.get("blocked") else ""))
        sources["fundamentals_stage2"] = {"name": "Yahoo Finance (Kennzahlen, Analystenschätzungen; inoffiziell)",
                                          "ok": bool(cov >= STAGE2["ref_min_coverage"] and not stats.get("error")),
                                          "detail": detail, "type": "database"}
    stage1 = pd.DataFrame({"rank": sc["rank"], "Z": sc["Z"], "pct": sc["pct"], "data_ok": q["data_ok"],
                           "m6": f["m6"], "m12": f["m12"], "vol": f["vol"]})
    mname = next((b["name"] for b in BENCHMARKS.values() if b["symbol"] == "EUNL.DE"), "MSCI World")
    s2src = {"prices": {"name": "Yahoo Finance (Kurse)", "type": "database", "asof": iso(asof)},
             "fundamentals": {"name": "Yahoo Finance (quoteSummary, Fundamentals-Zeitreihen)", "type": "database"},
             "estimates": {"name": "Analystenschätzungen über Yahoo Finance", "type": "secondary"},
             "fx": {"name": "EZB-Referenzkurse", "type": "official"},
             "sector": {"name": "GICS-Sektor laut iShares-Bestandsliste", "type": "database"},
             "benchmark": {"name": mname, "type": "database"}}
    from .stage2v2 import peer_group, run_stage2_v2
    peers = peer_group(sc, f, elig, pool)
    res = run_stage2_v2(loc=win, eur=eur, mkt=mkt, market_name=mname, asof=asof, today=today, meta=meta, stage1=stage1,
                        cands=[] if stage1_failed else list(cands), peers=peers, store=store, fx_row=fx_row,
                        snap90=snap90, demo=demo, sources=s2src, fund_stats=stats)
    res["fundamentals_coverage"] = round(cov, 3)
    if stage1_failed:
        res["status"] = "fehler"
        res["messages"].insert(0, {"level": "fehler", "text": "Stage 1 hat wegen Datenproblemen keine Kandidaten "
                                                              "freigegeben – Stage 2 bewertet deshalb nichts."})
    res["live_track"] = live_track(archive / "stage2v2", adj, cur_series, fx, mkt, asof)
    return res


def write_stage2_archive(folder: Path, s2: dict, close: pd.DataFrame, cur: pd.Series, fx_row: pd.Series) -> None:
    """Live-Protokoll: Stage-2-Rangfolge je Monat (letzter Lauf des Monats bleibt stehen)."""
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in s2.get("ranking", []):
        rows.append({"symbol": r["symbol"], "name": r.get("name"), "stage1_rank": (r.get("stage1") or {}).get("rank"),
                     "stage2_rank": (r.get("stage2") or {}).get("rank"), "score": (r.get("stage2") or {}).get("score"),
                     "decision": "TOP5" if r.get("buy") else "REST", "price_only": (r.get("stage2") or {}).get("price_only")})
    snap = {"asof": s2.get("asof"), "stage2_version": s2.get("stage2_version"), "status": s2.get("status"),
            "buy": s2.get("buy", []), "ranking": rows}
    txt = json.dumps(sanitize(snap), ensure_ascii=False, indent=1, default=_json_default)
    (folder / "latest.json").write_text(txt)
    if s2.get("asof"):
        (folder / f"{s2['asof'][:7]}.json").write_text(txt)


def live_track(folder: Path, adj: pd.DataFrame, cur: pd.Series, fx: pd.DataFrame, mkt: pd.Series | None,
               asof: pd.Timestamp) -> dict:
    """Echte Out-of-Sample-Bilanz: Wie entwickelten sich frühere Stage-2-Entscheidungen bis heute (EUR, ggü. MSCI World)?"""
    files = sorted(folder.glob("20[0-9][0-9]-[0-9][0-9].json")) if folder.exists() else []
    rows, months = [], 0
    for fp in files:
        try:
            js = json.loads(fp.read_text())
            d = pd.Timestamp(js.get("asof"))
        except Exception:  # noqa: BLE001
            continue
        if (asof - d).days < 28:
            continue
        months += 1
        m0 = core.price_at(mkt.to_frame("m"), d, 12)["m"] if mkt is not None else np.nan
        m1 = core.price_at(mkt.to_frame("m"), asof, 12)["m"] if mkt is not None else np.nan
        mret = m1 / m0 - 1 if np.isfinite(m0) and np.isfinite(m1) else np.nan
        for e in js.get("ranking", []):
            sym, c = e.get("symbol"), cur.get(e.get("symbol"))
            ret = np.nan
            if sym in adj.columns and c:
                p0 = core.price_at(adj[[sym]], d, 12)[sym]
                p1 = core.price_at(adj[[sym]], asof, 40)[sym]
                f0 = 1.0 if c == "EUR" else fx_on_index(fx, pd.DatetimeIndex([d])).iloc[0].get(c, np.nan)
                f1 = 1.0 if c == "EUR" else fx_on_index(fx, pd.DatetimeIndex([asof])).iloc[0].get(c, np.nan)
                if all(np.isfinite(x) for x in (p0, p1, f0, f1)) and p0 > 0:
                    ret = (p1 / f1) / (p0 / f0) - 1
            rows.append({"month": fp.stem, "symbol": sym, "decision": e.get("decision"), "ret": ret, "mkt": mret})
    groups = []
    spec = [("Stage 2 Top 5", {"TOP5"}), ("Stage-1-Kandidaten außerhalb der Stage-2-Top-5", {"REST"}), ("Alle Stage-1-Kandidaten", None)]
    for label, codes in spec:
        sub = [r for r in rows if np.isfinite(r["ret"]) and np.isfinite(r["mkt"]) and (codes is None or r["decision"] in codes)]
        if not sub:
            groups.append({"label": label, "n": 0})
            continue
        exc = np.array([r["ret"] - r["mkt"] for r in sub])
        groups.append({"label": label, "n": len(sub), "avg_return": r5(float(np.mean([r["ret"] for r in sub]))),
                       "avg_excess": r5(float(exc.mean())), "hit_rate": r5(float((exc > 0).mean()))})
    note = ("Echte Out-of-Sample-Beobachtung: Rendite von jeder Monatsentscheidung bis heute in EUR, verglichen mit dem "
            "MSCI World im selben Zeitraum. Noch zu wenige Beobachtungen für statistische Aussagen."
            if months else "Noch keine abgeschlossene Beobachtung. Die erste Auswertung erscheint etwa einen Monat nach "
                           "dem ersten Stage-2-Lauf und wird jeden Monat aussagekräftiger.")
    return {"months": months, "first": files[0].stem if files else None, "groups": groups, "note": note,
            "rows": [{k: (r5(v) if isinstance(v, float) else v) for k, v in r.items()} for r in rows[-80:]]}


def write_details(out: Path, detail_set: list, panel: core.Panel, meta: pd.DataFrame, f: pd.DataFrame,
                  cur: pd.Series, demo: bool, cache: Path, asof: pd.Timestamp) -> dict:
    from .details import DetailFetcher
    fetcher = None
    rng = np.random.default_rng(3)
    if not demo:
        fetcher = DetailFetcher(lambda u, h=None: http_json(u, h), lambda u: http_get(u), cache / "details",
                                pd.Timestamp.utcnow().tz_localize(None).normalize(), log)
    n = 0
    for s in detail_set:
        if s not in panel.adj.columns:
            continue
        ser = panel.adj[s].dropna()
        ser = ser[ser.index >= asof - pd.DateOffset(years=2)]
        name = meta.at[s, "name"] if s in meta.index else s
        rec = {"symbol": s, "name": name, "asof": iso(asof), "currency": cur.get(s),
               "series": [[iso(d), r5(v, 6)] for d, v in ser.items()],
               "ma200_series": [[iso(d), r5(v, 6)] for d, v in ser.rolling(200, min_periods=200).mean().dropna().items()]}
        if demo:
            from .synthetic import demo_details
            rec.update(demo_details(s, name, rng))
        elif fetcher is not None:
            is_us = "." not in s
            try:
                rec.update(fetcher.fetch(s, name, is_us, r5(f.at[s, "last_close"])))
            except Exception as exc:  # noqa: BLE001
                rec["detail_error"] = str(exc)[:200]
        fn = re.sub(r"[^A-Za-z0-9._-]", "_", s) + ".json"
        (out / "details" / fn).write_text(json.dumps(rec, default=_json_default, ensure_ascii=False, separators=(",", ":")))
        n += 1
    srcs = {}
    if fetcher is not None:
        st = fetcher.summary()
        sec_ok = st["sec"] in ("nicht genutzt", "ok") or bool(re.match(r"^[1-9]\d* ok", st["sec"]))
        srcs = {"sec": {"name": "SEC EDGAR (XBRL, Filings)", "ok": sec_ok,
                        "detail": st["sec"], "type": "official", "url": "https://www.sec.gov/edgar/search/"},
                "fundamentals_yahoo": {"name": "Yahoo Finance (Unternehmensdaten)", "ok": fetcher.ok["yahoo_info"],
                                       "detail": st["yahoo_info"], "type": "database"},
                "news": {"name": "Google News (RSS)", "ok": fetcher.ok["news"], "detail": st["news"],
                         "type": "secondary"}}
    return {"count": n, "sources": srcs}


def write_monthly(out: Path, close: pd.DataFrame, fx_idx: pd.DataFrame, cur: pd.Series, bench_frames: dict,
                  fx: pd.DataFrame, asof: pd.Timestamp) -> None:
    start = asof - pd.DateOffset(years=10)
    c = close[close.index >= start]
    me = c.groupby([c.index.year, c.index.month]).tail(1)
    me_ff = c.ffill(limit=10).loc[me.index]
    prices = {s: [r5(v, 5) for v in me_ff[s].values] for s in me_ff.columns}
    for sym, df in bench_frames.items():
        b = df["close"].reindex(c.index).ffill(limit=10).loc[me.index]
        prices[sym] = [r5(v, 5) for v in b.values]
    fxm = fx_on_index(fx, me.index)
    rates = {k: [r5(v, 6) for v in fxm[k].values] for k in fxm.columns if fxm[k].notna().any()}
    payload = {"dates": [iso(d) for d in me.index], "fx": rates, "prices": prices,
               "currency": {s: cur.get(s) for s in c.columns}}
    (out / "monthly.json").write_text(json.dumps(payload, separators=(",", ":"), default=_json_default))


def write_methodology(out: Path) -> None:
    changelog = []
    cl = ROOT / "CHANGELOG.md"
    if cl.exists():
        changelog = cl.read_text(encoding="utf-8").splitlines()[:80]
    (out / "methodology.json").write_text(json.dumps({
        "version": METHODOLOGY_VERSION, "params_hash": params_hash(), "params": METHODOLOGY,
        "variants": BACKTEST_VARIANTS, "tax": TAX, "costs": COST_SCENARIOS, "backtest": BACKTEST,
        "stage2": {"version": "2.0.0", "name": "Fortsetzungs-Rangfolge",
                   "signals": __import__("pipeline.stage2v2", fromlist=["SIGNALS"]).SIGNALS,
                   "rule": "Score = 10 × (½ Kursteil + ½ Gewinnteil), Perzentile gegen die Momentum-Vergleichsgruppe; Top 5 kaufen."},
        "changelog": changelog,
    }, ensure_ascii=False, indent=1))


def _fail(out: Path, messages, sources, demo, reason, cache: Path | None = None) -> int:
    """Heutiger Lauf gescheitert: letzte gültige Daten (falls vorhanden) bleiben sichtbar, Status sagt die Wahrheit."""
    import shutil
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    messages.append({"level": "fehler", "text": f"Heutiger Datenlauf fehlgeschlagen: {reason}"})
    asof, overall = None, "fehler"
    lg = (cache or Path("cache")) / "last_good"
    if lg.exists() and (lg / "screen.json").exists():
        for item in lg.iterdir():
            dst = out / item.name
            if item.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(item, dst)
            else:
                shutil.copy2(item, dst)
        try:
            asof = json.loads((lg / "screen.json").read_text()).get("asof")
        except Exception:  # noqa: BLE001
            asof = None
        if asof:
            age = (pd.Timestamp.utcnow().tz_localize(None).normalize() - pd.Timestamp(asof)).days
            overall = "warnung" if age <= 4 else "fehler"
            messages.append({"level": "warnung", "text": f"Angezeigt werden die letzten gültigen Daten vom {asof}."})
    (out / "status.json").write_text(json.dumps({
        "schema": 1, "demo": demo, "generated_at": now, "asof": asof, "overall": overall, "messages": messages,
        "sources": sources, "methodology_version": METHODOLOGY_VERSION, "pipeline_version": PIPELINE_VERSION,
        "last_run_failed": True,
    }, ensure_ascii=False, indent=1, default=_json_default))
    log(f"ABBRUCH: {reason}")
    return 2


def sanitize(o):
    """Rekursiv: NaN/Unendlich -> None, numpy-Typen -> Python. Ein einziges NaN macht JSON für Browser unlesbar."""
    if isinstance(o, dict):
        return {str(k): sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [sanitize(v) for v in o]
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return float(o) if math.isfinite(float(o)) else None
    if o is pd.NaT:
        return None
    return o


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return r5(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.strftime("%Y-%m-%d")
    if isinstance(o, set):
        return sorted(o)
    return str(o)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Momentum Lab Datenlauf")
    ap.add_argument("--mode", choices=["live", "demo"], default="live")
    ap.add_argument("--out", default="site/data")
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--archive", default="archive")
    ap.add_argument("--asof", default=None, help="nur Demo: Stichtag")
    ap.add_argument("--full-refresh", action="store_true")
    ap.add_argument("--skip-backtest", action="store_true")
    ap.add_argument("--force-backtest", action="store_true")
    ap.add_argument("--skip-details", action="store_true")
    args = ap.parse_args(argv)
    if os.environ.get("FULL_REFRESH", "").lower() in ("1", "true", "yes"):
        args.full_refresh = True
    try:
        return run(args)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        return _fail(out, [], {}, args.mode == "demo", f"Unerwarteter Fehler im Datenlauf: {exc}", Path(args.cache))


if __name__ == "__main__":
    sys.exit(main())
