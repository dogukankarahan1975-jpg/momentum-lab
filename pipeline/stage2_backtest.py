"""Teil-Validierung von Stage 2 im historischen Test – NUR die kursbasierten Bausteine.

Getestet wird mit denselben Funktionen wie live (stage2.price_metrics_at, stage2.score_categories):
  A  Momentum-Persistenz, C  relative Stärke / Outperformance, D  Trendqualität,
  Fp der Überhitzungsblock von F (Abstand zu den Durchschnittslinien, Kurssprung, Volatilität).
NICHT testbar (und bewusst nicht ersetzt): B (Gewinnrevisionen, Überraschungen, Wachstum), E (Qualität) und der
Bewertungsblock von F. Für diese Daten gibt es keine kostenlosen zeitpunktgenauen Historien; heutige Werte für die
Vergangenheit zu verwenden wäre Look-ahead. Ab Version 0.2.0 archiviert die Pipeline diese Daten wöchentlich selbst,
damit später ein echter Test möglich wird. Auch die Entscheidungsschwellen (8,5 usw.) gelten für den vollen Score und
sind hier nicht prüfbar.

Grundsätze: Signal am Monatsende, Handel am nächsten Handelstag, Kosten wie im Haupt-Backtest, keine Parameter-
optimierung (Varianten in config.STAGE2_BACKTEST vorab festgelegt). Survivorship Bias wie im Haupt-Backtest.
Zeitraum: ab dem Monat, für den 36 Monate MSCI-World-Daten in EUR (iShares Core MSCI World, EUNL) vorliegen.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import backtest as bt
from . import core
from . import stage2
from .config import COST_SCENARIOS, STAGE2, STAGE2_BACKTEST, STAGE2_CATEGORIES, STAGE2_MIN

PRICE_CATS = {
    "A": STAGE2_CATEGORIES["A"],
    "C": STAGE2_CATEGORIES["C"],
    "D": STAGE2_CATEGORIES["D"],
    "Fp": {"name": "Überhitzung (Kursteil von F)", "short": "Überhitzung",
           "metrics": [m for m in STAGE2_CATEGORIES["F"]["metrics"] if m[4] == "ueberhitzung"]},
}
PRICE_MINS = {"A": STAGE2_MIN["A"], "C": STAGE2_MIN["C"], "D": STAGE2_MIN["D"], "Fp": {"min": 2}}
PRICE_WEIGHTS = {"A": STAGE2["weights"]["A"], "C": STAGE2["weights"]["C"], "D": STAGE2["weights"]["D"],
                 "Fp": STAGE2["weights"]["F"]}
FACTOR_LABELS = {"s2p": "Stage-2-Kursscore (A, C, D, Überhitzung)", "A": "A Momentum-Persistenz",
                 "C": "C Relative Stärke", "D": "D Trendqualität", "Fp": "F Überhitzung (hoher Wert = wenig überhitzt)",
                 "Z": "Stage-1-Score (zum Vergleich)"}


def _spearman(a: pd.Series, b: pd.Series) -> float:
    df = pd.concat([a, b], axis=1).dropna()
    if len(df) < 10:
        return np.nan
    ra, rb = df.iloc[:, 0].rank(), df.iloc[:, 1].rank()
    if ra.std() == 0 or rb.std() == 0:
        return np.nan
    return float(np.corrcoef(ra, rb)[0, 1])


def newey_west_t(x: np.ndarray, lags: int) -> float:
    x = np.asarray([v for v in x if np.isfinite(v)], dtype=float)
    T = len(x)
    if T < 12:
        return np.nan
    m = x.mean()
    e = x - m
    var = (e @ e) / T
    for L in range(1, max(lags, 0) + 1):
        w = 1 - L / (lags + 1)
        var += 2 * w * (e[L:] @ e[:-L]) / T
    if var <= 0:
        return np.nan
    return float(m / math.sqrt(var / T))


def _rebalance_to(book: bt.Book, w: pd.Series, prices: pd.Series, cost: dict, year: int) -> None:
    """Wie backtest._rebalance_strict, aber mit vorgegebenen Zielgewichten (Toleranzband 25 %)."""
    w = w[[np.isfinite(prices.get(s, np.nan)) for s in w.index]]
    for s in book.holdings():
        if s not in w.index:
            book.sell(s, None, prices.get(s, np.nan), cost, year)
    if w.empty:
        return
    w = w / w.sum()
    total = book.value(prices)
    for s in w.index:
        cur = book.shares(s) * prices[s]
        tgt = total * w[s]
        if cur > tgt * 1.25:
            book.sell(s, (cur - tgt) / prices[s], prices[s], cost, year)
    needs = {}
    for s in w.index:
        cur = book.shares(s) * prices[s]
        tgt = total * w[s]
        if cur < tgt * 0.75:
            needs[s] = tgt - cur
    budget, need_total = book.cash, sum(needs.values())
    for s, amt in needs.items():
        book.buy(s, amt if need_total <= budget else budget * amt / need_total, prices[s], cost)


def compute_scores(ctx: bt.Context, meta: pd.DataFrame, mkt: pd.Series, dates: list, log=print) -> dict:
    loc, eur = ctx.panel.adj, ctx.price_eur
    sector = meta["sector"].reindex(loc.columns)
    sector = sector.where(~sector.isin(["", "Unbekannt"]) & sector.notna(), None)
    country = meta["country"].reindex(loc.columns)
    out = {}
    for k, d in enumerate(dates):
        sig = ctx.signals[d]
        elig, sc1, f = sig["elig"], sig["ra"], sig["f"]
        pool = core.select_candidates(f, sc1, elig, 10 ** 6)
        if not pool:
            out[d] = None
            continue
        cols = list(elig[elig].index)
        lw = loc.loc[(loc.index > d - pd.DateOffset(years=3, months=3)) & (loc.index <= d), cols]
        ew = eur.loc[lw.index, cols]
        pm, _ = stage2.price_metrics_at(lw, ew, mkt, d)
        e = elig.reindex(cols).fillna(False)
        home = stage2.home_groups(cols, country.reindex(cols), e, STAGE2["home_min_n"])
        sec = sector.reindex(cols)
        pm["rs_sector"] = stage2.group_relative(pm["r6_1_eur_log"], sec.fillna("__none__"), e & sec.notna(), STAGE2["sector_min_n"])
        pm.loc[sec.isna(), "rs_sector"] = np.nan
        pm["rs_home"] = stage2.group_relative(pm["r6_1_eur_log"], home, e, STAGE2["home_min_n"])
        peers = pool
        if len(peers) < STAGE2["peer_min_n"]:
            pct = sc1["pct"].reindex(cols)
            peers = [s for s in cols if np.isfinite(pct.get(s, np.nan)) and pct[s] <= STAGE2["peer_fallback_pct"]]
        res = stage2.score_categories(pm, sec, e, peers, cats=PRICE_CATS, mins=PRICE_MINS)
        fs = stage2.final_scores(res["scores"], PRICE_WEIGHTS)
        out[d] = {"pool": pool, "s2p": fs["score"], "cat": res["scores"], "Z": sc1["Z"]}
        if (k + 1) % 24 == 0:
            log(f"[stage2-backtest] Scores {k + 1}/{len(dates)} ({d.date()})")
    return out


def _targets(v: dict, info: dict | None) -> pd.Series:
    if not info:
        return pd.Series(dtype=float)
    top10 = info["pool"][:10]
    if v["rank_by"] == "stage1":
        chosen = top10[:v["pick"]]
    else:
        s2 = info["s2p"].reindex(top10)
        order = sorted(top10, key=lambda s: (-(s2.get(s) if np.isfinite(s2.get(s, np.nan)) else -1e9), top10.index(s)))
        chosen = order[:v["pick"]]
    if not chosen:
        return pd.Series(dtype=float)
    if v["weighting"] == "score":
        s2 = info["s2p"].reindex(chosen).fillna(0.0).clip(lower=0.0)
        if s2.sum() <= 0:
            return pd.Series(1.0 / len(chosen), index=chosen)
        return s2 / s2.sum()
    return pd.Series(1.0 / len(chosen), index=chosen)


def simulate(ctx: bt.Context, dates: list, scores: dict, v: dict, h: int, cost: dict, capital: float) -> dict:
    """h überlappende Tranchen (je 1/h des Kapitals), Tranche j wird alle h Monate umgeschichtet."""
    books = [bt.Book(cash=capital / h, tax_on=False) for _ in range(h)]
    parts = []
    for k, d in enumerate(dates):
        e = ctx.exec_day[d]
        nxt = ctx.exec_day[dates[k + 1]] if k + 1 < len(dates) else None
        prices = ctx.price_eur.loc[e]
        j = k % h
        _rebalance_to(books[j], _targets(v, scores.get(d)), prices, cost, e.year)
        seg = None
        for b in books:
            pth = bt._value_path(b, ctx.price_eur, e, nxt)
            seg = pth if seg is None else seg.add(pth, fill_value=0.0)
        parts.append(seg)
    values = pd.concat(parts) if parts else pd.Series(dtype=float)
    return {"values": values, "books": books}


def forward_returns(ctx: bt.Context, dates: list, all_dates: list, h: int, mkt: pd.Series) -> dict:
    """h-Monats-Rendite ab dem Handelstag nach dem Signal (EUR) für alle Aktien und den MSCI World."""
    pos = {d: i for i, d in enumerate(all_dates)}
    mk = mkt.reindex(ctx.price_eur.index).ffill(limit=10)
    out = {}
    for d in dates:
        i = pos[d]
        if i + h >= len(all_dates):
            continue
        e0, e1 = ctx.exec_day[d], ctx.exec_day[all_dates[i + h]]
        r = ctx.price_eur.loc[e1] / ctx.price_eur.loc[e0] - 1
        m = mk.get(e1) / mk.get(e0) - 1 if np.isfinite(mk.get(e0, np.nan)) and np.isfinite(mk.get(e1, np.nan)) else np.nan
        out[d] = (r, m)
    return out


def selection_stats(dates: list, scores: dict, v: dict, fwd: dict) -> dict:
    exc, raw = [], []
    for d in dates:
        if d not in fwd:
            continue
        r, m = fwd[d]
        if not np.isfinite(m):
            continue
        for s in _targets(v, scores.get(d)).index:
            x = r.get(s, np.nan)
            if np.isfinite(x):
                raw.append(x)
                exc.append(x - m)
    if not exc:
        return {"decisions": 0}
    exc, raw = np.array(exc), np.array(raw)
    win = exc > 0
    return {"decisions": int(len(exc)), "hit_rate": float(win.mean()),
            "avg_return_winners": float(raw[win].mean()) if win.any() else None,
            "avg_return_losers": float(raw[~win].mean()) if (~win).any() else None,
            "avg_excess_winners": float(exc[win].mean()) if win.any() else None,
            "avg_excess_losers": float(exc[~win].mean()) if (~win).any() else None,
            "avg_excess": float(exc.mean())}


def run_stage2_validation(ctx: bt.Context, meta: pd.DataFrame, bench_eur: dict, log=print) -> dict:
    t0 = pd.Timestamp.now()
    b = bench_eur.get("msci_world_eur")
    mkt = b["eur"].dropna() if b else None
    if mkt is None or len(mkt) < 800:
        return {"available": False, "reason": "MSCI-World-Kursreihe in EUR (EUNL) fehlt oder ist zu kurz."}
    if not ctx.signals:
        ctx.compute_signals()
    start_need = mkt.index[0] + pd.DateOffset(months=STAGE2["win"]["resid_months"] + 1)
    dates = [d for d in ctx.dates if d >= start_need]
    if len(dates) < 36:
        return {"available": False, "reason": "Weniger als 36 Monate mit vollständigen Stage-2-Kursdaten."}
    log(f"[stage2-backtest] {len(dates)} Monate ab {dates[0].date()}")
    scores = compute_scores(ctx, meta, mkt, dates, log)
    capital = 10_000.0
    cost = COST_SCENARIOS["realistisch"]
    fwd = {h: forward_returns(ctx, dates, ctx.dates, h, mkt) for h in sorted(set(STAGE2_BACKTEST["holding_months"]) | set(STAGE2_BACKTEST["ic_horizons"]))}
    first_e = ctx.exec_day[dates[0]]
    mk = mkt.reindex(ctx.price_eur.index).ffill(limit=10)
    mvals = mk[mk.index >= first_e].dropna()
    mvals = mvals / mvals.iloc[0] * capital
    m_metrics = bt.perf_metrics(mvals)
    strategies = []
    for h in STAGE2_BACKTEST["holding_months"]:
        for v in STAGE2_BACKTEST["variants"]:
            res = simulate(ctx, dates, scores, v, h, cost, capital)
            vals = res["values"]
            m = bt.perf_metrics(vals)
            years = m.get("years") or np.nan
            traded = sum(bk.traded_value for bk in res["books"])
            avg_val = float(vals.mean()) if len(vals) else np.nan
            m["trades"] = sum(bk.trades for bk in res["books"])
            m["fees"] = sum(bk.fees + bk.spread_cost for bk in res["books"])
            m["turnover"] = (traded / 2) / avg_val / years if avg_val and years and np.isfinite(years) else None
            if m.get("cagr") is not None and m_metrics.get("cagr") is not None:
                m["excess_cagr"] = (1 + m["cagr"]) / (1 + m_metrics["cagr"]) - 1
                m["excess_total"] = (1 + m["total_return"]) / (1 + m_metrics["total_return"]) - 1
            mon = vals.groupby([vals.index.year, vals.index.month]).tail(1).pct_change().dropna()
            mm = mvals.groupby([mvals.index.year, mvals.index.month]).tail(1).pct_change().dropna()
            both = pd.concat([mon, mm.reindex(mon.index)], axis=1).dropna()
            if len(both):
                m["months_better"] = float((both.iloc[:, 0] > both.iloc[:, 1]).mean())
            sel = selection_stats(dates, scores, v, fwd[h])
            strategies.append({"id": v["id"], "name": v["name"], "holding_months": h, "metrics": bt._clean(m),
                               "selection": bt._clean(sel), "curve": bt.monthly_points(vals / vals.iloc[0] * 100) if len(vals) else []})
        log(f"[stage2-backtest] Haltedauer {h} M fertig")
    # Kostensensitivität (Haltedauer 1 Monat)
    sens = []
    for vid in ("s1_top10", "s12_top5"):
        v = next(x for x in STAGE2_BACKTEST["variants"] if x["id"] == vid)
        row = {"id": vid, "name": v["name"]}
        for ck, cv in COST_SCENARIOS.items():
            res = simulate(ctx, dates, scores, v, 1, cv, capital)
            mm_ = bt.perf_metrics(res["values"])
            row[ck] = {"cagr": bt._f(mm_.get("cagr")), "label": cv["label"]}
        sens.append(row)
    # Prognosegüte (Rang-Informationskoeffizient innerhalb der Stage-1-Kandidatengruppe)
    ic_rows = []
    for fac in ("s2p", "A", "C", "D", "Fp", "Z"):
        row = {"factor": fac, "label": FACTOR_LABELS[fac]}
        for h in STAGE2_BACKTEST["ic_horizons"]:
            ics = []
            for d in dates:
                info = scores.get(d)
                if not info or d not in fwd[h]:
                    continue
                pool = info["pool"]
                if len(pool) < 10:
                    continue
                if fac == "s2p":
                    x = info["s2p"].reindex(pool)
                elif fac == "Z":
                    x = info["Z"].reindex(pool)
                else:
                    x = info["cat"][fac].reindex(pool)
                ics.append(_spearman(x, fwd[h][d][0].reindex(pool)))
            arr = np.array([v for v in ics if np.isfinite(v)])
            row[f"h{h}"] = {"mean": bt._f(arr.mean()) if len(arr) else None, "t": bt._f(newey_west_t(arr, h - 1)),
                            "positive_share": bt._f((arr > 0).mean()) if len(arr) else None, "months": int(len(arr))}
        ic_rows.append(row)
    s1 = next((s for s in strategies if s["id"] == "s1_top10" and s["holding_months"] == 1), None)
    s12 = next((s for s in strategies if s["id"] == "s12_top5" and s["holding_months"] == 1), None)
    s15 = next((s for s in strategies if s["id"] == "s1_top5" and s["holding_months"] == 1), None)
    conclusion = []
    dn, dp = stage2.de_num, stage2.de_pct
    ic1 = next(r for r in ic_rows if r["factor"] == "s2p").get("h1", {})
    if ic1.get("mean") is not None:
        t = ic1.get("t")
        sig = t is not None and abs(t) >= 2
        conclusion.append(f"Prognosegüte innerhalb der Momentum-Gruppe (1 Monat): mittlerer Rang-IC {dn(ic1['mean'], 3)}, "
                          f"t-Wert {dn(t, 1) if t is not None else '–'}. "
                          + ("Statistisch auffällig (|t| ≥ 2)." if sig else "Statistisch nicht von null unterscheidbar (|t| < 2)."))
    if s1 and s12 and s15:
        a, b_, c = s1["metrics"], s12["metrics"], s15["metrics"]
        if a.get("cagr") is not None and b_.get("cagr") is not None and c.get("cagr") is not None:
            conclusion.append(f"Monatlich umgeschichtet: Stage 1 Top 10 {dp(a['cagr'])} p. a. (Sharpe {dn(a.get('sharpe'), 2)}), "
                              f"Stage 1 Top 5 {dp(c['cagr'])} p. a. (Sharpe {dn(c.get('sharpe'), 2)}), Stage 1+2 beste 5 "
                              f"{dp(b_['cagr'])} p. a. (Sharpe {dn(b_.get('sharpe'), 2)}). MSCI World {dp(m_metrics.get('cagr'))} p. a.")
            better = (b_.get("sharpe") or -9) > (c.get("sharpe") or -9)
            conclusion.append("Fairer Vergleich (gleich viele Aktien): Stage 1+2 beste 5 gegen Stage 1 Top 5. "
                              + ("Die Stage-2-Auswahl war risikobereinigt besser." if better else "Die Stage-2-Auswahl war risikobereinigt NICHT besser."))
    conclusion.append("Nur die kursbasierten Bausteine sind getestet. Gewinnrevisionen, Qualität und Bewertung sind nicht "
                      "validiert, die Entscheidungsschwellen bleiben Heuristiken.")
    warnings = [
        "Teiltest: B (Gewinnrevisionen, Überraschungen, Wachstum), E (Qualität) und der Bewertungsblock von F fehlen, weil es "
        "dafür keine kostenlosen zeitpunktgenauen Historien gibt. Ein Ersatz mit heutigen Werten wäre Look-ahead und wurde bewusst nicht gebaut.",
        "Survivorship Bias: nur heutige MSCI-World-Mitglieder. Alle Varianten sind dadurch vermutlich zu gut; der Vergleich der "
        "Varianten untereinander ist weniger betroffen als der Vergleich mit dem MSCI World.",
        "Zeitraum beginnt erst, wenn 36 Monate MSCI-World-Daten in EUR vorliegen (ETF EUNL ab September 2009). Die Finanzkrise "
        "und der Momentum-Crash 2009 sind deshalb nicht enthalten.",
        "MSCI World = ETF (inkl. Fondskosten). Vor Steuern, nach Kosten. Überlappende Tranchen bei 3/6/12 Monaten Haltedauer "
        "(Jegadeesh & Titman 1993), damit der Startmonat keine Rolle spielt.",
        f"Mehrfachtests: {len(STAGE2_BACKTEST['variants'])} Varianten × {len(STAGE2_BACKTEST['holding_months'])} Haltedauern. "
        "Kleine Unterschiede sind Zufall (Harvey, Liu & Zhu 2016).",
    ]
    log(f"[stage2-backtest] fertig in {(pd.Timestamp.now() - t0).total_seconds():.0f}s")
    return {
        "available": True,
        "period": {"start": first_e.strftime("%Y-%m-%d"), "end": ctx.price_eur.index[-1].strftime("%Y-%m-%d"), "months": len(dates)},
        "tested": ["A Momentum-Persistenz", "C Relative Stärke", "D Trendqualität", "F Überhitzung (Kursteil)"],
        "not_tested": ["B Gewinn- und Revisionsmomentum", "E Unternehmensqualität", "F Bewertung", "Entscheidungsschwellen und Datenqualitätsregeln"],
        "weights_used": {k: round(v / sum(PRICE_WEIGHTS.values()), 4) for k, v in PRICE_WEIGHTS.items()},
        "benchmark": {"name": "iShares Core MSCI World (EUNL, EUR, inkl. Fondskosten)", "metrics": bt._clean(m_metrics),
                      "curve": bt.monthly_points(mvals / mvals.iloc[0] * 100)},
        "strategies": strategies,
        "cost_sensitivity": sens,
        "ic": {"horizons": STAGE2_BACKTEST["ic_horizons"], "rows": ic_rows,
               "explanation": "Rang-Korrelation zwischen Score und späterer Rendite innerhalb der Stage-1-Kandidatengruppe, je Monat. "
                              "0 = keine Aussagekraft. t-Wert nach Newey-West (überlappende Zeiträume berücksichtigt)."},
        "conclusion": conclusion,
        "warnings": warnings,
    }
