"""Stage 2 – Fortsetzungsanalyse der Stage-1-Kandidaten (Methodik S2 v1.0.0).

Stage 1 (core.py) bleibt unverändert und liefert die Top 10. Stage 2 prüft jede dieser Aktien zusätzlich in
sechs Kategorien, berechnet einen Score von 0 bis 10, eine Datenqualitäts-Stufe, eine Risiko-Stufe
(Anti-Peak/Anti-Chasing), eine Sparplan-Entscheidung und eine Outperformance-Einschätzung gegenüber dem
MSCI World. Die kursbasierten Bausteine nutzen dieselben Funktionen live und im Teil-Backtest.

Skalierung: Jede Kennzahl wird als Perzentil (0 bis 1) gegen eine dokumentierte Vergleichsgruppe gemessen
(config.STAGE2_CATEGORIES). Perzentile sind robust gegen Ausreißer, kein Einzelwert kann eine Kategorie
dominieren, und fehlende Werte werden NICHT ersetzt: Sie zählen als fehlend und senken die Datenqualität.
Kategorie-Score = 10 × Mittel der verfügbaren Perzentile (A und F: Mittel zweier gleich gewichteter Blöcke).
Gesamtscore = gewichtetes Mittel der Kategorien (Gewichte des Nutzers), nur wenn >= 80 % Gewicht berechenbar.
"""
from __future__ import annotations

import math
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import core
from .config import (FIN_SECTORS, STAGE2, STAGE2_CATEGORIES, STAGE2_MIN, STAGE2_VERSION, stage2_params_hash)
from .fundamentals import MINOR_UNITS

DECISION_ORDER = ["REJECT", "NO_ENTRY", "WATCHLIST", "STRONG_BUY", "EXCEPTIONAL"]
DECISION_LABEL = {
    "EXCEPTIONAL": "EXCEPTIONAL", "STRONG_BUY": "STRONG BUY CANDIDATE", "WATCHLIST": "WATCHLIST",
    "NO_ENTRY": "NO ENTRY", "REJECT": "REJECT", "HARD_RISK": "HARD RISK", "INSUFFICIENT_DATA": "INSUFFICIENT DATA",
}
DECISION_TEXT = {
    "EXCEPTIONAL": "Sehr starke Kombination aus Momentum, relativer Stärke, Fundamentaldaten und Risikoqualität. Sparplanstart möglich.",
    "STRONG_BUY": "Sparplanstart grundsätzlich möglich, es liegt kein hartes Risiko vor.",
    "WATCHLIST": "Interessant, aber derzeit keine bevorzugte Auswahl für einen neuen Sparplan.",
    "NO_ENTRY": "Keine Sparplanfreigabe.",
    "REJECT": "Schwache Gesamtqualität trotz Momentum.",
    "HARD_RISK": "Hartes Risiko: keine Sparplanfreigabe, unabhängig vom Score.",
    "INSUFFICIENT_DATA": "Die Datenlage reicht für eine Bewertung nicht aus. Keine Sparplanfreigabe.",
}
RISK_LEVELS = ["NORMAL", "ELEVATED", "HIGH", "CRITICAL"]
OUTPERF_LABEL = {"HIGH": "HIGH OUTPERFORMANCE POTENTIAL", "MODERATE": "MODERATE OUTPERFORMANCE POTENTIAL",
                 "MARKET_LIKE": "MARKET-LIKE POTENTIAL", "LOW": "LOW OUTPERFORMANCE POTENTIAL",
                 "INSUFFICIENT": "INSUFFICIENT DATA"}
DQ_LABEL = {"HIGH": "HIGH DATA QUALITY", "MEDIUM": "MEDIUM DATA QUALITY", "LOW": "LOW DATA QUALITY",
            "INSUFFICIENT": "INSUFFICIENT DATA"}
REF_LABEL = {"universe": "alle zulässigen MSCI-World-Aktien", "sector": "Aktien desselben Sektors",
             "peers": "Momentum-Vergleichsgruppe (Stage-1-Kandidaten)"}
REGION_BY_SUFFIX = {"": "Nordamerika", ".TO": "Nordamerika", ".V": "Nordamerika", ".T": "Pazifik", ".AX": "Pazifik",
                    ".HK": "Pazifik", ".SI": "Pazifik", ".NZ": "Pazifik"}


# =============================================================================== Formatierung (Texte)
def de_num(x, d=1) -> str:
    if x is None or not np.isfinite(x):
        return "–"
    s = f"{x:,.{d}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def de_pct(x, d=1, sign=True) -> str:
    if x is None or not np.isfinite(x):
        return "–"
    v = x * 100
    return f"{'+' if sign and v > 0.0000001 else ''}{de_num(v, d)} %"


def de_date(iso: str | None) -> str:
    if not iso:
        return "–"
    try:
        return pd.Timestamp(iso).strftime("%d.%m.%Y")
    except Exception:  # noqa: BLE001
        return str(iso)


def _f(x, digits=5):
    """JSON-taugliche Zahl (None statt NaN)."""
    if x is None or isinstance(x, str):
        return x
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return 0.0 if x == 0 else float(f"{x:.{digits}g}")


# =============================================================================== Kursbasierte Kennzahlen
def _series_at(s: pd.Series | None, target: pd.Timestamp, window_days: int) -> float:
    if s is None or s.empty:
        return np.nan
    sub = s.loc[(s.index > target - pd.Timedelta(days=window_days)) & (s.index <= target)].dropna()
    return float(sub.iloc[-1]) if len(sub) else np.nan


def _last_valid_means(recent: pd.DataFrame, n: int, lag: int = 0) -> pd.Series:
    """Mittel der letzten n gültigen Werte je Spalte (optional lag gültige Werte früher)."""
    out = {}
    for c in recent.columns:
        v = recent[c].to_numpy()
        v = v[np.isfinite(v)]
        if len(v) >= n + lag:
            out[c] = float(v[len(v) - lag - n: len(v) - lag].mean())
        else:
            out[c] = np.nan
    return pd.Series(out)


