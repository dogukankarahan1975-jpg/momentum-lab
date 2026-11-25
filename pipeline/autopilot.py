"""Autopilot (Methodik AP v1.0.0): fester Monatsplan aus kursbasierten, getesteten Regeln.

Regeln je Monat (Signal am letzten Handelstag des Monats, Handel zum Schluss des nächsten Handelstags):
  1. Verkauf: Stage-1-Halteregel (außerhalb der besten 20 % oder 12-1-Momentum <= 0 an zwei Monatsenden
     in Folge; sofort bei "schwer": unter dem Median oder 12-1-Momentum <= -10 %).
  2. Markt-Trendfilter (je Variante): gleichgewichteter Markt unter seiner 200-Tage-Linie =>
     "soft": keine Neukäufe, "hard": alles verkaufen und Geld parken.
  3. Kauf: freie Plätze (bis n) mit den bestplatzierten Stage-1-Kandidaten füllen, die noch nicht gehalten
     werden; Branchengrenze beachten. Zielbetrag je Aktie = Depotwert / n; in Rangfolge kaufen, solange das
     Geld reicht (keine Kleinstorders unter 50 €).
  4. Übriges Geld (Sparrate, Verkaufserlöse): Positionen auffüllen, die mehr als 25 % unter Ziel liegen.
     Gewinner werden nie gekürzt (keine unnötigen Steuern).

Die Variantenauswahl erfolgt automatisch und nur mit Daten 2003–2014; 2015–heute ist Prüfzeitraum.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import core
from .backtest import Book, _f, _value_path, monthly_points, perf_metrics
from .config import AUTOPILOT, AUTOPILOT_VERSION, COST_SCENARIOS, METHODOLOGY, TAX, autopilot_params_hash

MARKET_LABEL = {"none": "ohne Markt-Trendfilter",
                "soft": "Trendfilter: im Abwärtstrend keine Neukäufe",
                "hard": "Trendfilter: im Abwärtstrend alles verkaufen und Geld parken"}


def variants() -> list[dict]:
    out = []
    g = AUTOPILOT["grid"]
    for n in g["n"]:
        for cap in g["sector_cap"]:
            for mk in g["market"]:
                vid = f"ap_n{n}_{'cap' if cap else 'nocap'}_{mk}"
                name = (f"{n} Aktien, " + (f"max. {cap_count(n, cap)} je Branche" if cap else "ohne Branchengrenze")
                        + ", " + MARKET_LABEL[mk])
                out.append({"id": vid, "n": n, "sector_cap": cap, "market": mk, "name": name})
    return out


def cap_count(n: int, cap: float | None) -> int | None:
    return None if not cap else max(2, int(math.floor(n * cap + 1e-9)))


def _sector_of(sectors: pd.Series, s: str) -> str | None:
    v = sectors.get(s) if sectors is not None else None
    return v if isinstance(v, str) and v.strip() else None


def pick_buys(cands: list[str], held: list[str], free: int, sectors: pd.Series, cap_n: int | None,
              price_ok=lambda s: True) -> tuple[list[str], list[dict]]:
    """Wählt bis zu `free` neue Aktien in Rangfolge; überspringt gehaltene und Branchen am Limit."""
    cnt: dict[str, int] = defaultdict(int)
    for s in held:
        sec = _sector_of(sectors, s)
        if sec:
            cnt[sec] += 1
    picks, skipped = [], []
    for c in cands:
        if len(picks) >= free:
            break
        if c in held or not price_ok(c):
            continue
        sec = _sector_of(sectors, c)
        if cap_n and sec and cnt[sec] >= cap_n:
            skipped.append({"symbol": c, "reason": f"Branchengrenze ({sec}: bereits {cnt[sec]})"})
            continue
        picks.append(c)
        if sec:
            cnt[sec] += 1
    return picks, skipped


def simulate(ctx, v: dict, sectors: pd.Series, cost: dict, capital: float = 10_000.0, taxes: bool = False,
             monthly: float = 0.0, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> dict | None:
    p = ctx.params
    book = Book(cash=capital, tax_on=taxes)
    book.contributions = capital
    dates = [d for d in ctx.dates if (start is None or ctx.exec_day[d] >= start) and (end is None or d <= end)]
    if len(dates) < 12:
        return None
    cap_n = cap_count(v["n"], v["sector_cap"])
    tol, min_order = AUTOPILOT["topup_tolerance"], AUTOPILOT["min_order_eur"]
    hcount: dict[str, int] = defaultdict(int)
    parts, flows, bear_months = [], [(ctx.exec_day[dates[0]], -capital)] if capital else [], 0
    for k, d in enumerate(dates):
        if end is not None and k == len(dates) - 1:
            break  # Lernzeitraum endet mit dem letzten Signal: keine Haltedauer danach (kein Blick in 2015)
        e = ctx.exec_day[d]
        nxt = ctx.exec_day[dates[k + 1]] if k + 1 < len(dates) else None
        prices = ctx.price_eur.loc[e]
        book.settle_taxes(e.year, prices)
        if monthly:
            book.cash += monthly
            book.contributions += monthly
            flows.append((e, -monthly))
        sig = ctx.signals[d]
        sc, f, elig = sig["ra"], sig["f"], sig["elig"]
        bear = not sig["market_bull"]
        bear_months += int(bear)
        hs = core.hold_state(sc["pct"], f["m12"], sig["q"]["data_ok"], sc["score_valid"], p)
        for s in book.holdings():
            cond = bool(hs.at[s, "H"] or hs.at[s, "data_problem"]) if s in hs.index else True
            hcount[s] = hcount[s] + 1 if cond else 0
            severe = bool(hs.at[s, "severe"]) if s in hs.index else False
            if cond and (hcount[s] >= p["confirm_months"] or severe):
                book.sell(s, None, prices.get(s, np.nan), cost, e.year)
                hcount[s] = 0
        if v["market"] == "hard" and bear:
            for s in book.holdings():
                book.sell(s, None, prices.get(s, np.nan), cost, e.year)
                hcount[s] = 0
        elif not (v["market"] == "soft" and bear):
            total = book.value(prices)
            target = total / v["n"]
            held = book.holdings()
            free = v["n"] - len(held)
            if free > 0:
                cands = core.select_candidates(f, sc, elig, 10_000, p)
                picks, _ = pick_buys(cands, held, free, sectors, cap_n,
                                     lambda s: np.isfinite(prices.get(s, np.nan)) and prices.get(s) > 0)
                # in Rangfolge je bis zum Zielbetrag kaufen, solange das Geld reicht (keine Mini-Orders)
                for c in picks:
                    if book.cash < min_order:
                        break
                    book.buy(c, min(max(target, min_order), book.cash), prices[c], cost)
            # Auffüllen untergewichteter Positionen (Sparrate / Restgeld), Gewinner werden nie gekürzt
            if book.cash > min_order:
                held = book.holdings()
                short = {}
                for s in held:
                    px = prices.get(s, np.nan)
                    if not np.isfinite(px):
                        continue
                    cur = book.shares(s) * px
                    if cur < target * (1 - tol):
                        short[s] = target - cur
                tot_short = sum(short.values())
                if tot_short > 0:
                    budget = min(book.cash, tot_short)
                    for s, need in short.items():
                        amt = budget * need / tot_short
                        if amt >= min_order:
                            book.buy(s, amt, prices[s], cost)
        parts.append((e, _value_path(book, ctx.price_eur, e, nxt)))
    values = pd.concat([pt for _, pt in parts])
    values = values[~values.index.duplicated(keep="first")]
    end_prices = ctx.price_eur.loc[values.index[-1]]
    after_tax = book.liquidation_value_after_tax(end_prices, values.index[-1].year) if taxes else None
    return {"values": values, "book": book, "after_tax_final": after_tax, "flows": flows,
            "bear_months": bear_months, "months": len(dates)}


def _cagr(start_val: float, end_val: float, years: float) -> float | None:
    if not (start_val and end_val and years > 0) or start_val <= 0 or end_val <= 0:
        return None
    return (end_val / start_val) ** (1 / years) - 1


def _summ(pre: dict, taxed: dict, capital: float) -> dict:
    m = perf_metrics(pre["values"])
    years = m.get("years") or 0
    after = taxed["after_tax_final"] if taxed else None
    return {
        "start": m.get("start"), "end": m.get("end"), "years": m.get("years"),
        "cagr": _f(m.get("cagr")), "cagr_after_tax": _f(_cagr(capital, after, years)) if after else None,
        "max_drawdown": _f(m.get("max_drawdown")), "max_dd_date": m.get("max_dd_date"),
        "volatility": _f(m.get("volatility")), "final": _f(pre["values"].iloc[-1]),
        "final_after_tax": _f(after), "trades": pre["book"].trades,
        "taxes_paid": _f(taxed["book"].tax_paid) if taxed else None,
        "fees": _f(pre["book"].fees + pre["book"].spread_cost),
        "cash_months_share": _f(pre["bear_months"] / pre["months"]) if pre.get("months") else None,
        "worst_year": _worst_year(pre["values"]),
    }


def _worst_year(values: pd.Series) -> dict | None:
    y = values.groupby(values.index.year).last()
    if len(y) < 2:
        return None
    first = values.iloc[0]
    r = (y / y.shift(1).fillna(first) - 1)
    k = r.idxmin()
    return {"year": int(k), "return": _f(r.loc[k])}


def _etf_window(series: pd.Series | None, start: pd.Timestamp, capital: float) -> dict | None:
    if series is None:
        return None
    s = series.dropna()
    s = s[s.index >= start]
    if len(s) < 250 or (s.index[0] - start).days > 20:
        return None
    vals = s / s.iloc[0] * capital
    m = perf_metrics(vals)
    gain = vals.iloc[-1] - capital
    taxable = max(0.0, gain * (1 - TAX["etf_partial_exemption"]) - TAX["allowance"])
    after = vals.iloc[-1] - taxable * TAX["rate"]
    return {"start": m.get("start"), "end": m.get("end"), "cagr": _f(m.get("cagr")),
            "cagr_after_tax": _f(_cagr(capital, after, m.get("years") or 0)),
            "max_drawdown": _f(m.get("max_drawdown")), "max_dd_date": m.get("max_dd_date"),
            "final": _f(vals.iloc[-1]), "final_after_tax": _f(after), "curve": monthly_points(vals)}


def run_autopilot_backtest(ctx, sectors: pd.Series, log=print) -> dict:
    """Erwartet einen Context mit berechneten Signalen (run_backtest hat compute_signals bereits aufgerufen)."""
    if not ctx.signals:
        ctx.compute_signals()
    sel = AUTOPILOT["selection"]
    is_end = pd.Timestamp(sel["insample_end"])
    oos_start = pd.Timestamp(sel["oos_start"])
    cost = COST_SCENARIOS["realistisch"]
    capital = 10_000.0
    grid = []
    for v in variants():
        log(f"[autopilot] Lernzeitraum {v['id']}")
        pre = simulate(ctx, v, sectors, cost, capital, taxes=False, end=is_end)
        tax = simulate(ctx, v, sectors, cost, capital, taxes=True, end=is_end)
        if pre is None or tax is None:
            continue
        row = {"id": v["id"], "name": v["name"], "n": v["n"], "sector_cap": cap_count(v["n"], v["sector_cap"]),
               "market": v["market"], "insample": _summ(pre, tax, capital)}
        grid.append(row)
    if not grid:
        return {"available": False, "reason": "Zu wenig Kurshistorie für den Lernzeitraum 2003–2014."}
    limit = sel["max_drawdown_limit"]
    ok = [g for g in grid if g["insample"]["max_drawdown"] is not None and g["insample"]["max_drawdown"] >= limit
          and g["insample"]["cagr_after_tax"] is not None]
    if ok:
        chosen = max(ok, key=lambda g: g["insample"]["cagr_after_tax"])
        how = "Grenze eingehalten"
    else:
        chosen = max(grid, key=lambda g: g["insample"]["max_drawdown"] or -9)
        how = "Keine Variante blieb über -45 %; gewählt: kleinster Zwischenverlust"
    for g in grid:
        g["meets_limit"] = g in ok
        g["chosen"] = g is chosen
    base = next((g for g in grid if g["n"] == 10 and g["sector_cap"] is None and g["market"] == "none"), None)
    vmap = {v["id"]: v for v in variants()}
    # Prüfzeitraum: frischer Start 2015 (gleiches Startkapital wie die ETFs)
    oos = {}
    oos_curves = {}
    for g in [chosen] + ([base] if base and base is not chosen else []):
        v = vmap[g["id"]]
        log(f"[autopilot] Prüfzeitraum {v['id']}")
        pre = simulate(ctx, v, sectors, cost, capital, taxes=False, start=oos_start)
        tax = simulate(ctx, v, sectors, cost, capital, taxes=True, start=oos_start)
        if pre and tax:
            oos[g["id"]] = _summ(pre, tax, capital)
            oos_curves[g["id"]] = monthly_points(pre["values"])
    bench = {}
    first_exec = min((ctx.exec_day[d] for d in ctx.dates if ctx.exec_day[d] >= oos_start), default=oos_start)
    for key in ("msci_world_eur", "msci_momentum_eur"):
        b = ctx.benchmarks.get(key)
        r = _etf_window(b["eur"] if b else None, first_exec, capital)
        if r:
            r["name"] = b["name"]
            bench[key] = r
    # Gesamtzeitraum und Sparplan der gewählten Variante
    v = vmap[chosen["id"]]
    log(f"[autopilot] Gesamtzeitraum {v['id']}")
    pre = simulate(ctx, v, sectors, cost, capital, taxes=False)
    tax = simulate(ctx, v, sectors, cost, capital, taxes=True)
    full = _summ(pre, tax, capital) if pre and tax else None
    full_curve = monthly_points(pre["values"]) if pre else []
    dd_curve = monthly_points((pre["values"] / pre["values"].cummax() - 1) * 100) if pre else []
    monthly = AUTOPILOT["monthly_savings"]
    sp_pre = simulate(ctx, v, sectors, cost, 0.0, taxes=False, monthly=monthly, start=oos_start)
    sp_tax = simulate(ctx, v, sectors, cost, 0.0, taxes=True, monthly=monthly, start=oos_start)
    savings = None
    if sp_pre and sp_tax:
        contrib = sp_pre["book"].contributions
        savings = {"start": sp_pre["values"].index[0].strftime("%Y-%m-%d"), "monthly": monthly,
                   "contributions": _f(contrib), "final": _f(sp_pre["values"].iloc[-1]),
                   "final_after_tax": _f(sp_tax["after_tax_final"]), "trades": sp_pre["book"].trades,
                   "taxes_paid": _f(sp_tax["book"].tax_paid)}
        etf = ctx.benchmarks.get("msci_world_eur")
        if etf is not None:
            s = etf["eur"].dropna()
            s = s[s.index >= sp_pre["values"].index[0]]
            months = sorted({(d.year, d.month) for d in sp_pre["values"].index})
            units, paid = 0.0, 0.0
            for y, mth in months:
                px = s[(s.index.year == y) & (s.index.month == mth)]
                if len(px):
                    units += monthly * (1 - cost["spread"]) / px.iloc[0]
                    paid += monthly
            if len(s) and paid:
                val = units * s.iloc[-1]
                taxable = max(0.0, (val - paid) * (1 - TAX["etf_partial_exemption"]) - TAX["allowance"])
                savings["etf"] = {"contributions": _f(paid), "final": _f(val),
                                  "final_after_tax": _f(val - taxable * TAX["rate"])}
    return {
        "available": True, "version": AUTOPILOT_VERSION, "params_hash": autopilot_params_hash(),
        "selection_rule": sel["rule"], "selection_result": how, "max_drawdown_limit": limit,
        "insample": {"start": grid[0]["insample"]["start"], "end": sel["insample_end"]},
        "oos_start": sel["oos_start"], "chosen": chosen["id"], "baseline": base["id"] if base else None,
        "grid": grid, "oos": oos, "oos_curves": oos_curves, "benchmarks_oos": bench,
        "full": full, "full_curve": full_curve, "full_drawdown": dd_curve, "savings": savings,
        "cost": cost, "tax": TAX,
        "warnings": [
            "Survivorship Bias: Getestet wird mit den HEUTIGEN Indexmitgliedern. Echte Ergebnisse wären "
            "wahrscheinlich schlechter.",
            "Geparktes Geld wird mit 0 % Zins gerechnet (vorsichtig).",
            "Steuern: 26,375 % auf realisierte Gewinne, 1.000 € Pauschbetrag, Verlustverrechnung, jährlich gezahlt. "
            "Dividendenbesteuerung und Vorabpauschale sind vereinfacht nicht modelliert.",
            "Vergangene Ergebnisse sind keine Garantie für die Zukunft.",
        ],
    }


# ------------------------------------------------------------------------------------------- Monatsplan
def next_plan_date(today: date) -> date:
    """Erster Werktag des Folgemonats + 1 Tag (der Lauf am Abend des ersten Börsentags liefert den Plan)."""
    first = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
    d = first
    while d.weekday() >= 5:
        d += timedelta(days=1)
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def live_plan(ctx, rule: dict, sectors: pd.Series, names: pd.Series, today: date, market_now: dict | None = None) -> dict:
    """Monatsplan aus den letzten beiden Monatsenden des Contexts (gleiche Logik wie im Backtest)."""
    p = ctx.params
    if len(ctx.dates) < 2:
        return {"available": False, "reason": "Zu wenige Monatsenden mit Daten."}
    d0, d1 = ctx.dates[-2], ctx.dates[-1]
    for d in (d0, d1):
        if d not in ctx.signals:
            raise ValueError("Signale fehlen")
    s0, s1 = ctx.signals[d0], ctx.signals[d1]
    hs1 = core.hold_state(s1["ra"]["pct"], s1["f"]["m12"], s1["q"]["data_ok"], s1["ra"]["score_valid"], p)
    hs0 = core.hold_state(s0["ra"]["pct"], s0["f"]["m12"], s0["q"]["data_ok"], s0["ra"]["score_valid"], p)
    status = {}
    pct = s1["ra"]["pct"]
    for s in hs1.index:
        H1 = bool(hs1.at[s, "H"])
        H0 = bool(hs0.at[s, "H"]) if s in hs0.index else True
        dp = bool(hs1.at[s, "data_problem"])
        sev = bool(hs1.at[s, "severe"])
        if dp:
            code = "P"
        elif H1 and (H0 or sev):
            code = "V"
        elif H1:
            code = "W"
        else:
            code = "H"
        pv = pct.get(s)
        status[s] = [code, None if pv is None or not np.isfinite(pv) else round(float(pv), 4)]
    cands = core.select_candidates(s1["f"], s1["ra"], s1["elig"], AUTOPILOT["buy_list_len"], p)
    buy_list = []
    for i, c in enumerate(cands, 1):
        buy_list.append({"rank": i, "symbol": c, "name": str(names.get(c, c)), "sector": _sector_of(sectors, c),
                         "pct": _f(s1["ra"].at[c, "pct"]), "m12": _f(s1["f"].at[c, "m12"]), "m6": _f(s1["f"].at[c, "m6"])})
    bear = not s1["market_bull"]
    n, mk, cap = rule["n"], rule["market"], rule.get("sector_cap")
    if mk == "hard" and bear:
        action = "PARKEN"
        action_text = ("Der Gesamtmarkt liegt unter seiner 200-Tage-Linie. Regel: alle Aktien verkaufen und das Geld "
                       "parken (Tagesgeld), bis der Markt wieder darüber liegt.")
    elif mk == "soft" and bear:
        action = "KEINE_KAEUFE"
        action_text = ("Der Gesamtmarkt liegt unter seiner 200-Tage-Linie. Regel: diesen Monat keine neuen Aktien kaufen. "
                       "Verkaufssignale gelten weiter; neues Geld bleibt geparkt.")
    else:
        action = "NORMAL"
        action_text = "Normaler Monat: Verkaufssignale umsetzen, freie Plätze mit der Kaufliste füllen."
    return {
        "available": True, "signal_date": d1.strftime("%Y-%m-%d"), "prev_signal_date": d0.strftime("%Y-%m-%d"),
        "trade_from": ctx.exec_day[d1].strftime("%Y-%m-%d"), "next_plan": next_plan_date(today).isoformat(),
        "rule": {"id": rule["id"], "name": rule["name"], "n": n, "sector_cap": cap, "market": mk},
        "market": {"bull": not bear, "now": market_now}, "action": action, "action_text": action_text,
        "buy_list": buy_list, "status": status,
        "status_legend": {"H": "Halten", "W": "Warnung: Verkaufsbedingung einmal erfüllt",
                          "V": "Verkaufen", "P": "Datenproblem: selbst prüfen"},
    }


def default_rule() -> dict:
    """Vor dem ersten Backtest gilt die vorsichtigste getestete Annahme des Rasters."""
    v = next(x for x in variants() if x["n"] == 10 and x["sector_cap"] and x["market"] == "soft")
    return {"id": v["id"], "name": v["name"], "n": v["n"], "sector_cap": cap_count(v["n"], v["sector_cap"]),
            "market": v["market"], "provisional": True}
