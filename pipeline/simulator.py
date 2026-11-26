"""Daten für den Backtest-Simulator der App (Rechnung erfolgt im Browser).

Für jedes Monatsende seit Beginn der Kurshistorie wird das Stage-1-Screening mit den Daten von DAMALS
nachgestellt (nur Kurse bis zu diesem Tag). Exportiert werden:
  - die Rangliste (Top 12 nach Stage-1-Score, mit Kandidatenstatus),
  - je Aktie der Status der App-Halteregel (für "Verkauf bei erstem Verkaufssignal"),
  - Stage 2 (nur Kursteil): Kandidaten mit Risiko NORMAL und allen kursbasierten Outperformance-Säulen erfüllt,
  - Ausführungskurse in EUR (Schluss des nächsten Handelstags) aller Aktien, die je in einer Liste standen,
  - MSCI World und S&P 500 (thesaurierend) in EUR an denselben Tagen.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import core, stage2
from .stage2v2 import continuation_scores, peer_group
from .config import STAGE2

TOP_K = 12
SCHEMA = 1


def _round(x: float) -> float | None:
    if x is None or not np.isfinite(x) or x <= 0:
        return None
    return float(f"{x:.6g}")


def _stage2_rank(ctx, d, sig, top10: list[str], mkt: pd.Series | None):
    """Stage 2 v2 (Kursteil): Top-10-Kandidaten nach Fortsetzungs-Score (Perzentile gegen die Momentum-Gruppe)."""
    if not top10:
        return [], {}
    f, sc, elig = sig["f"], sig["ra"], sig["elig"]
    pool = core.select_candidates(f, sc, elig, 10 ** 6)
    peers = peer_group(sc, f, elig, pool)
    cols = list(dict.fromkeys(list(peers) + list(top10)))
    loc = ctx.panel.adj
    lw = loc.loc[(loc.index > d - pd.DateOffset(years=3, months=3)) & (loc.index <= d), cols]
    ew = ctx.price_eur.loc[lw.index, cols]
    pm, _ = stage2.price_metrics_at(lw, ew, mkt, d)
    res = continuation_scores(pm, peers, list(top10), use_gewinn=False)
    if not len(res):
        return [], {}
    res = res[res["score"].notna()].sort_values("score", ascending=False)
    return res.index.tolist(), {s: float(res.at[s, "score"]) for s in res.index}


def chain_backfill(main: pd.Series, candidates: list, log=print) -> tuple[pd.Series, dict | None]:
    """Verlängert eine ETF-Reihe nach hinten mit einer älteren Reihe desselben Index.

    Bedingung (sonst keine Verlängerung): mindestens 24 gemeinsame Monate, Korrelation der Monatsrenditen >= 0,97,
    Unterschied der Durchschnittsrendite <= 1,5 Prozentpunkte p. a., kein Monat mit mehr als 3 Prozentpunkten
    Abweichung. Die ältere Reihe wird am ersten Tag der Hauptreihe auf deren Niveau skaliert (reine Verkettung der
    Renditen, keine geschätzten Werte)."""
    main = main.dropna()
    if main.empty:
        return main, None
    best = None
    for c in candidates:
        s = c["eur"].dropna()
        s = s[s > 0]
        if s.empty or s.index[0] > main.index[0] - pd.Timedelta(days=200):
            continue
        both = pd.concat([main, s], axis=1, keys=["m", "c"]).dropna()
        mon = both.groupby([both.index.year, both.index.month]).tail(1).pct_change().dropna()
        if len(mon) < 24:
            log(f"[simulator] Verlängerung {c['symbol']}: zu wenig gemeinsame Monate ({len(mon)})")
            continue
        corr = float(mon["m"].corr(mon["c"]))
        diff = float(abs(mon["m"].mean() - mon["c"].mean()) * 12)
        mx = float((mon["m"] - mon["c"]).abs().max())
        ok = corr >= 0.97 and diff <= 0.015 and mx <= 0.03
        log(f"[simulator] Verlängerung {c['symbol']}: {len(mon)} Monate, Korrelation {corr:.3f}, "
            f"Differenz {diff:.2%} p. a., max. Monatsabweichung {mx:.2%} -> {'ok' if ok else 'verworfen'}")
        if ok and (best is None or s.index[0] < best[1].index[0]):
            best = (c, s, {"symbol": c["symbol"], "name": c["name"], "from": s.index[0].strftime("%Y-%m-%d"),
                           "to": main.index[0].strftime("%Y-%m-%d"), "months_checked": int(len(mon)),
                           "corr": round(corr, 4), "diff_pa": round(diff, 4)})
    if best is None:
        return main, None
    c, s, info = best
    d0 = main.index[0]
    ref = s.loc[:d0]
    if ref.empty:
        return main, None
    early = s.loc[s.index < d0] * (main.iloc[0] / ref.iloc[-1])
    return pd.concat([early, main]).sort_index(), info


def measure_bias(ctx, dates: list, ref: pd.Series | None) -> dict | None:
    """Vorsprung der gleichgewichteten Backtest-Liste (alle zulässigen Aktien, monatlich neu gewichtet, ohne Kosten)
    vor einem echten Index-ETF im selben Zeitraum. Dient als gemessener Korrekturwert für den Simulator."""
    if ref is None or len(dates) < 25:
        return None
    ref = ref.dropna()
    ds = [d for d in dates if d >= ref.index[0]]
    if len(ds) < 25:
        return None
    rets = []
    for a, b in zip(ds[:-1], ds[1:]):
        el = ctx.signals[a]["elig"]
        syms = el[el].index
        pa, pb = ctx.price_eur.loc[a, syms], ctx.price_eur.loc[b, syms]
        r = (pb / pa - 1).replace([np.inf, -np.inf], np.nan).dropna()
        r = r[r.abs() < 3]
        if len(r):
            rets.append(float(r.mean()))
    yrs = (ds[-1] - ds[0]).days / 365.25
    ew = float(np.prod([1 + x for x in rets]) ** (1 / yrs) - 1)
    ra, rb = ref.asof(ds[0]), ref.asof(ds[-1])
    if not (ra and rb and ra > 0):
        return None
    rf = float((rb / ra) ** (1 / yrs) - 1)
    return {"ew_cagr": round(ew, 4), "ref_cagr": round(rf, 4), "pa": round(max(0.0, ew - rf), 4),
            "from": ds[0].strftime("%Y-%m-%d"), "to": ds[-1].strftime("%Y-%m-%d")}


def build_sim_data(ctx, meta: pd.DataFrame, bench_eur: dict, asof: pd.Timestamp, log=print,
                   backfill: list | None = None, pit_info: dict | None = None) -> dict:
    if not ctx.signals:
        ctx.compute_signals()
    p = ctx.params
    dates = list(ctx.dates)
    world = bench_eur.get("msci_world_eur", {}).get("eur") if bench_eur.get("msci_world_eur") else None
    mkt_proxy = None
    if world is None or len(world) < 300:
        world = None
    # Marktreihe für Stage-2-Kursteil: MSCI World, vorher gleichgewichteter Markt (gekennzeichnet)
    ew = ctx.market if hasattr(ctx, "market") else None
    ranks, cands, holds, s2, s2sc, zs, zr = [], [], [], [], [], [], []
    syms: dict[str, int] = {}
    raw_lists = []
    for k, d in enumerate(dates):
        sig = ctx.signals[d]
        sc, f, elig = sig["ra"], sig["f"], sig["elig"]
        valid = elig & sc["score_valid"].reindex(elig.index).fillna(False).astype(bool)
        z = sc["Z"].reindex(valid.index)
        order = z[valid].dropna().sort_values(ascending=False).index[:TOP_K].tolist()
        cand_set = core.select_candidates(f, sc, elig, 10 ** 6, p)
        cand_order = [s for s in cand_set[:TOP_K]]
        top = list(dict.fromkeys(cand_order + order))[:TOP_K + 4]
        mkt = world if (world is not None and world.index[0] <= d - pd.DateOffset(months=13)) else ew
        try:
            s2_order, s2_score = _stage2_rank(ctx, d, sig, cand_set[:10], mkt)
        except Exception as exc:  # noqa: BLE001
            log(f"[simulator] Stage-2-Kursteil {d.date()} nicht berechenbar: {exc}")
            s2_order, s2_score = [], {}
        raw_lists.append((top, order, cand_set[:TOP_K], s2_order, s2_score, mkt is world and world is not None))
        for s in top:
            syms.setdefault(s, len(syms))
        if (k + 1) % 36 == 0:
            log(f"[simulator] {k + 1}/{len(dates)} Monate ({d.date()})")
    sym_list = list(syms)
    exec_days = [ctx.exec_day[d] for d in dates]
    last_day = ctx.price_eur.index[ctx.price_eur.index <= asof][-1]
    points = exec_days + ([last_day] if last_day > exec_days[-1] else [])
    px = ctx.price_eur.reindex(columns=sym_list).reindex(points)
    for k, d in enumerate(dates):
        top, order, cand, s2_order, s2_score, world_used = raw_lists[k]
        idx = {s: syms[s] for s in top}
        ranks.append([idx[s] for s in order if s in idx])
        cands.append([idx[s] for s in cand if s in idx])
        zrow = ctx.signals[d]["ra"]["Z"]
        zs.append([None if not np.isfinite(zrow.get(s, np.nan)) else round(float(zrow[s]), 3) for s in cand if s in idx])
        zr.append([None if not np.isfinite(zrow.get(s, np.nan)) else round(float(zrow[s]), 3) for s in order if s in idx])
        s2.append([idx[s] for s in s2_order if s in idx])
        s2sc.append([round(s2_score[s], 2) for s in s2_order if s in idx])
        sig = ctx.signals[d]
        hs = core.hold_state(sig["ra"]["pct"], sig["f"]["m12"], sig["q"]["data_ok"], sig["ra"]["score_valid"], p)
        code = []
        mem = None
        if getattr(ctx, "membership", None):
            keys = [m for m in ctx.membership if m <= d.strftime("%Y-%m")]
            mem = ctx.membership[max(keys)] if keys else set()
        for s in sym_list:
            if s not in hs.index or (mem is not None and s not in mem):
                code.append("3")      # Datenproblem oder nicht mehr im Index
                continue
            if bool(hs.at[s, "data_problem"]):
                code.append("3")
            elif bool(hs.at[s, "severe"]):
                code.append("2")
            elif bool(hs.at[s, "H"]):
                code.append("1")
            else:
                code.append("0")
        holds.append("".join(code))
    bench_out = {}
    for key, b in bench_eur.items():
        if key not in ("msci_world_eur", "sp500_tr", "sp500_eur"):
            continue
        s = b["eur"].dropna()
        if len(s) < 250:
            continue
        ext = None
        if key == "msci_world_eur" and backfill:
            s, ext = chain_backfill(s, backfill, log=log)
        if key == "sp500_tr":  # Index ohne Kosten: laufende ETF-Kosten (0,07 % p. a.) abziehen
            yrs = (s.index - s.index[0]).days / 365.25
            s = s * np.exp(-0.0007 * yrs)
        ser = s.reindex(s.index.union(pd.DatetimeIndex(points))).ffill(limit=7).reindex(points)
        ser[pd.DatetimeIndex(points) < s.index[0]] = np.nan
        bench_out[key] = {"name": b["name"], "start": s.index[0].strftime("%Y-%m-%d"), "px": [_round(x) for x in ser.values]}
        if ext:
            bench_out[key]["extended"] = ext
    # S&P 500: Index (Total Return) bevorzugt, sonst ETF
    if "sp500_tr" in bench_out:
        bench_out["sp500"] = bench_out.pop("sp500_tr")
        bench_out.pop("sp500_eur", None)
    elif "sp500_eur" in bench_out:
        bench_out["sp500"] = bench_out.pop("sp500_eur")
    if "msci_world_eur" in bench_out:
        bench_out["msci_world"] = bench_out.pop("msci_world_eur")
    # Kursdaten enden (Delisting, Übernahme): letzten Kurs fortschreiben, Ende markieren
    ended = {}
    for j, sname in enumerate(sym_list):
        col = px[sname]
        lv = col.last_valid_index()
        if lv is not None and lv < points[-1]:
            k_end = int(np.searchsorted(np.array(points), lv, side="right")) - 1
            if k_end < len(points) - 3:
                ended[j] = k_end
    px = px.ffill()
    ref_key = "acwi_usd" if (pit_info or {}).get("kind") == "acwi" and bench_eur.get("acwi_usd") else "msci_world_eur"
    bias = measure_bias(ctx, dates, (bench_eur.get(ref_key) or {}).get("eur"))
    if bias:
        bias["ref_name"] = bench_eur[ref_key]["name"]
        log(f"[simulator] gemessene Verzerrung: Liste gleichgewichtet {bias['ew_cagr']:.2%} vs. {bias['ref_name']} "
            f"{bias['ref_cagr']:.2%} -> {bias['pa']:.2%} p. a.")
    names = meta["name"].reindex(sym_list).fillna(pd.Series(sym_list, index=sym_list)).tolist()
    sectors = meta["sector"].reindex(sym_list).fillna("").tolist()
    return {
        "schema": SCHEMA,
        "signal_dates": [d.strftime("%Y-%m-%d") for d in dates],
        "points": [d.strftime("%Y-%m-%d") for d in points],
        "syms": sym_list, "names": names, "sectors": sectors,
        "px": [[_round(x) for x in px[s].values] for s in sym_list],
        "rank": ranks, "cand": cands, "cand_z": zs, "rank_z": zr, "hold": holds, "s2": s2, "s2_score": s2sc, "s2_version": "2.0.0",
        "s2_world": [bool(x[5]) for x in raw_lists],
        "bench": bench_out,
        "ended": ended,
        "bias": bias,
        "pit": pit_info,
        "notes": {
            "survivorship": ("Historische Indexzusammensetzung: In jedem Monat nur die Aktien, die damals im Index waren "
                             "(iShares-Bestandslisten). Ehemalige Mitglieder ohne Yahoo-Kurse fehlen weiterhin."
                             if (pit_info or {}).get("active") else
                             "Liste der Aktien = HEUTIGE Indexmitglieder. Firmen, die seitdem aus dem Index "
                             "gefallen sind, fehlen. Die Ergebnisse sind dadurch zu günstig."),
            "stage2": "Stage 2 (v2, Fortsetzungs-Rangfolge) nur mit dem Kursteil: Die Top-10-Kandidaten werden nach "
                      "gleichmäßigem Anstieg (Frog-in-the-Pan), Nähe zum 52-Wochen-Hoch und marktbereinigtem Momentum "
                      "sortiert; gekauft werden die besten 5. Die Analystensignale (Schätzungsänderungen, Gewinnüberraschungen) "
                      "gibt es für damals nicht kostenlos; sie fließen nur live ein. Vor Oktober 2010 dient der "
                      "gleichgewichtete Markt als Vergleich für das marktbereinigte Momentum.",
        },
    }