def price_metrics_at(loc: pd.DataFrame, eur: pd.DataFrame, mkt: pd.Series | None, asof: pd.Timestamp,
                     win: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Alle kursbasierten Stage-2-Kennzahlen zum Stichtag (nur Daten bis einschließlich asof).

    loc = bereinigte Kurse in Landeswährung, eur = dieselben Kurse in EUR, mkt = MSCI-World-ETF in EUR.
    """
    win = win or STAGE2["win"]
    W = win["price_window_days"]
    loc = loc.loc[loc.index <= asof]
    eur = eur.loc[eur.index <= asof].reindex(columns=loc.columns)
    cols = loc.columns
    out = pd.DataFrame(index=cols)
    mkt = mkt.loc[mkt.index <= asof].dropna() if mkt is not None else None

    def at(df, k):
        return core.price_at(df, asof - pd.DateOffset(months=k), W) if k else core.price_at(df, asof, 40)

    def mat(k):
        return _series_at(mkt, asof - pd.DateOffset(months=k), W if k else 40) if mkt is not None else np.nan

    ml = {k: at(loc, k) for k in range(0, 14)}
    me = {k: at(eur, k) for k in range(0, 37)}
    mm = np.array([mat(k) for k in range(0, 37)], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        # --- A: Momentum über mehrere Zeitfenster (Landeswährung, wie Stage 1)
        out["m12_1"] = ml[1] / ml[13] - 1
        out["m6_1"] = ml[1] / ml[7] - 1
        out["m3_1"] = ml[1] / ml[4] - 1
        out["m12_2"] = ml[2] / ml[13] - 1
        out["ret_1m"] = ml[0] / ml[1] - 1
        out["ret_3m"] = ml[0] / ml[3] - 1
        out["ret_6m"] = ml[0] / ml[6] - 1
        out["ret_12m"] = ml[0] / ml[12] - 1
        mr = pd.DataFrame({k: ml[k] / ml[k + 1] - 1 for k in range(1, 12)})       # 11 Monatsrenditen im 12-1-Fenster
        nvalid = mr.notna().sum(axis=1)
        out["pos_months"] = ((mr > 0).sum(axis=1) / nvalid).where(nvalid >= 9)
        # --- tägliche Renditen
        recent = loc.loc[loc.index > asof - pd.Timedelta(days=440)]
        lp = np.log(recent.where(recent > 0))
        lr = lp.diff()
        tail = lr.iloc[-252:]
        cnt = tail.notna().sum()
        sig = tail.std().where(cnt >= 200)
        out["sigma_d"] = sig
        t63 = lr.iloc[-63:]
        out["vol63"] = (t63.std() * math.sqrt(252)).where(t63.notna().sum() >= 50)
        # Informationsdiskretheit (Da, Gurun & Warachka 2014): Anteil Minus- minus Plus-Tage im 12-1-Fenster
        t13, t1 = asof - pd.DateOffset(months=12), asof - pd.DateOffset(months=1)
        lrw = loc.loc[(loc.index > t13 - pd.Timedelta(days=7)) & (loc.index <= t1)]
        lrw = np.log(lrw.where(lrw > 0)).diff()
        lrw = lrw.loc[lrw.index > t13]
        n_d = lrw.notna().sum()
        frac_pos = (lrw > 0).sum() / n_d
        frac_neg = (lrw < 0).sum() / n_d
        out["info_disc"] = (np.sign(out["m12_1"]) * (frac_neg - frac_pos)).where(n_d >= 150)
        # --- D: Trend
        p_now = ml[0]
        ma50 = _last_valid_means(recent, win["ma_short"])
        ma200 = _last_valid_means(recent, win["ma_long"])
        ma50_prev = _last_valid_means(recent, win["ma_short"], win["slope_lag"])
        ma200_prev = _last_valid_means(recent, win["ma_long"], win["slope_lag"])
        out["ma50"], out["ma200"] = ma50, ma200
        out["dist_ma50"] = p_now / ma50 - 1
        out["dist_ma200"] = p_now / ma200 - 1
        out["ma_spread"] = ma50 / ma200 - 1
        out["slope_ma50"] = ma50 / ma50_prev - 1
        out["slope_ma200"] = ma200 / ma200_prev - 1
        yr = loc.loc[loc.index > asof - pd.Timedelta(days=365)]
        hi = yr.max()
        out["prox_52w"] = p_now / hi
        has = yr.columns[yr.notna().any()]
        hi_date = yr[has].idxmax().reindex(cols) if len(has) else pd.Series(pd.NaT, index=cols)
        out["days_since_high"] = [(asof - d).days if pd.notna(d) else np.nan for d in hi_date]
        out["mdd_12m"] = (yr / yr.cummax() - 1).min()
        # Trendstabilität: R² des logarithmierten Kurses gegen die Zeit (6 Monate)
        w = lp.iloc[-win["r2"]:]
        m = w.notna().to_numpy()
        y = np.where(m, w.to_numpy(), 0.0)
        t = np.arange(len(w), dtype=float)[:, None] * np.ones((1, len(cols)))
        t = np.where(m, t, 0.0)
        n = m.sum(axis=0).astype(float)
        sx, sy = t.sum(0), y.sum(0)
        sxx, syy, sxy = (t * t).sum(0), (y * y).sum(0), (t * y).sum(0)
        den = (n * sxx - sx ** 2) * (n * syy - sy ** 2)
        r = np.where(den > 0, (n * sxy - sx * sy) / np.sqrt(np.where(den > 0, den, 1)), np.nan)
        r2 = np.where(n >= 0.85 * win["r2"], r ** 2, np.nan)
        r2 = np.where(np.isfinite(r) & (r < 0), -r2, r2)   # Abwärtstrend: negativ (stabil fallend ist kein Qualitätsmerkmal)
        out["r2_6m"] = r2
        # Höhere Hochs und höhere Tiefs (Monatshochs/-tiefs aus Schlusskursen)
        sub = loc.loc[loc.index > asof - pd.DateOffset(months=13)]
        if len(sub):
            g = sub.groupby([sub.index.year, sub.index.month])
            hi_m, lo_m = g.max(), g.min()
            both = (hi_m.diff() > 0) & (lo_m.diff() > 0)
            valid = hi_m.notna() & hi_m.shift(1).notna() & lo_m.notna() & lo_m.shift(1).notna()
            both, valid = both.iloc[-win["hh_months"]:], valid.iloc[-win["hh_months"]:]
            vcount = valid.sum()
            out["hh_hl"] = ((both & valid).sum() / vcount).where(vcount >= 10)
        else:
            out["hh_hl"] = np.nan
        # RSI (Wilder, 14 Tage) – nur ergänzend im Risikomodul
        px = recent.ffill(limit=5).iloc[-150:]
        d = px.diff()
        gain = d.clip(lower=0).ewm(alpha=1 / win["rsi"], adjust=False).mean().iloc[-1]
        loss = (-d.clip(upper=0)).ewm(alpha=1 / win["rsi"], adjust=False).mean().iloc[-1]
        rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
        out["rsi14"] = rsi.where(loss > 0, 100.0).where(px.notna().sum() >= 60)
        # --- F: Überhitzung in Standardabweichungen (Vergleich mit Momentum-Gruppe)
        out["ext50"] = out["dist_ma50"] / (sig * math.sqrt(win["ma_short"]))
        out["ext200"] = out["dist_ma200"] / (sig * math.sqrt(win["ma_long"]))
        out["accel_z"] = np.log(ml[0] / ml[1]) / (sig * math.sqrt(win["accel"]))
        q1 = np.log(ml[0] / ml[3])
        q0 = np.log(ml[3] / ml[12]) / 3
        out["z_acc"] = (q1 - q0) / (sig * math.sqrt(win["acc_recent"]) * math.sqrt(4 / 3))
        # --- C: relative Stärke in EUR gegenüber MSCI World
        out["r6_1_eur_log"] = np.log(me[1] / me[7])
        eur_recent = eur.loc[eur.index > asof - pd.Timedelta(days=400)]
        elr = np.log(eur_recent.where(eur_recent > 0)).diff().iloc[-252:]
        evol = (elr.std() * math.sqrt(252)).where(elr.notna().sum() >= 200)
        out["vol_12m_eur"] = evol
        out["ret_12m_eur"] = me[0] / me[12] - 1
        out["sharpe12"] = out["ret_12m_eur"] / evol
        R = np.column_stack([(me[k - 1] / me[k] - 1).to_numpy() for k in range(1, 37)])   # Spalte j = Monat k=j+1
        M = np.array([mm[k - 1] / mm[k] - 1 for k in range(1, 37)])
        for k, lab in ((3, "rs_world_3m"), (6, "rs_world_6m"), (12, "rs_world_12m")):
            out[lab] = (me[0] / me[k]) / (mm[0] / mm[k]) - 1
        valid = np.isfinite(R) & np.isfinite(M)[None, :]
        nv = valid.sum(1).astype(float)
        Rv, Mv = np.where(valid, R, 0.0), np.where(valid, M[None, :], 0.0)
        sx, sy = Mv.sum(1), Rv.sum(1)
        sxx, sxy = (Mv * Mv).sum(1), (Mv * Rv).sum(1)
        den = nv * sxx - sx ** 2
        beta = np.where(den > 0, (nv * sxy - sx * sy) / np.where(den > 0, den, 1), np.nan)
        alpha = np.where(nv > 0, (sy - beta * sx) / np.where(nv > 0, nv, 1), np.nan)
        E = np.where(valid, R - alpha[:, None] - beta[:, None] * M[None, :], np.nan)   # Residuen (Marktmodell, 36 M)
        # Marktbereinigtes Momentum: Rendite minus Beta × MSCI World in den Monaten t-12 ... t-2 (jüngster Monat
        # ausgelassen), geteilt durch die Restschwankung -> nur der Teil, den der Markt NICHT erklärt.
        A = np.where(valid, R - beta[:, None] * M[None, :], np.nan)[:, 1:12]
        ce = np.isfinite(A).sum(1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            sd = np.nanstd(E, axis=1, ddof=2)
            rm = np.nansum(A, axis=1) / (sd * np.sqrt(np.maximum(ce, 1)))
        rm = np.where((nv >= win["resid_min"]) & (ce >= 9) & (sd > 0), rm, np.nan)
        out["resid_mom"] = rm
        out["beta_36m"] = np.where(nv >= win["resid_min"], beta, np.nan)
        v12 = valid[:, :win["beat_months"]]
        n12 = v12.sum(1)
        beats = ((R[:, :win["beat_months"]] > M[None, :win["beat_months"]]) & v12).sum(1)
        out["beat_n"] = np.where(n12 >= 10, beats, np.nan)
        out["beat_share"] = np.where(n12 >= 10, beats / np.where(n12 > 0, n12, 1), np.nan)
        down = valid & (M[None, :] < 0)
        nd = down.sum(1)
        exc = np.where(down, R - M[None, :], 0.0).sum(1)
        out["down_excess"] = np.where(nd >= win["down_min"], exc / np.where(nd > 0, nd, 1), np.nan)
        out["last_close_loc"] = p_now
    # Markt (MSCI World, EUR)
    mret = lambda k: (mm[0] / mm[k] - 1) if np.isfinite(mm[0]) and np.isfinite(mm[k]) else np.nan  # noqa: E731
    market = {"ret_1m": mret(1), "ret_3m": mret(3), "ret_6m": mret(6), "ret_12m": mret(12)}
    if mkt is not None and len(mkt) > 260:
        mk = mkt.loc[mkt.index > asof - pd.Timedelta(days=400)]
        mlr = np.log(mk).diff().iloc[-252:]
        market["vol_12m"] = float(mlr.std() * math.sqrt(252))
        yrm = mkt.loc[mkt.index > asof - pd.Timedelta(days=365)]
        market["mdd_12m"] = float((yrm / yrm.cummax() - 1).min())
        market["sharpe12"] = market["ret_12m"] / market["vol_12m"] if market["vol_12m"] else np.nan
        market["asof"] = mkt.index[-1].strftime("%Y-%m-%d")
        market["last"] = float(mkt.iloc[-1])
    out = out.replace([np.inf, -np.inf], np.nan)
    return out, market


def _num(x) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return np.nan
    return x if math.isfinite(x) else np.nan


def _true(x) -> bool:
    """Nur echtes True zählt (NaN/None/fehlend = False)."""
    return isinstance(x, (bool, np.bool_)) and bool(x)


def trend_status(r: pd.Series) -> str:
    """Regelbasierte Trend-Einordnung über die Lage von Kurs, 50- und 200-Tage-Linie (klassische Stufenanalyse)
    plus statistischem Beschleunigungstest: Weicht das letzte Quartal um mehr als 2 Standardabweichungen vom
    Tempo der drei Quartale davor ab, gilt der Trend als beschleunigend bzw. schwächer werdend."""
    p, ma50, ma200 = _num(r.get("last_close_loc")), _num(r.get("ma50")), _num(r.get("ma200"))
    if not all(np.isfinite(x) for x in (p, ma50, ma200)):
        return "nicht bestimmbar"
    if p < ma200:
        return "Trendbruch"
    za, s50, s200 = _num(r.get("z_acc")), _num(r.get("slope_ma50")), _num(r.get("slope_ma200"))
    if (p < ma50 and not (s50 > 0)) or (np.isfinite(za) and za <= -2):
        return "Schwächer werdender Trend"
    if ma50 > ma200 and s200 > 0:   # Rücksetzer unter die 50-Tage-Linie bei steigender Linie gehören zum Aufwärtstrend
        return "Beschleunigender Aufwärtstrend" if np.isfinite(za) and za >= 2 and p > ma50 else "Gesunder Aufwärtstrend"
    return "Seitwärtsbewegung"


def group_relative(x: pd.Series, groups: pd.Series, ref_mask: pd.Series, min_n: int) -> pd.Series:
    """x minus Gruppenmittel (berechnet über die Vergleichsgruppe); zu kleine Gruppen -> NaN."""
    ref = x[ref_mask.reindex(x.index).fillna(False).astype(bool) & x.notna()]
    gref = groups.reindex(ref.index)
    means = ref.groupby(gref).mean()
    counts = ref.groupby(gref).count()
    ok = counts[counts >= min_n].index
    g = groups.reindex(x.index)
    mean_for = g.map(means.where(means.index.isin(ok)))
    return x - mean_for


def home_groups(symbols, countries: pd.Series, eligible: pd.Series, min_n: int) -> pd.Series:
    """Heimatmarkt: Land, wenn genug Aktien zulässig sind, sonst MSCI-Region (nach Börsenkürzel)."""
    elig_counts = countries[eligible.reindex(countries.index).fillna(False).astype(bool)].value_counts()
    out = {}
    for s in symbols:
        c = countries.get(s)
        if isinstance(c, str) and c and elig_counts.get(c, 0) >= min_n:
            out[s] = c
        else:
            suf = "" if "." not in s else "." + s.split(".", 1)[1]
            out[s] = REGION_BY_SUFFIX.get(suf, "Europa & Nahost")
    return pd.Series(out)


# =============================================================================== Fundamentale Kennzahlen
def _major(price, cur):
    if price is None or cur is None:
        return price, cur
    if cur in MINOR_UNITS:
        major, f = MINOR_UNITS[cur]
        return price / f, major
    return price, cur


def _convert(amount, from_cur, to_cur, fx_row) -> float | None:
    if amount is None or from_cur is None or to_cur is None:
        return None
    if from_cur == to_cur:
        return amount
    rf = 1.0 if from_cur == "EUR" else fx_row.get(from_cur, np.nan)
    rt = 1.0 if to_cur == "EUR" else fx_row.get(to_cur, np.nan)
    if not (np.isfinite(rf) and np.isfinite(rt)) or rf == 0:
        return None
    return amount / rf * rt


def _mean(vals):
    v = [x for x in vals if x is not None and np.isfinite(x)]
    return float(np.mean(v)) if v else None


def fundamental_metrics(store, symbols, today: pd.Timestamp, fx_row: pd.Series,
                        snap90: pd.DataFrame | None = None) -> pd.DataFrame:
    """Kennzahlen aus dem Fundamentaldaten-Speicher. Veraltete Daten (> 21 Tage) zählen als fehlend."""
    p = STAGE2
    rows = {}
    for s in symbols:
        e = store.data.get(s) or {}
        q, ts = e.get("qs"), e.get("ts")
        age_q = store.age(s, "qs", today) if q else np.inf
        age_t = store.age(s, "ts", today) if ts else np.inf
        r = {"fund_at": e.get("qs_at") if q else None, "fund_age": age_q, "ts_at": e.get("ts_at") if ts else None,
             "ts_age": age_t, "fund_err": e.get("qs_err")}
        if q and age_q <= p["fund_max_age_days"]:
            price, cur = _major(q.get("price"), q.get("currency"))
            fin = q.get("fin_currency") or cur
            price_fin = _convert(price, cur, fin, fx_row) if price else None

            def ey(eps, pe):
                ours = eps / price_fin if eps is not None and price_fin else None
                yah = 1.0 / pe if pe and pe > 0 else None
                if ours is not None and yah is not None and ours > 0 and not (1 / 3 <= ours / yah <= 3):
                    return None, True         # widersprüchliche Daten (z. B. Währungsfehler) -> nicht verwenden
                return (ours if ours is not None else yah), False
            r["ey_fwd"], bad1 = ey(q.get("eps_fwd"), q.get("pe_fwd"))
            r["ey_ttm"], bad2 = ey(q.get("eps_ttm"), q.get("pe_ttm"))
            r["ey_inconsistent"] = bad1 or bad2
            evx = q.get("ev_ebitda")
            r["ebitda_ev"] = 1.0 / evx if evx else None
            r["sp"] = 1.0 / q["ps"] if q.get("ps") and q["ps"] > 0 else None
            r["bp"] = 1.0 / q["pb"] if q.get("pb") and q["pb"] > 0 else None
            tr = q.get("trend") or {}
            g1 = (tr.get("+1y") or {}).get("eps_growth")
            pe_f = q.get("pe_fwd")
            r["peg"] = pe_f / (g1 * 100) if pe_f and pe_f > 0 and g1 is not None and g1 > 0 else None
            r["exp_growth"] = g1
            for k in ("roe", "roa", "op_margin", "profit_margin", "gross_margin", "rev_growth", "eps_growth",
                      "current_ratio", "pe_ttm", "pe_fwd", "ev_ebitda", "ps", "pb", "analysts", "eps_fwd", "eps_ttm",
                      "fcf", "revenue", "market_cap", "rec_mean", "target_mean"):
                r[k] = q.get(k)
            r["de"] = q["de_pct"] / 100.0 if q.get("de_pct") is not None else None
            r["fcf_margin"] = q["fcf"] / q["revenue"] if q.get("fcf") is not None and q.get("revenue") and q["revenue"] > 0 else None
            r["eps_fwd_neg"] = bool(q.get("eps_fwd") is not None and q["eps_fwd"] < 0)
            br, c30, c90, up, down, n_an = [], [], [], 0.0, 0.0, None
            for per in ("0y", "+1y"):
                t = tr.get(per) or {}
                n = t.get("eps_n")
                if n and n > 0 and (t.get("up30") is not None or t.get("down30") is not None):
                    br.append(max(-1.0, min(1.0, ((t.get("up30") or 0) - (t.get("down30") or 0)) / n)))
                    if per == "0y":
                        up, down, n_an = t.get("up30") or 0, t.get("down30") or 0, n
                for lag, lst in (("eps_30d", c30), ("eps_90d", c90)):
                    a, b = t.get("eps_now"), t.get(lag)
                    if a is not None and b is not None and abs(b) > 1e-9:
                        lst.append((a - b) / abs(b))
            r["breadth30"], r["rev30"], r["rev90"] = _mean(br), _mean(c30), _mean(c90)
            r["up30"], r["down30"], r["analysts_0y"] = up, down, n_an
            t0 = tr.get("0y") or {}
            for k in ("eps_now", "eps_30d", "eps_60d", "eps_90d", "eps_avg", "rev_avg", "end"):
                r[f"{k}_0y"] = t0.get(k)
            hist = q.get("history") or []
            sur = [h.get("surprise") for h in hist if h.get("surprise") is not None]
            r["surprise4"] = float(np.mean(sur)) if len(sur) >= 2 else None
            r["surprise_last"] = sur[-1] if sur else None
            r["surprise_hist"] = hist
            r["next_earnings"] = q.get("next_earnings")
            r["fin_currency"] = fin
            # Umsatzrevision aus eigener Historie (gleiche Geschäftsjahre vergleichen)
            if snap90 is not None and s in snap90.index:
                old = snap90.loc[s]
                ch = []
                for per in ("0y", "+1y"):
                    t = tr.get(per) or {}
                    end, avg = t.get("end"), t.get("rev_avg")
                    if not end or not avg:
                        continue
                    ov = None
                    if str(old.get("rev0y_end")) == end:
                        ov = old.get("rev0y_avg")
                    elif str(old.get("rev1y_end")) == end:
                        ov = old.get("rev1y_avg")
                    try:
                        ov = float(ov)
                    except (TypeError, ValueError):
                        ov = None
                    if ov and np.isfinite(ov) and abs(ov) > 0:
                        ch.append((avg - ov) / abs(ov))
                r["rev_est90"] = _mean(ch)
        if ts and age_t <= p["ts_max_age_days"]:
            for k in ("roic_pre", "interest_cov", "dilution", "margin_change", "op_margin_fy", "fy_end"):
                r[k] = ts.get(k)
        rows[s] = r
    df = pd.DataFrame.from_dict(rows, orient="index")
    for k in ("ey_fwd", "ey_ttm", "ebitda_ev", "sp", "bp", "peg", "roe", "roa", "op_margin", "profit_margin",
              "fcf_margin", "de", "rev_growth", "eps_growth", "breadth30", "rev30", "rev90", "surprise4",
              "surprise_last", "margin_change", "roic_pre", "interest_cov", "dilution", "rev_est90"):
        if k not in df:
            df[k] = np.nan
        df[k] = pd.to_numeric(df[k], errors="coerce")
    return df.reindex(list(symbols))


# =============================================================================== Perzentile und Kategorien
def _pct_against(x: np.ndarray, ref: np.ndarray) -> np.ndarray:
    ref = np.sort(ref[np.isfinite(ref)])
    out = np.full(len(x), np.nan)
    if len(ref) == 0:
        return out
    ok = np.isfinite(x)
    lo = np.searchsorted(ref, x[ok], side="left")
    hi = np.searchsorted(ref, x[ok], side="right")
    out[ok] = (lo + 0.5 * (hi - lo)) / len(ref)
    return out


def applies(rule: str, sector) -> bool:
    fin = sector in FIN_SECTORS
    return rule == "all" or (rule == "fin" and fin) or (rule == "nonfin" and not fin)


def metric_defs(cats=None):
    cats = cats or STAGE2_CATEGORIES
    for c, spec in cats.items():
        for key, label, d, ref, block, rule, fmt in spec["metrics"]:
            yield c, {"key": key, "label": label, "dir": d, "ref": ref, "block": block, "rule": rule, "fmt": fmt}


def score_categories(X: pd.DataFrame, sector: pd.Series, eligible: pd.Series, peers, cats=None, mins=None,
                     min_cov: float | None = None, min_count: int = 30) -> dict:
    """Perzentile je Kennzahl und Kategorie-Scores für alle Symbole in X.

    Eine Kennzahl ist für ALLE Aktien aktiv oder inaktiv (gleiche Regeln für alle): aktiv nur, wenn in
    ihrer Vergleichsgruppe genug Werte vorhanden sind. Nicht anwendbare Kennzahlen (z. B. Free-Cashflow-
    Marge bei Banken) zählen weder als vorhanden noch als fehlend.
    """
    cats = cats or STAGE2_CATEGORIES
    mins = mins or STAGE2_MIN
    min_cov = STAGE2["ref_min_coverage"] if min_cov is None else min_cov
    idx = X.index
    sector = sector.reindex(idx)
    elig = eligible.reindex(idx).fillna(False).astype(bool)
    peer_mask = pd.Series(idx.isin(list(peers)), index=idx)
    pct = pd.DataFrame(index=idx)
    status = {}
    app = {}
    for c, m in metric_defs(cats):
        key = m["key"]
        x = pd.to_numeric(X[key], errors="coerce") if key in X else pd.Series(np.nan, index=idx)
        xv = (x * m["dir"]).to_numpy(dtype=float)
        appl = pd.Series([applies(m["rule"], sector.get(s)) for s in idx], index=idx)
        app[key] = appl
        if m["ref"] == "peers":
            ref_mask = peer_mask & appl
        else:
            ref_mask = elig & appl
        n_ref = int(ref_mask.sum())
        n_val = int((ref_mask & x.notna()).sum())
        cov = n_val / n_ref if n_ref else 0.0
        active = n_ref > 0 and cov >= min_cov and n_val >= min(min_count, n_ref)
        status[key] = {"category": c, "active": bool(active), "coverage": round(cov, 3), "n": n_val, "ref": m["ref"]}
        p = np.full(len(idx), np.nan)
        if active:
            refvals = xv[(ref_mask & x.notna()).to_numpy()]
            if m["ref"] == "sector":
                p = _pct_against(xv, refvals)          # Fallback: ganze anwendbare Gruppe
                sref = pd.Series(xv, index=idx)[(ref_mask & x.notna())]
                ssec = sector.reindex(sref.index)
                for sec_name, grp in sref.groupby(ssec):
                    if len(grp) < STAGE2["sector_min_n"]:
                        continue
                    members = (sector == sec_name).to_numpy()
                    p[members] = _pct_against(xv[members], grp.to_numpy())
            else:
                p = _pct_against(xv, refvals)
            p = np.where(appl.to_numpy(), p, np.nan)
        pct[key] = p
    # Kategorien (vektorisiert: Perzentil-Matrix je Kategorie)
    scores = pd.DataFrame(index=idx)
    detail = {}
    n = len(idx)
    for c, spec in cats.items():
        mets = spec["metrics"]
        act = [m for m in mets if status[m[0]]["active"]]
        req = mins.get(c, {})
        if not act:
            scores[c] = np.nan
            detail[c] = {"available": pd.Series(0, index=idx), "applicable": pd.Series(0, index=idx)}
            continue
        P = np.column_stack([pct[m[0]].to_numpy(dtype=float) for m in act])
        A = np.column_stack([app[m[0]].to_numpy(dtype=bool) for m in act])
        av = A & np.isfinite(P)
        n_av, n_ap = av.sum(1), A.sum(1)
        ok = np.ones(n, dtype=bool)
        if spec.get("blocks"):
            bmeans = []
            for b in spec["blocks"]:
                cols_b = [j for j, m in enumerate(act) if m[4] == b]
                need = req.get("blocks", {}).get(b, 1)
                if not cols_b:
                    ok &= need <= 0
                    continue
                cnt = av[:, cols_b].sum(1)
                ok &= cnt >= need
                with np.errstate(invalid="ignore", divide="ignore"):
                    bm = np.where(cnt > 0, np.where(av[:, cols_b], P[:, cols_b], 0.0).sum(1) / np.maximum(cnt, 1), np.nan)
                bmeans.append(bm)
            val = np.nanmean(np.column_stack(bmeans), axis=1) if bmeans else np.full(n, np.nan)
        else:
            if "min" in req:
                ok &= n_av >= req["min"]
            if "share" in req:
                ok &= (n_ap > 0) & (n_av > 0) & (n_av >= req["share"] * n_ap)
            if "core_any" in req:
                cj = [j for j, m in enumerate(act) if m[0] in req["core_any"]]
                ok &= av[:, cj].any(1) if cj else False
            with np.errstate(invalid="ignore", divide="ignore"):
                val = np.where(n_av > 0, np.where(av, P, 0.0).sum(1) / np.maximum(n_av, 1), np.nan)
        scores[c] = np.where(ok & np.isfinite(val), 10.0 * val, np.nan)
        detail[c] = {"available": pd.Series(n_av, index=idx), "applicable": pd.Series(n_ap, index=idx)}
    return {"pct": pct, "scores": scores, "status": status, "detail": detail, "applies": app}


def final_scores(scores: pd.DataFrame, weights: dict | None = None, min_w: float | None = None) -> pd.DataFrame:
    weights = weights or STAGE2["weights"]
    min_w = STAGE2["min_weight_available"] if min_w is None else min_w
    out = pd.DataFrame(index=scores.index)
    wsum = pd.Series(0.0, index=scores.index)
    acc = pd.Series(0.0, index=scores.index)
    for c, w in weights.items():
        if c not in scores:
            continue
        ok = scores[c].notna()
        wsum += np.where(ok, w, 0.0)
        acc += np.where(ok, w * scores[c].fillna(0.0), 0.0)
    total_w = sum(w for c, w in weights.items() if c in scores)
    share = wsum / total_w if total_w else wsum * 0
    out["weight_available"] = share
    out["score"] = (acc / wsum).where((share >= min_w - 1e-9) & (wsum > 0))
    return out


# =============================================================================== Risiko, Entscheidung, Outperformance
def peer_thresholds(X: pd.DataFrame, peers) -> dict:
    rp = STAGE2["risk"]
    P = X.loc[X.index.isin(list(peers))]
    q = lambda col, p: float(P[col].dropna().quantile(p)) if col in P and P[col].notna().sum() >= 10 else np.nan  # noqa: E731
    return {"ext50": q("ext50", rp["ext_peer_pct"]), "ext200": q("ext200", rp["ext_peer_pct"]),
            "vol63": q("vol63", rp["vol_peer_pct"]), "n_peers": int(len(P))}


def risk_assessment(r: pd.Series, thr: dict, pct_row: pd.Series, today: pd.Timestamp, status: dict,
                    currency: str | None = None) -> dict:
    """Anti-Peak-/Anti-Chasing-Modul. Je Konzept höchstens EIN Warnsignal (keine Doppelzählung korrelierter Werte):
    technisch: Abstand zu den Durchschnittslinien, Kursbeschleunigung, Volatilität (+ RSI ergänzend);
    fundamental: sinkende Gewinnerwartungen, verfehlte Quartalszahlen; Bewertung; Trend; Ereignis (nur Hinweis)."""
    rp = STAGE2["risk"]
    flags = []

    def add(code, group, text, metrics, counts=True):
        flags.append({"code": code, "group": group, "text": text, "metrics": {k: _f(v) for k, v in metrics.items()},
                      "counts": counts})
    v = lambda k: _num(r.get(k))  # noqa: E731
    e50 = np.isfinite(v("ext50")) and np.isfinite(thr.get("ext50", np.nan)) and v("ext50") >= thr["ext50"]
    e200 = np.isfinite(v("ext200")) and np.isfinite(thr.get("ext200", np.nan)) and v("ext200") >= thr["ext200"]
    if e50 or e200:
        parts = []
        if e50:
            parts.append(f"{de_pct(v('dist_ma50'))} über der 50-Tage-Linie ({de_num(v('ext50'), 1)} Standardabweichungen, Grenze {de_num(thr['ext50'], 1)})")
        if e200:
            parts.append(f"{de_pct(v('dist_ma200'))} über der 200-Tage-Linie ({de_num(v('ext200'), 1)} Standardabweichungen, Grenze {de_num(thr['ext200'], 1)})")
        add("T_EXT", "technisch", "Weit über dem Trend: " + " und ".join(parts) + ". Grenze = oberstes Zehntel der Momentum-Gruppe.",
            {"ext50": v("ext50"), "ext200": v("ext200"), "grenze50": thr.get("ext50"), "grenze200": thr.get("ext200")})
    if np.isfinite(v("accel_z")) and v("accel_z") >= rp["accel_z"]:
        ext = v("accel_z") >= rp["accel_z_extreme"]
        add("T_ACCEL", "technisch", f"{'Extreme ' if ext else ''}Kursbeschleunigung im letzten Monat: {de_pct(v('ret_1m'))}, das sind "
            f"{de_num(v('accel_z'), 1)} Standardabweichungen (Grenze {de_num(rp['accel_z'], 0)}, extrem ab {de_num(rp['accel_z_extreme'], 0)}).",
            {"accel_z": v("accel_z"), "ret_1m": v("ret_1m")})
    if np.isfinite(v("vol63")) and np.isfinite(thr.get("vol63", np.nan)) and v("vol63") >= thr["vol63"]:
        add("T_VOL", "technisch", f"Erhöhte Volatilität: {de_pct(v('vol63'), 0, False)} p. a. über 3 Monate "
            f"(oberstes Zehntel der Momentum-Gruppe ab {de_pct(thr['vol63'], 0, False)}).", {"vol63": v("vol63"), "grenze": thr["vol63"]})
    tech_main = len(flags)
    if np.isfinite(v("rsi14")) and v("rsi14") >= rp["rsi_extreme"]:
        add("T_RSI", "technisch (ergänzend)", f"RSI {de_num(v('rsi14'), 0)} (ab {de_num(rp['rsi_extreme'], 0)} extrem überkauft). "
            "Zählt nur zusammen mit einem anderen technischen Signal.", {"rsi14": v("rsi14")}, counts=tech_main > 0)
    ts = r.get("trend_status")
    if ts in ("Schwächer werdender Trend", "Trendbruch"):
        add("TR_WEAK", "Trend", f"Trendstatus: {ts}.", {"dist_ma50": v("dist_ma50"), "dist_ma200": v("dist_ma200"), "z_acc": v("z_acc")})
    b_neg = np.isfinite(v("breadth30")) and status.get("breadth30", {}).get("active") and v("breadth30") < 0
    r_neg = np.isfinite(v("rev90")) and status.get("rev90", {}).get("active") and v("rev90") < 0
    if b_neg or r_neg:
        parts = []
        if r_neg:
            parts.append(f"Gewinnschätzung {de_pct(v('rev90'))} gegenüber vor 90 Tagen")
        if b_neg:
            parts.append(f"mehr Analysten senken als erhöhen (Revisionsbreite {de_num(v('breadth30'), 2)})")
        div = np.isfinite(v("m3_1")) and v("m3_1") > 0
        add("F_REV", "fundamental", "Gewinnerwartungen sinken: " + ", ".join(parts) + (" – bei steigendem Kurs (Divergenz)." if div else "."),
            {"rev90": v("rev90"), "breadth30": v("breadth30"), "m3_1": v("m3_1")})
    if np.isfinite(v("surprise_last")) and v("surprise_last") < 0:
        add("F_MISS", "fundamental", f"Letzte Quartalszahlen unter den Erwartungen (Abweichung {de_pct(v('surprise_last'))}).",
            {"surprise_last": v("surprise_last")})
    p_ey = _num(pct_row.get("ey_fwd")) if pct_row is not None else np.nan
    expensive = np.isfinite(p_ey) and p_ey <= rp["val_sector_pct"]
    loss = _true(r.get("eps_fwd_neg"))
    if expensive or loss:
        pe = v("pe_fwd")
        txt = "Analysten erwarten einen Verlust für das nächste Geschäftsjahr." if loss else \
            f"Forward-KGV {de_num(pe, 1) if np.isfinite(pe) and pe > 0 else 'n. v.'} gehört zum teuersten Zehntel im eigenen Sektor."
        add("V_VAL", "Bewertung", txt, {"pe_fwd": pe, "perzentil_sektor": p_ey, "eps_fwd": v("eps_fwd")})
    ne = r.get("next_earnings")
    if isinstance(ne, str) and ne:
        days = (pd.Timestamp(ne) - today).days
        if 0 <= days <= STAGE2["event_window_days"]:
            add("E_EARNINGS", "Ereignis", f"Quartalszahlen voraussichtlich am {de_date(ne)}. Um diesen Termin sind starke "
                "Kurssprünge möglich.", {"tage": days}, counts=False)
    counted = [f for f in flags if f["counts"]]
    n_t = sum(1 for f in counted if f["group"].startswith("technisch"))
    n_f = sum(1 for f in counted if f["group"] == "fundamental")
    n_v = sum(1 for f in counted if f["group"] == "Bewertung")
    n_tr = sum(1 for f in counted if f["group"] == "Trend")
    total = n_t + n_f + n_v + n_tr
    extreme = np.isfinite(v("accel_z")) and v("accel_z") >= rp["accel_z_extreme"]
    has_vol = any(f["code"] == "T_VOL" for f in counted)
    if n_f >= 1 and (n_t >= 2 or n_v >= 1 or ts == "Trendbruch"):
        level, why = "CRITICAL", "Fundamentale Verschlechterung zusammen mit technischen oder Bewertungsrisiken."
    elif extreme or has_vol or total >= 2:
        level = "HIGH"
        why = "Extreme Kursbeschleunigung." if extreme else "Erhöhte Volatilität." if has_vol else f"{total} Warnsignale."
    elif total == 1:
        level, why = "ELEVATED", "Ein Warnsignal."
    else:
        level, why = "NORMAL", "Gesunder Verlauf, keine auffällige Überhitzung."
    return {"level": level, "why": why, "flags": flags, "counts": {"technisch": n_t, "fundamental": n_f,
                                                                    "bewertung": n_v, "trend": n_tr, "gesamt": total}}


def decide(score, dq: str, risk: dict, verified, is_candidate: bool) -> dict | None:
    if not is_candidate:
        return None
    reasons = []
    if dq == "INSUFFICIENT" or score is None or not np.isfinite(score):
        return {"code": "INSUFFICIENT_DATA", "label": DECISION_LABEL["INSUFFICIENT_DATA"], "sparplan": False,
                "text": DECISION_TEXT["INSUFFICIENT_DATA"], "reasons": ["Zu wenige verlässliche Daten für einen Score."],
                "base": None}
    s = round(float(score), 1)
    if risk["level"] == "CRITICAL":
        return {"code": "HARD_RISK", "label": DECISION_LABEL["HARD_RISK"], "sparplan": False, "text": DECISION_TEXT["HARD_RISK"],
                "reasons": [f"Risiko-Stufe CRITICAL: {risk['why']}"], "base": None, "score_rounded": s}
    base = next(code for thr, code in STAGE2["thresholds"] if s >= thr)
    code = base
    reasons.append(f"Score {de_num(s, 1)} liegt im Bereich {DECISION_LABEL[base]}.")

    def cap(limit, why):
        nonlocal code
        if DECISION_ORDER.index(code) > DECISION_ORDER.index(limit):
            code = limit
            reasons.append(why)
    if risk["level"] == "HIGH":
        if risk["counts"]["gesamt"] >= STAGE2["risk"]["high_exclude_flags"]:
            cap("NO_ENTRY", f"Risiko-Stufe HIGH mit {risk['counts']['gesamt']} Warnsignalen: kein Einstieg.")
        else:
            cap("WATCHLIST", "Risiko-Stufe HIGH: deutliche Abwertung, keine Sparplanfreigabe.")
    if dq == "LOW":
        cap("WATCHLIST", "Datenqualität LOW: keine Sparplanfreigabe.")
    if verified is not True:
        cap("WATCHLIST", "Kurs nicht von der Zweitquelle (iShares) bestätigt: keine Sparplanfreigabe.")
    return {"code": code, "label": DECISION_LABEL[code], "sparplan": code in ("EXCEPTIONAL", "STRONG_BUY"),
            "text": DECISION_TEXT[code], "reasons": reasons, "base": base, "score_rounded": s}


def outperformance(r: pd.Series, market: dict, risk: dict, status: dict) -> dict:
    op = STAGE2["outperf"]
    pillars = []

    def pillar(code, label, ok, text):
        pillars.append({"code": code, "label": label, "ok": ok, "text": text})
    fin = lambda k: r.get(k) is not None and np.isfinite(r.get(k))  # noqa: E731
    if all(fin(k) for k in ("rs_world_3m", "rs_world_6m", "rs_world_12m")):
        ok = r["rs_world_3m"] > 0 and r["rs_world_6m"] > 0 and r["rs_world_12m"] > 0
        pillar("P1", "Stärker als der MSCI World über 3, 6 und 12 Monate", bool(ok),
               f"3 M {de_pct(r['rs_world_3m'])}, 6 M {de_pct(r['rs_world_6m'])}, 12 M {de_pct(r['rs_world_12m'])} gegenüber dem MSCI World (in Euro).")
    else:
        pillar("P1", "Stärker als der MSCI World über 3, 6 und 12 Monate", None, "Nicht berechenbar.")
    if fin("beat_n"):
        ok = r["beat_n"] >= op["beat_months_min"]
        pillar("P2", "Übertrifft den Markt beständig", bool(ok), f"In {int(r['beat_n'])} der letzten 12 Monate besser als der MSCI World "
               f"(mindestens {op['beat_months_min']} nötig).")
    else:
        pillar("P2", "Übertrifft den Markt beständig", None, "Nicht berechenbar.")
    b_ok = fin("breadth30") and status.get("breadth30", {}).get("active")
    r_ok = fin("rev90") and status.get("rev90", {}).get("active")
    if b_ok or r_ok:
        ok = (not r_ok or r["rev90"] > 0) and (not b_ok or r["breadth30"] >= 0) and (r_ok and r["rev90"] > 0 or b_ok and r["breadth30"] > 0)
        pillar("P3", "Gewinnerwartungen steigen", bool(ok),
               f"Schätzung ggü. vor 90 Tagen {de_pct(r.get('rev90')) if r_ok else 'n. v.'}, Revisionsbreite {de_num(r.get('breadth30'), 2) if b_ok else 'n. v.'}.")
    else:
        pillar("P3", "Gewinnerwartungen steigen", None, "Keine Analystendaten.")
    if fin("rev_growth") and fin("eps_growth"):
        ok = r["rev_growth"] > 0 and r["eps_growth"] > 0
        pillar("P4", "Umsatz und Gewinn wachsen", bool(ok), f"Umsatz {de_pct(r['rev_growth'])}, Gewinn je Aktie {de_pct(r['eps_growth'])} (Quartal ggü. Vorjahr).")
    else:
        pillar("P4", "Umsatz und Gewinn wachsen", None, "Wachstumszahlen fehlen.")
    msh = market.get("sharpe12")
    if fin("sharpe12") and msh is not None and np.isfinite(msh):
        ok = r["sharpe12"] > msh
        pillar("P5", "Risikobereinigt besser als der Markt", bool(ok), f"Rendite je Schwankungseinheit (12 M): {de_num(r['sharpe12'], 2)} gegenüber {de_num(msh, 2)} beim MSCI World.")
    else:
        pillar("P5", "Risikobereinigt besser als der Markt", None, "Nicht berechenbar.")
    vflags = [f for f in risk["flags"] if f["group"] == "Bewertung" and f["counts"]]
    ev_ok = status.get("ey_fwd", {}).get("active")
    if ev_ok or risk["level"] in ("HIGH", "CRITICAL"):
        ok = not vflags and risk["level"] in ("NORMAL", "ELEVATED")
        pillar("P6", "Bewertung und Überhitzung tragbar", bool(ok), "Keine Bewertungswarnung, Risiko-Stufe höchstens ELEVATED." if ok
               else f"Risiko-Stufe {risk['level']}{', Bewertungswarnung' if vflags else ''}.")
    else:
        pillar("P6", "Bewertung und Überhitzung tragbar", None, "Bewertungsdaten fehlen.")
    ev = [p for p in pillars if p["ok"] is not None]
    pos = sum(1 for p in ev if p["ok"])
    if len(ev) < op["min_evaluable"]:
        level = "INSUFFICIENT"
    else:
        share = pos / len(ev)
        level = "HIGH" if share >= 5 / 6 - 1e-9 else "MODERATE" if share >= 4 / 6 - 1e-9 else "MARKET_LIKE" if share >= 0.5 - 1e-9 else "LOW"
        if risk["level"] == "CRITICAL":
            level = "LOW"
        elif risk["level"] == "HIGH" and level == "HIGH":
            level = "MODERATE"
    return {"level": level, "label": OUTPERF_LABEL[level], "positives": pos, "evaluable": len(ev), "pillars": pillars}


# =============================================================================== Gesamtablauf (live)
def _metric_value_fmt(v, fmt):
    return _f(v, 6)


def run_stage2(*, loc: pd.DataFrame, eur: pd.DataFrame, mkt: pd.Series | None, market_name: str, asof: pd.Timestamp,
               today: pd.Timestamp, meta: pd.DataFrame, eligible: pd.Series, stage1: pd.DataFrame, cands: list,
               pool: list, top_pick, verified: pd.Series, store, fx_row: pd.Series, snap90=None, snap90_date=None,
               demo: bool = False, sources: dict | None = None, fund_stats: dict | None = None,
               currency: pd.Series | None = None) -> dict:
    """Berechnet Stage 2 für alle Aktien (Scores) und die vollständige Analyse für die Stage-1-Kandidaten.

    stage1: DataFrame mit rank, Z, pct, m6, m12, vol, data_ok je Symbol (Ergebnis von Stage 1, unverändert).
    """
    p = STAGE2
    syms = list(loc.columns)
    elig = eligible.reindex(syms).fillna(False).astype(bool)
    sector = meta["sector"].reindex(syms) if "sector" in meta else pd.Series("", index=syms)
    sector = sector.where(~sector.isin(["", "Unbekannt", "Beobachtungsliste"]) & sector.notna(), None)
    country = meta["country"].reindex(syms) if "country" in meta else pd.Series("", index=syms)
    names = meta["name"].reindex(syms) if "name" in meta else pd.Series(syms, index=syms)
    pm, market = price_metrics_at(loc, eur, mkt, asof)
    pm["trend_status"] = [trend_status(pm.loc[s]) for s in syms]
    home = home_groups(syms, country, elig, p["home_min_n"])
    pm["home_group"] = home
    pm["rs_sector"] = group_relative(pm["r6_1_eur_log"], sector.fillna("__none__"), elig & sector.notna(), p["sector_min_n"])
    pm.loc[sector.isna(), "rs_sector"] = np.nan
    pm["rs_home"] = group_relative(pm["r6_1_eur_log"], home, elig, p["home_min_n"])
    fm = fundamental_metrics(store, syms, today, fx_row, snap90)
    X = pm.join(fm, how="left", rsuffix="_f")
    # Momentum-Vergleichsgruppe
    peers = [s for s in pool if s in X.index]
    peer_note = "Stage-1-Kandidatengruppe (bestes Zehntel, positives 6M/12M-Momentum)"
    if len(peers) < p["peer_min_n"]:
        pct1 = stage1["pct"].reindex(syms)
        peers = [s for s in syms if elig.get(s) and np.isfinite(pct1.get(s, np.nan)) and pct1[s] <= p["peer_fallback_pct"]]
        peer_note = f"beste {int(p['peer_fallback_pct'] * 100)} % des Stage-1-Rankings (Kandidatengruppe zu klein)"
    sc = score_categories(X, sector, elig, peers)
    fin_scores = final_scores(sc["scores"])
    thr = peer_thresholds(X, peers)
    status = sc["status"]
    cand_set = set(cands)
    s1 = stage1.reindex(syms)
    # Datenqualität für alle (kompakt) und Details für Kandidaten
    dq_all, risk_all = {}, {}
    weights = p["weights"]
    for s in syms:
        data_ok = bool(s1.at[s, "data_ok"]) if "data_ok" in s1 and pd.notna(s1.at[s, "data_ok"]) else False
        score = fin_scores.at[s, "score"]
        cats_av = {c: np.isfinite(sc["scores"].at[s, c]) for c in weights}
        cov_tot = 0.0
        for c, w in weights.items():
            ap = sc["detail"][c]["applicable"].at[s]
            av = sc["detail"][c]["available"].at[s]
            cov_tot += w * (av / ap if ap else 0.0) if cats_av[c] else 0.0
        fage = X.at[s, "fund_age"] if "fund_age" in X else np.inf
        if not data_ok or score is None or not np.isfinite(score):
            dq = "INSUFFICIENT"
        elif all(cats_av.values()) and cov_tot >= p["dq_high_min_coverage"] and fage <= p["fund_fresh_days"]:
            dq = "HIGH"
        elif all(cats_av.values()) and fage <= p["fund_max_age_days"]:
            dq = "MEDIUM"
        else:
            dq = "LOW"
        dq_all[s] = (dq, cov_tot)
        risk_all[s] = risk_assessment(X.loc[s], thr, sc["pct"].loc[s], today, status, currency.get(s) if currency is not None else None)
    # Kandidaten im Detail
    details = []
    for s in cands:
        if s not in X.index:
            continue
        r = X.loc[s]
        dq, cov_tot = dq_all[s]
        risk = risk_all[s]
        score = fin_scores.at[s, "score"]
        score = float(score) if score is not None and np.isfinite(score) else None
        dec = decide(score, dq, risk, verified.get(s) if verified is not None else None, s in cand_set)
        outp = outperformance(r, market, risk, status) if dq != "INSUFFICIENT" else {
            "level": "INSUFFICIENT", "label": OUTPERF_LABEL["INSUFFICIENT"], "positives": 0, "evaluable": 0, "pillars": []}
        cats = {}
        missing = []
        for c, spec in STAGE2_CATEGORIES.items():
            mets = []
            for key, label, d, ref, block, rule, fmt in spec["metrics"]:
                appl = sc["applies"][key].at[s]
                st = status[key]
                v = r.get(key)
                pv = sc["pct"].at[s, key]
                miss = bool(appl and st["active"] and not np.isfinite(pv))
                if miss:
                    missing.append(label)
                ref_lab = REF_LABEL[ref]
                if ref == "sector":
                    n_sec = int(((sector == sector.get(s)) & elig & X[key].notna()).sum()) if sector.get(s) else 0
                    ref_lab = f"Sektor {sector.get(s)}" if n_sec >= p["sector_min_n"] else "alle zulässigen Aktien (Sektor zu klein)"
                mets.append({"key": key, "label": label, "value": _f(v, 6) if not isinstance(v, (bool, np.bool_)) else bool(v),
                             "pct": _f(pv, 4), "score": _f(10 * pv, 3) if np.isfinite(pv) else None, "dir": d,
                             "ref": ref, "ref_label": ref_lab, "block": block, "fmt": fmt, "rule": rule, "applicable": bool(appl),
                             "active": st["active"], "missing": miss})
            cs = sc["scores"].at[s, c]
            cats[c] = {"name": spec["name"], "short": spec["short"], "weight": weights[c],
                       "score": _f(cs, 4) if np.isfinite(cs) else None, "available": bool(np.isfinite(cs)),
                       "n_available": int(sc["detail"][c]["available"].at[s]), "n_applicable": int(sc["detail"][c]["applicable"].at[s]),
                       "metrics": mets}
        details.append({"symbol": s, "r": r, "dq": dq, "cov": cov_tot, "risk": risk, "decision": dec, "out": outp,
                        "cats": cats, "missing": missing, "score": score})
    # Rangfolge (Stage-2-Score absteigend; ohne Score ans Ende; Gleichstand: Stage-1-Rang)
    def s1rank(s):
        v = s1.at[s, "rank"] if "rank" in s1 else np.nan
        return float(v) if pd.notna(v) else 1e9
    details.sort(key=lambda d: (d["score"] is None, -(d["score"] or 0), s1rank(d["symbol"])))
    for i, d in enumerate(details):
        d["rank2"] = i + 1 if d["score"] is not None else None
    ranking = []
    for i, d in enumerate(details):
        s, r = d["symbol"], d["r"]
        texts = build_texts(d, s1.loc[s], market, names.get(s, s), sector.get(s), r, currency.get(s) if currency is not None else None)
        nxt = details[i + 1] if i + 1 < len(details) else None
        prv = details[i - 1] if i > 0 else None
        texts["vs_next"] = compare_text(d, nxt, prv, names)
        fage = r.get("fund_age")
        ranking.append({
            "symbol": s, "name": names.get(s, s), "sector": sector.get(s) or "", "country": country.get(s) or "",
            "currency": (currency.get(s) if currency is not None else None), "home_group": _str(r.get("home_group")),
            "stage1": {"rank": _int(s1.at[s, "rank"]), "score": _f(s1.at[s, "Z"], 4), "pct": _f(s1.at[s, "pct"], 4),
                       "top_pick": s == top_pick},
            "stage2": {"rank": d["rank2"], "score": _f(d["score"], 4), "score_display": _f(round(d["score"], 1), 3) if d["score"] is not None else None,
                       "weight_available": _f(fin_scores.at[s, "weight_available"], 3),
                       "renormalized": bool(fin_scores.at[s, "weight_available"] < 0.999)},
            "categories": d["cats"],
            "data_quality": {"level": d["dq"], "label": DQ_LABEL[d["dq"]], "coverage": _f(d["cov"], 3), "missing": d["missing"],
                             "fund_asof": _str(r.get("fund_at")), "fund_age_days": _f(fage, 3) if fage is not None and np.isfinite(fage) else None,
                             "ts_asof": _str(r.get("ts_at")), "verified": (bool(verified.get(s)) if verified is not None and s in verified.index else None),
                             "notes": dq_notes(d, r, status)},
            "risk": d["risk"], "outperformance": d["out"], "decision": d["decision"],
            "trend": {k: _f(r.get(k), 6) for k in ("ma50", "ma200", "dist_ma50", "dist_ma200", "prox_52w", "days_since_high",
                                                    "rsi14", "vol63", "mdd_12m", "slope_ma50", "slope_ma200", "z_acc", "r2_6m",
                                                    "ext50", "ext200", "accel_z", "last_close_loc", "hh_hl")} | {"status": _str(r.get("trend_status"))},
            "momentum": {k: _f(r.get(k), 6) for k in ("ret_1m", "ret_3m", "ret_6m", "ret_12m", "m12_1", "m6_1", "m3_1", "m12_2",
                                                       "rs_world_3m", "rs_world_6m", "rs_world_12m", "rs_sector", "rs_home",
                                                       "resid_mom", "beat_n", "beta_36m", "sharpe12", "pos_months", "info_disc")},
            "earnings": {k: _f(r.get(k), 6) for k in ("rev_growth", "eps_growth", "surprise_last", "surprise4", "breadth30",
                                                       "up30", "down30", "analysts_0y", "eps_now_0y", "eps_30d_0y", "eps_60d_0y",
                                                       "eps_90d_0y", "rev30", "rev90", "margin_change", "rev_est90", "exp_growth")}
                        | {"next_earnings": _str(r.get("next_earnings")), "eps_period_end": _str(r.get("end_0y")), "guidance": None,
                           "surprise_hist": _hist(r.get("surprise_hist"))},
            "fundamentals": {k: _f(r.get(k), 6) for k in ("fcf_margin", "op_margin", "profit_margin", "gross_margin", "roe", "roa",
                                                           "roic_pre", "de", "interest_cov", "dilution", "fcf", "revenue",
                                                           "market_cap")} | {"currency": _str(r.get("fin_currency")), "fy_end": _str(r.get("fy_end"))},
            "valuation": {k: _f(r.get(k), 6) for k in ("pe_ttm", "pe_fwd", "ev_ebitda", "ps", "pb", "peg", "ey_fwd")}
                         | {"pe_fwd_pct_sector": _f(sc["pct"].at[s, "ey_fwd"], 4)},
            "texts": texts,
        })
    # Kompakte Tabelle für alle Aktien (Depot-Positionen außerhalb der Top 10)
    all_rows = []
    for s in syms:
        scv = fin_scores.at[s, "score"]
        if scv is None or not np.isfinite(scv):
            continue
        all_rows.append([s, _f(scv, 4)] + [_f(sc["scores"].at[s, c], 3) for c in weights] +
                        [risk_all[s]["level"], dq_all[s][0], _int(s1.at[s, "rank"]) if "rank" in s1 else None])
    active = {k: v for k, v in status.items()}
    eligible_list = [d["symbol"] for d in ranking if d["decision"] and d["decision"]["sparplan"]]
    n_fund = int(sum(1 for s in syms if elig.get(s) and np.isfinite(X.at[s, "fund_age"]) and X.at[s, "fund_age"] <= p["fund_max_age_days"]))
    n_elig = int(elig.sum())
    fund_cov = n_fund / n_elig if n_elig else 0.0
    inactive = [m["label"] for c, m in metric_defs() if not status[m["key"]]["active"]]
    messages = []
    state = "ok"
    if fund_cov < p["ref_min_coverage"]:
        state = "aufbau"
        messages.append({"level": "warnung", "text": f"Vergleichsdaten im Aufbau: Kennzahlen für {fund_cov:.0%} der zulässigen Aktien "
                         f"(nötig {p['ref_min_coverage']:.0%}). Bis dahin fehlen fundamentale Kategorien und Stage 2 gibt keine Sparplanfreigabe."})
    if inactive:
        messages.append({"level": "info", "text": "Derzeit nicht nutzbare Kennzahlen (zu wenige Vergleichswerte): " + ", ".join(inactive) + "."})
    if mkt is None or not market.get("asof"):
        state = "warnung"
        messages.append({"level": "warnung", "text": "MSCI-World-Kursreihe fehlt – relative Stärke nicht berechenbar."})
    return {
        "schema": 1, "stage2_version": STAGE2_VERSION, "params_hash": stage2_params_hash(), "demo": demo,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "asof": asof.strftime("%Y-%m-%d"),
        "status": state, "messages": messages,
        "weights": weights, "thresholds": [{"min": t, "code": c, "label": DECISION_LABEL[c], "text": DECISION_TEXT[c]} for t, c in p["thresholds"]],
        "categories": {c: {"name": v["name"], "short": v["short"], "weight": weights[c],
                           "metrics": [{"key": m[0], "label": m[1], "dir": m[2], "ref": m[3], "block": m[4], "rule": m[5],
                                        "active": status[m[0]]["active"], "coverage": status[m[0]]["coverage"]} for m in v["metrics"]]}
                       for c, v in STAGE2_CATEGORIES.items()},
        "reference": {"universe": n_elig, "peers": len(peers), "peer_definition": peer_note,
                      "fundamentals_coverage": _f(fund_cov, 3), "fundamentals_n": n_fund,
                      "min_coverage": p["ref_min_coverage"], "inactive_metrics": inactive,
                      "peer_thresholds": {k: _f(v, 4) for k, v in thr.items()},
                      "revenue_revision_base": snap90_date},
        "market": {"symbol": "EUNL.DE", "name": market_name, **{k: _f(v, 6) if not isinstance(v, str) else v for k, v in market.items()}},
        "ranking": ranking,
        "eligible": eligible_list,
        "all": {"fields": ["symbol", "score"] + list(weights) + ["risk", "dq", "stage1_rank"], "rows": all_rows},
        "fundamentals_fetch": fund_stats or {},
        "sources": sources or {},
        "metric_status": active,
    }


def _str(v):
    return v if isinstance(v, str) and v else None


def _int(v):
    try:
        return int(v) if v is not None and np.isfinite(float(v)) else None
    except (TypeError, ValueError):
        return None


def _hist(h):
    if not isinstance(h, list):
        return []
    return [{"quarter": x.get("quarter"), "eps_actual": _f(x.get("eps_actual")), "eps_est": _f(x.get("eps_est")),
             "surprise": _f(x.get("surprise"))} for x in h]


def dq_notes(d: dict, r: pd.Series, status: dict) -> list:
    notes = []
    fage = _num(r.get("fund_age"))
    if not np.isfinite(fage):
        err = r.get("fund_err")
        notes.append("Keine Kennzahlen von Yahoo" + (f" ({err})." if isinstance(err, str) and err else "."))
    elif fage > STAGE2["fund_max_age_days"]:
        notes.append(f"Kennzahlen zu alt ({int(fage)} Tage) – nicht verwendet.")
    elif fage > STAGE2["fund_fresh_days"]:
        notes.append(f"Kennzahlen sind {int(fage)} Tage alt.")
    if bool(r.get("ey_inconsistent")):
        notes.append("Gewinnrendite widersprüchlich (Kurs- und Gewinnwährung passen nicht) – nicht verwendet.")
    if d["missing"]:
        notes.append(f"{len(d['missing'])} Kennzahl(en) fehlen. Sie werden nicht geschätzt, sondern ausgelassen.")
    unavailable = [STAGE2_CATEGORIES[c]["name"] for c, v in d["cats"].items() if not v["available"]]
    if unavailable:
        notes.append("Nicht berechenbar: " + ", ".join(unavailable) + ". Der Score nutzt die übrigen Kategorien (Gewichte neu normiert).")
    notes.append("Unternehmensprognosen (Guidance) gibt es nicht kostenlos in strukturierter Form. Sie fließen nicht ein.")
    return notes


def build_texts(d: dict, s1: pd.Series, market: dict, name: str, sector, r: pd.Series, cur: str | None = None) -> dict:
    cats = d["cats"]
    why = []
    if pd.notna(s1.get("rank")):
        why.append(f"Stage 1: Rang {int(s1['rank'])} beim risikoadjustierten Momentum (Score {de_num(s1.get('Z'), 2)}).")
    ranked = sorted([(c, v) for c, v in cats.items() if v["available"]], key=lambda kv: -kv[1]["score"])
    if ranked:
        why.append("Stärkste Kategorien: " + ", ".join(f"{v['name']} {de_num(v['score'], 1)} von 10" for c, v in ranked[:3]) + ".")
    if r.get("rev90") is not None and np.isfinite(r.get("rev90")) and r["rev90"] > 0:
        why.append(f"Analysten haben ihre Gewinnschätzung in 90 Tagen um {de_pct(r['rev90'])} angehoben.")
    if _num(r.get("breadth30")) > 0:
        why.append(f"Mehr Analysten erhöhen als senken ihre Gewinnschätzung (Revisionsbreite {de_num(r['breadth30'], 2)}).")
    if r.get("trend_status"):
        why.append(f"Trend: {r['trend_status']}.")
    risks = [f["text"] for f in d["risk"]["flags"]]
    weak = [(c, v) for c, v in cats.items() if v["available"] and v["score"] is not None and v["score"] < 4]
    for c, v in sorted(weak, key=lambda kv: kv[1]["score"])[:2]:
        risks.append(f"Schwache Kategorie: {v['name']} nur {de_num(v['score'], 1)} von 10.")
    if not risks:
        risks.append("Keine regelbasierten Warnsignale. Allgemeine Risiken bleiben: Momentum-Crashs bei Marktwenden, "
                     "Einzelaktienrisiko, Datenfehler.")
    outp = [p["text"] for p in d["out"]["pillars"] if p["ok"]]
    if not outp:
        outp = ["Derzeit stützt keine der geprüften Säulen eine Outperformance."]
    fals = []
    if np.isfinite(r.get("ma200", np.nan)):
        fals.append(f"Der Kurs schließt unter der 200-Tage-Linie (heute {de_num(r['ma200'], 2)}{' ' + cur if cur else ''}, Abstand {de_pct(r.get('dist_ma200'))}).")
    if pd.notna(s1.get("pct")):
        fals.append(f"Der Stage-1-Rang fällt aus den besten 20 % (Halteband; heute Top {de_num(max(float(s1['pct']) * 100, 0.1), 1)} %).")
    if np.isfinite(r.get("rs_world_3m", np.nan)):
        fals.append(f"Die relative Stärke gegenüber dem MSCI World über 3 Monate wird negativ (heute {de_pct(r['rs_world_3m'])}).")
    if np.isfinite(r.get("breadth30", np.nan)):
        fals.append(f"Mehr Analysten senken als erhöhen ihre Gewinnschätzung (heute Revisionsbreite {de_num(r['breadth30'], 2)}).")
    if isinstance(r.get("next_earnings"), str) and r.get("next_earnings"):
        fals.append(f"Die Quartalszahlen am {de_date(r['next_earnings'])} verfehlen die Erwartungen.")
    fals.append("Die Risiko-Stufe steigt auf HIGH oder CRITICAL.")
    return {"why_selected": why, "risks": risks, "why_outperform": outp, "falsification": fals}


def compare_text(d, nxt, prv, names) -> str:
    """Warum diese Aktie vor (bzw. hinter) dem Nachbarn liegt: Kategorien mit dem größten gewichteten Unterschied."""
    other, ahead = (nxt, True) if nxt is not None else (prv, False)
    if other is None:
        return "Einziger Kandidat."
    if d["score"] is None:
        return "Ohne Score (Datenlage unzureichend), deshalb am Ende der Rangfolge."
    if other["score"] is None:
        return f"Vor {names.get(other['symbol'], other['symbol'])}, weil dort die Datenlage für einen Score nicht reicht."
    diffs = []
    for c, v in d["cats"].items():
        o = other["cats"][c]
        if v["available"] and o["available"]:
            diffs.append((c, STAGE2["weights"][c] * (v["score"] - o["score"]), v["score"], o["score"], v["name"]))
    if not diffs:
        return "Kein direkter Vergleich möglich."
    diffs.sort(key=lambda x: -x[1] if ahead else x[1])
    top = [x for x in diffs if (x[1] > 0 if ahead else x[1] < 0)][:2]
    on = names.get(other["symbol"], other["symbol"])
    if not top:
        return f"{'Vor' if ahead else 'Hinter'} {on} mit nahezu gleichem Profil."
    parts = [f"{x[4]} ({de_num(x[2], 1)} gegenüber {de_num(x[3], 1)})" for x in top]
    return f"{'Vor' if ahead else 'Hinter'} {on} vor allem wegen {' und '.join(parts)}."
