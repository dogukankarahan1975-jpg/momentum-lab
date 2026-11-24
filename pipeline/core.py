"""Momentum-Engine: Datenqualität, Kennzahlen, Scores, Auswahl und Halteregeln.

Dieselben Funktionen werden für das Live-Screening UND den Backtest verwendet,
damit beide exakt dieselbe Methodik nutzen (Reproduzierbarkeit).

Konventionen:
- Alle Kurs-Tabellen sind "breit": Index = Handelstage (DatetimeIndex), Spalten = Yahoo-Symbole.
- adj   = um Splits und Dividenden bereinigter Schlusskurs (Total-Return-Näherung), Landeswährung.
- close = splitbereinigter Schlusskurs, Landeswährung (für Liquidität und Kursanzeige).
- Wechselkurse: Einheiten Fremdwährung je 1 EUR (EZB-Konvention). EUR-Wert = Lokalwert / Kurs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import METHODOLOGY

DATA_PROBLEM_CODES = {"no_data", "stale", "gaps", "jump", "adj_ratio", "crosscheck", "currency"}

REASON_TEXT = {
    "no_data": "Keine Kursdaten abrufbar (Ticker-Zuordnung prüfen)",
    "stale": "Kursdaten veraltet oder Handel ausgesetzt",
    "short_history": "Zu kurze Kurshistorie (< 2 Jahre)",
    "gaps": "Lückenhafte Kursdaten im letzten Jahr",
    "jump": "Unplausibler Kurssprung (nicht verifiziert)",
    "adj_ratio": "Unplausible Split-/Dividendenanpassung",
    "liquidity": "Zu geringe Liquidität (Median-Tagesumsatz < 1 Mio. €)",
    "zero_volume": "Häufig kein Handelsumsatz",
    "penny": "Kurs unter 1 € (Penny-Stock-Regel)",
    "crosscheck": "Kurs weicht von Zweitquelle (iShares) ab",
    "currency": "Währung nicht umrechenbar",
    "no_vol": "Volatilität nicht berechenbar (zu wenige Wochenrenditen)",
    "duplicate": "Weitere Aktiengattung desselben Unternehmens (liquidere Gattung behalten)",
}


@dataclass
class Panel:
    adj: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    weekly: pd.DataFrame
    logret: pd.DataFrame       # Log-Renditen zwischen gültigen Beobachtungen
    adjratio_jump: pd.DataFrame  # relative Änderung von adj/close zwischen gültigen Beobachtungen
    first_date: pd.Series


def _per_column_valid_change(df: pd.DataFrame, fn) -> pd.DataFrame:
    out = {}
    for col in df.columns:
        s = df[col].dropna()
        if len(s) < 2:
            out[col] = pd.Series(dtype=float)
            continue
        out[col] = fn(s)
    res = pd.DataFrame(out).reindex(df.index)
    return res.reindex(columns=df.columns)


def prepare_panel(adj: pd.DataFrame, close: pd.DataFrame, volume: pd.DataFrame) -> Panel:
    adj = adj.sort_index()
    close = close.reindex(index=adj.index, columns=adj.columns)
    volume = volume.reindex(index=adj.index, columns=adj.columns)
    weekly = adj.resample("W-FRI").last()
    with np.errstate(divide="ignore", invalid="ignore"):
        logret = _per_column_valid_change(adj, lambda s: np.log(s / s.shift(1)))
        ratio = adj / close
        adjratio_jump = _per_column_valid_change(ratio, lambda s: (s / s.shift(1) - 1.0).abs())
    first_date = adj.apply(lambda s: s.first_valid_index())
    return Panel(adj, close, volume, weekly, logret, adjratio_jump, first_date)


def price_at(df: pd.DataFrame, target: pd.Timestamp, window_days: int) -> pd.Series:
    """Letzter gültiger Wert je Spalte im Fenster (target - window, target]."""
    start = target - pd.Timedelta(days=window_days)
    sub = df.loc[(df.index > start) & (df.index <= target)]
    if sub.empty:
        return pd.Series(np.nan, index=df.columns)
    return sub.ffill().iloc[-1]


def last_valid_date(df: pd.DataFrame, asof: pd.Timestamp, lookback_days: int = 40) -> pd.Series:
    sub = df.loc[(df.index > asof - pd.Timedelta(days=lookback_days)) & (df.index <= asof)]
    if sub.empty:
        return pd.Series(pd.NaT, index=df.columns)
    mask = sub.notna()
    any_valid = mask.any()
    idx = mask.iloc[::-1].idxmax()
    return idx.where(any_valid, pd.NaT)


def fx_rate_for(currencies: pd.Series, fx_row: pd.Series) -> pd.Series:
    """Einheiten Lokalwährung je EUR für jedes Symbol (EUR = 1)."""
    rates = currencies.map(lambda c: 1.0 if c == "EUR" else fx_row.get(c, np.nan))
    return rates.astype(float)


# ---------------------------------------------------------------- Datenqualität
def quality_at(panel: Panel, asof: pd.Timestamp, currencies: pd.Series, fx_row: pd.Series,
               params: dict = METHODOLOGY, crosscheck_dev: pd.Series | None = None,
               duplicates: set | None = None) -> pd.DataFrame:
    p = params
    cols = panel.adj.columns
    q = pd.DataFrame(index=cols)
    last_date = last_valid_date(panel.adj, asof)
    q["last_date"] = last_date
    first = pd.to_datetime(panel.first_date)
    q["has_data"] = (first <= asof).fillna(False)
    stale = (asof - last_date).dt.days > p["stale_days"]
    q["stale"] = stale.fillna(True)
    hist_years = (asof - first).dt.days / 365.25
    q["history_years"] = hist_years
    year = (panel.adj.index > asof - pd.Timedelta(days=365)) & (panel.adj.index <= asof)
    q["rows_1y"] = panel.adj.loc[year].notna().sum()
    jl = (panel.logret.index > asof - pd.Timedelta(days=p["jump_lookback_days"])) & (panel.logret.index <= asof)
    q["max_abs_logret"] = panel.logret.loc[jl].abs().max()
    q["max_adjratio_jump"] = panel.adjratio_jump.loc[jl].max()
    win = (panel.close.index > asof - pd.Timedelta(days=int(p["liq_window_days"] * 1.5))) & (panel.close.index <= asof)
    rates = fx_rate_for(currencies.reindex(cols), fx_row)
    traded = (panel.close.loc[win] * panel.volume.loc[win])
    q["liq_eur"] = traded.median() / rates
    vol_win = panel.volume.loc[win]
    q["zero_volume_share"] = (vol_win == 0).sum() / vol_win.notna().sum().replace(0, np.nan)
    last_close = price_at(panel.close, asof, 40)
    q["price_eur"] = last_close / rates
    q["fx_ok"] = rates.notna()
    q["crosscheck_dev"] = crosscheck_dev.reindex(cols) if crosscheck_dev is not None else np.nan

    reasons = {c: [] for c in cols}
    ln_jump = math.log(p["max_daily_jump"])

    def flag(mask: pd.Series, code: str):
        for c in mask[mask.fillna(False).astype(bool)].index:
            reasons[c].append(code)

    flag(~q["has_data"], "no_data")
    has = q["has_data"]
    flag(has & q["stale"], "stale")
    flag(has & ~q["fx_ok"], "currency")
    flag(has & (q["history_years"] < p["min_history_years"]), "short_history")
    flag(has & ~q["stale"] & (q["history_years"] >= 1) & (q["rows_1y"] < p["min_rows_last_year"]), "gaps")
    flag(has & (q["max_abs_logret"] > ln_jump), "jump")
    flag(has & (q["max_adjratio_jump"] > p["max_adj_ratio_jump"]), "adj_ratio")
    flag(has & q["fx_ok"] & (q["liq_eur"] < p["min_liquidity_eur"]), "liquidity")
    flag(has & (q["zero_volume_share"] > p["max_zero_volume_share"]), "zero_volume")
    flag(has & q["fx_ok"] & (q["price_eur"] < p["min_price_eur"]), "penny")
    if crosscheck_dev is not None:
        flag(has & (q["crosscheck_dev"].abs() > p["crosscheck_tolerance"]), "crosscheck")
    if duplicates:
        flag(pd.Series([c in duplicates for c in cols], index=cols), "duplicate")

    q["reasons"] = pd.Series({c: reasons[c] for c in cols})
    q["data_ok"] = q["reasons"].map(lambda r: not any(code in DATA_PROBLEM_CODES for code in r))
    q["eligible"] = q["reasons"].map(lambda r: len(r) == 0)
    return q


# ---------------------------------------------------------------- Kennzahlen
def features_at(panel: Panel, asof: pd.Timestamp, params: dict = METHODOLOGY, light: bool = False) -> pd.DataFrame:
    """Kennzahlen zum Stichtag. light=True berechnet nur, was der Backtest braucht."""
    p = params
    w = p["price_window_days"]
    skip = p["skip_months"]
    t1 = asof - pd.DateOffset(months=skip)
    t7 = asof - pd.DateOffset(months=skip + p["m6_months"])
    t13 = asof - pd.DateOffset(months=skip + p["m12_months"])
    p_now = price_at(panel.adj, asof, 40)
    p1 = price_at(panel.adj, t1, w)
    p7 = price_at(panel.adj, t7, w)
    p13 = price_at(panel.adj, t13, w)
    f = pd.DataFrame(index=panel.adj.columns)
    f["m6"] = p1 / p7 - 1.0
    f["m12"] = p1 / p13 - 1.0

    wk = panel.weekly.loc[:asof].iloc[-(p["vol_weeks"] + 1):]
    rets = wk / wk.shift(1) - 1.0
    rets = rets.iloc[1:]
    n = rets.notna().sum()
    vol = rets.std(ddof=1) * math.sqrt(52)
    f["vol"] = vol.where(n >= p["vol_min_weeks"])
    f["vol_weeks"] = n

    ma_days = p["trend_ma_days"]
    recent = panel.adj.loc[(panel.adj.index > asof - pd.Timedelta(days=int(ma_days * 2.2))) & (panel.adj.index <= asof)]
    cnt = recent.notna().sum()
    ma = recent.apply(lambda s: s.dropna().iloc[-ma_days:].mean() if s.notna().sum() >= ma_days else np.nan)
    ma = ma.where(cnt >= ma_days)
    f["ma200"] = ma
    f["above_ma200"] = (p_now > ma).where(ma.notna())
    f["dist_ma200"] = p_now / ma - 1.0
    f["last_adj"] = p_now
    if light:
        return f

    # Anzeige-/Risikokennzahlen
    f["ret_1m"] = p_now / price_at(panel.adj, t1, w) - 1.0
    f["ret_3m"] = p_now / price_at(panel.adj, asof - pd.DateOffset(months=3), w) - 1.0
    f["ret_6m"] = p_now / price_at(panel.adj, asof - pd.DateOffset(months=6), w) - 1.0
    f["ret_12m"] = p_now / price_at(panel.adj, asof - pd.DateOffset(months=12), w) - 1.0
    ytd_anchor = pd.Timestamp(year=asof.year, month=1, day=1) - pd.Timedelta(days=1)
    f["ret_ytd"] = p_now / price_at(panel.adj, ytd_anchor, 10) - 1.0

    yr = panel.adj.loc[(panel.adj.index > asof - pd.Timedelta(days=365)) & (panel.adj.index <= asof)]
    hi = yr.max()
    f["dd_52w"] = p_now / hi - 1.0
    roll_max = yr.cummax()
    f["maxdd_1y"] = (yr / roll_max - 1.0).min()
    f["last_close"] = price_at(panel.close, asof, 40)
    return f


# ---------------------------------------------------------------- Scores
def standardize(x: pd.Series, fit_mask: pd.Series, sigma: float) -> pd.Series:
    """z-Score mit robusten Momenten (aus ±sigma winsorisierten Werten der Fit-Menge).

    Die Werte selbst werden NICHT gekappt, damit die Spitze der Rangliste
    (wo die Top 10 liegen) keine künstlichen Gleichstände bekommt.
    """
    v = x[fit_mask.reindex(x.index).fillna(False).astype(bool)].dropna()
    v = v[np.isfinite(v)]
    if len(v) < 5:
        return pd.Series(np.nan, index=x.index)
    m, s = v.mean(), v.std(ddof=0)
    if not np.isfinite(s) or s == 0:
        return pd.Series(0.0, index=x.index).where(x.notna())
    clipped = v.clip(m - sigma * s, m + sigma * s)
    m2, s2 = clipped.mean(), clipped.std(ddof=0)
    if not np.isfinite(s2) or s2 == 0:
        s2 = s
    out = (x - m2) / s2
    return out.where(np.isfinite(out))


def scores_at(features: pd.DataFrame, eligible: pd.Series, signal: str = "ra",
              params: dict = METHODOLOGY) -> pd.DataFrame:
    """Berechnet z6, z12, Z, Rang und Perzentil.

    signal: "ra"  = risikoadjustiert 6+12 (Kernmethodik, MSCI-Stil)
            "m612" = rohes 6- und 12-Monats-Momentum kombiniert
            "m12"  = einfaches 12-1-Momentum
    Rang/Perzentil beziehen sich auf die zulässigen (eligible) Aktien; nicht zulässige
    Aktien mit gültigen Daten erhalten ein "Schatten-Perzentil" relativ zu dieser Verteilung.
    """
    p = params
    sigma = p["winsor_sigma"]
    elig = eligible.reindex(features.index).fillna(False).astype(bool)
    if signal == "ra":
        x6 = features["m6"] / features["vol"]
        x12 = features["m12"] / features["vol"]
    else:
        x6 = features["m6"].copy()
        x12 = features["m12"].copy()
    valid = x6.notna() & np.isfinite(x6)
    if signal == "ra":
        valid &= features["vol"].notna() & (features["vol"] > 0)
    fit = elig & valid
    z6 = standardize(x6.where(valid), fit, sigma)
    z12 = standardize(x12.where(valid), fit, sigma)
    if signal == "m12":
        comb = z12
    else:
        comb = p["weight_m6"] * z6 + p["weight_m12"] * z12
        comb = comb.where(z12.notna(), z6)  # MSCI: fehlt 12M, nur 6M
    Z = standardize(comb, fit & comb.notna(), sigma)
    s = pd.DataFrame(index=features.index)
    s["z6"], s["z12"], s["Z"] = z6, z12, Z
    s["score_valid"] = Z.notna()
    zfit = Z[fit & Z.notna()].sort_values(ascending=False)
    n = len(zfit)
    rank = pd.Series(np.nan, index=features.index)
    # deterministische Rangfolge: Score absteigend, bei Gleichstand Symbol aufsteigend
    order = sorted(zfit.index, key=lambda c: (-zfit[c], c))
    for i, c in enumerate(order, start=1):
        rank[c] = i
    s["rank"] = rank
    s["n_ranked"] = n
    arr = np.sort(zfit.values)[::-1]

    def shadow_pct(z):
        if not np.isfinite(z) or n < 2:
            return np.nan
        better = np.searchsorted(-arr, -z, side="left")  # Anzahl strikt besserer Werte
        return min(1.0, better / (n - 1))

    pct = Z.map(shadow_pct)
    pct[rank.notna()] = (rank[rank.notna()] - 1) / max(n - 1, 1)
    s["pct"] = pct
    return s


def select_candidates(features: pd.DataFrame, scores: pd.DataFrame, eligible: pd.Series,
                      top_n: int, params: dict = METHODOLOGY,
                      extra_ok: pd.Series | None = None) -> list[str]:
    p = params
    elig = eligible.reindex(scores.index).fillna(False).astype(bool)
    ok = elig & scores["Z"].notna() & (scores["pct"] <= p["candidate_max_pct"])
    if p["require_positive_m6"]:
        ok &= features["m6"] > 0
    if p["require_positive_m12"]:
        ok &= features["m12"] > 0
    if extra_ok is not None:
        ok &= extra_ok.reindex(scores.index).fillna(False).astype(bool)
    ranked = scores.loc[ok].sort_values("rank")
    return list(ranked.index[:top_n])


def pick_top(candidates: list[str], features: pd.DataFrame, scores: pd.DataFrame,
             eligible: pd.Series, params: dict = METHODOLOGY,
             verified: pd.Series | None = None) -> tuple[str | None, dict]:
    """Top Pick = bester Kandidat, der zusätzlich alle Robustheitsregeln erfüllt."""
    p = params
    elig = eligible.reindex(scores.index).fillna(False).astype(bool)
    vol_limit = features.loc[elig, "vol"].quantile(p["toppick_max_vol_pct"]) if elig.any() else np.nan
    checks_by_symbol = {}
    chosen = None
    for c in candidates:
        chk = {
            "z6": bool(scores.at[c, "z6"] >= p["toppick_min_z6"]),
            "z12": bool(scores.at[c, "z12"] >= p["toppick_min_z12"]),
            "vol": bool(np.isfinite(vol_limit) and features.at[c, "vol"] <= vol_limit),
            "verified": bool(verified.get(c, True)) if verified is not None else True,
        }
        checks_by_symbol[c] = chk
        if chosen is None and all(chk.values()):
            chosen = c
    return chosen, {"vol_limit": None if not np.isfinite(vol_limit) else float(vol_limit),
                    "checks": checks_by_symbol}


def hold_state(pct: pd.Series, m12: pd.Series, data_ok: pd.Series, score_valid: pd.Series,
               params: dict = METHODOLOGY, hold_max_pct: float | None = None) -> pd.DataFrame:
    """Verkaufsbedingung H und 'schwer' (sofort) je Aktie.

    H: Rang außerhalb des Haltebands ODER 12-1-Momentum <= 0 ODER kein gültiger Score.
    schwer: unterhalb des Medians (pct > 0,5) oder 12-1-Momentum <= -10 %.
    Datenprobleme werden separat behandelt (-> 'Verkauf prüfen', nie automatisch 'Verkauf').
    """
    hm = params["hold_max_pct"] if hold_max_pct is None else hold_max_pct
    out = pd.DataFrame(index=pct.index)
    valid = score_valid.reindex(pct.index).fillna(False).astype(bool)
    out["H"] = (~valid) | (pct > hm) | (m12 <= 0)
    out["severe"] = valid & ((pct > params["sell_immediate_pct"]) | (m12 <= -0.10))
    out["data_problem"] = ~data_ok.reindex(pct.index).fillna(False).astype(bool)
    return out


def last_trading_day_of_prev_month(index: pd.DatetimeIndex, asof: pd.Timestamp) -> pd.Timestamp | None:
    first_of_month = pd.Timestamp(year=asof.year, month=asof.month, day=1)
    prev = index[index < first_of_month]
    return prev[-1] if len(prev) else None


def month_end_dates(index: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    s = pd.Series(index, index=index)
    s = s[(s.index >= start) & (s.index <= end)]
    if s.empty:
        return []
    me = s.groupby([s.index.year, s.index.month]).max()
    return [pd.Timestamp(x) for x in me.values]
