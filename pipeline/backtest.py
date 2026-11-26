"""Backtest der vorab festgelegten Varianten (config.BACKTEST_VARIANTS / SAVINGS_VARIANTS).

Grundsätze gegen typische Backtest-Fehler:
- Kein Look-ahead: Signale nutzen nur Daten bis Monatsende d; gehandelt wird am nächsten Handelstag.
- Dieselben Funktionen wie im Live-Screening (core.py).
- Kosten (Ordergebühr + Spread) und deutsche Abgeltungsteuer (FIFO, Pauschbetrag, Verlustvortrag).
- Keine Parameteroptimierung: alle Varianten stehen vorher fest.
- Bekannte, NICHT behebbare Verzerrung: Das Universum besteht aus HEUTIGEN Indexmitgliedern
  (Survivorship Bias). Fairerer Maßstab: gleichgewichtetes Universum mit derselben Verzerrung.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import core
from .config import BACKTEST, BACKTEST_VARIANTS, COST_SCENARIOS, METHODOLOGY, SAVINGS_VARIANTS, TAX
from .fx import fx_on_index

NAMED_PERIODS = [
    ("Finanzkrise", "2007-10-31", "2009-03-09"),
    ("Momentum-Crash 2009", "2009-03-09", "2009-06-30"),
    ("Euro-Schuldenkrise", "2011-04-29", "2011-10-04"),
    ("Corona-Crash", "2020-02-19", "2020-03-23"),
    ("Corona-Erholung", "2020-03-23", "2020-08-31"),
    ("Zinswende-Bärenmarkt 2022", "2021-12-31", "2022-10-12"),
]


@dataclass
class Lot:
    shares: float
    cost: float


@dataclass
class Book:
    cash: float = 0.0
    etf_exemption: float = 0.0
    lots: dict = field(default_factory=dict)
    realized: dict = field(default_factory=lambda: defaultdict(float))
    loss_carry: float = 0.0
    tax_paid: float = 0.0
    fees: float = 0.0
    spread_cost: float = 0.0
    trades: int = 0
    traded_value: float = 0.0
    closed_gains: list = field(default_factory=list)
    contributions: float = 0.0
    taxed_through: int = 0
    tax_on: bool = True

    def shares(self, sym: str) -> float:
        return sum(l.shares for l in self.lots.get(sym, []))

    def holdings(self) -> list[str]:
        return [s for s, ls in self.lots.items() if sum(l.shares for l in ls) > 1e-12]

    def value(self, prices: pd.Series) -> float:
        v = self.cash
        for s in self.holdings():
            p = prices.get(s, np.nan)
            if np.isfinite(p):
                v += self.shares(s) * p
        return v

    def buy(self, sym: str, amount: float, price: float, cost: dict) -> None:
        fee, spread = cost["fee"], cost["spread"]
        amount = min(amount, self.cash)
        if not np.isfinite(price) or price <= 0 or amount <= fee + 1.0:
            return
        net = (amount - fee) * (1 - spread)
        self.lots.setdefault(sym, []).append(Lot(net / price, amount))
        self.cash -= amount
        self.fees += fee
        self.spread_cost += (amount - fee) * spread
        self.trades += 1
        self.traded_value += amount

    def sell(self, sym: str, shares: float | None, price: float, cost: dict, year: int) -> None:
        held = self.shares(sym)
        if held <= 1e-12 or not np.isfinite(price) or price <= 0:
            return
        shares = held if shares is None else min(shares, held)
        gross = shares * price
        spread_c = gross * cost["spread"]
        proceeds = gross - spread_c - cost["fee"]
        remaining, basis = shares, 0.0
        lots = self.lots[sym]
        while remaining > 1e-12 and lots:
            lot = lots[0]
            take = min(lot.shares, remaining)
            frac = take / lot.shares
            basis += lot.cost * frac
            lot.cost -= lot.cost * frac
            lot.shares -= take
            remaining -= take
            if lot.shares <= 1e-12:
                lots.pop(0)
        gain = proceeds - basis
        self.realized[year] += gain * (1 - self.etf_exemption)
        self.cash += proceeds
        self.fees += cost["fee"]
        self.spread_cost += spread_c
        self.trades += 1
        self.traded_value += gross
        if self.shares(sym) <= 1e-12:
            self.lots.pop(sym, None)
            self.closed_gains.append(gain)

    def settle_taxes(self, up_to_year: int, prices: pd.Series) -> None:
        """Zahlt Abgeltungsteuer für alle abgeschlossenen Jahre < up_to_year."""
        if not self.tax_on:
            return
        for y in range(max(self.taxed_through + 1, min(self.realized.keys(), default=up_to_year)), up_to_year):
            g = self.realized.get(y, 0.0) + self.loss_carry
            if g < 0:
                self.loss_carry = g
                taxable = 0.0
            else:
                self.loss_carry = 0.0
                taxable = max(0.0, g - TAX["allowance"])
            tax = taxable * TAX["rate"]
            if tax > 0:
                self._pay(tax, prices)
                self.tax_paid += tax
            self.taxed_through = y
        self.taxed_through = max(self.taxed_through, up_to_year - 1)

    def _pay(self, amount: float, prices: pd.Series) -> None:
        if self.cash >= amount:
            self.cash -= amount
            return
        need = amount - self.cash
        self.cash = 0.0
        invested = self.value(prices)
        if invested <= 0:
            return
        keep = max(0.0, 1 - need / invested)
        for s in self.holdings():
            for lot in self.lots[s]:
                lot.shares *= keep
                lot.cost *= keep

    def liquidation_value_after_tax(self, prices: pd.Series, year: int) -> float:
        gross = self.value(prices)
        unreal = 0.0
        for s in self.holdings():
            p = prices.get(s, np.nan)
            if not np.isfinite(p):
                continue
            unreal += self.shares(s) * p - sum(l.cost for l in self.lots[s])
        g = (self.realized.get(year, 0.0) + unreal * (1 - self.etf_exemption)) + self.loss_carry
        taxable = max(0.0, g - TAX["allowance"])
        return gross - taxable * TAX["rate"]


# ---------------------------------------------------------------------- Kennzahlen
def perf_metrics(values: pd.Series, rf: float = 0.0) -> dict:
    v = values.dropna()
    v = v[v > 0]
    if len(v) < 30:
        return {}
    years = (v.index[-1] - v.index[0]).days / 365.25
    total = v.iloc[-1] / v.iloc[0] - 1
    cagr = (v.iloc[-1] / v.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    daily = v.pct_change().dropna()
    vol = daily.std() * math.sqrt(252)
    dd = v / v.cummax() - 1
    sharpe = (cagr - rf) / vol if vol and np.isfinite(vol) and vol > 0 else np.nan
    return {"start": v.index[0].strftime("%Y-%m-%d"), "end": v.index[-1].strftime("%Y-%m-%d"),
            "years": round(years, 2), "cagr": cagr, "total_return": total, "volatility": vol,
            "max_drawdown": dd.min(), "sharpe": sharpe,
            "max_dd_date": dd.idxmin().strftime("%Y-%m-%d")}


def monthly_points(values: pd.Series) -> list:
    v = values.dropna()
    if v.empty:
        return []
    m = v.groupby([v.index.year, v.index.month]).tail(1)
    return [[d.strftime("%Y-%m-%d"), round(float(x), 2)] for d, x in m.items()]


def xirr(flows: list[tuple[pd.Timestamp, float]]) -> float | None:
    if not flows or all(f >= 0 for _, f in flows) or all(f <= 0 for _, f in flows):
        return None
    t0 = flows[0][0]

    def npv(r):
        return sum(f / (1 + r) ** ((d - t0).days / 365.25) for d, f in flows)
    lo, hi = -0.99, 5.0
    flo, fhi = npv(lo), npv(hi)
    if flo * fhi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = npv(mid)
        if abs(fm) < 1e-7:
            break
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


# ---------------------------------------------------------------------- Kontext
class Context:
    """Alle Monats-Signale werden einmal berechnet und von allen Varianten geteilt."""

    def __init__(self, panel: core.Panel, currencies: pd.Series, fx: pd.DataFrame,
                 duplicates: set, asof: pd.Timestamp, benchmarks: dict, log=print,
                 params: dict = METHODOLOGY, membership: dict | None = None):
        self.panel, self.currencies, self.params, self.log = panel, currencies, params, log
        idx = panel.adj.index
        fx_idx = fx_on_index(fx, idx)
        factor = pd.DataFrame(index=idx, columns=panel.adj.columns, dtype=float)
        for cur, syms in currencies.groupby(currencies).groups.items():
            syms = [s for s in syms if s in factor.columns]
            if cur == "EUR":
                factor[syms] = 1.0
            elif cur in fx_idx.columns:
                factor[syms] = np.repeat((1.0 / fx_idx[cur].values)[:, None], len(syms), axis=1)
        self.price_eur = (panel.adj * factor).ffill(limit=10)
        self.fx_idx = fx_idx
        start = pd.Timestamp(BACKTEST["first_rebalance"])
        last_me = core.last_trading_day_of_prev_month(idx, asof)
        self.dates = core.month_end_dates(idx, start, last_me) if last_me is not None else []
        pos = {d: i for i, d in enumerate(idx)}
        self.exec_day = {d: idx[pos[d] + 1] for d in self.dates if pos[d] + 1 < len(idx)}
        self.dates = [d for d in self.dates if d in self.exec_day]
        # Historische Indexzusammensetzung: nur Monate mit bekannter Zusammensetzung, nur damalige Mitglieder
        self.membership = membership or None
        if self.membership:
            first = min(self.membership)
            self.dates = [d for d in self.dates if d.strftime("%Y-%m") >= first]
        self.signals = {}
        self.benchmarks = benchmarks
        # Marktproxy: gleichgewichtetes Universum (Landeswährungen), tägliche Durchschnittsrendite
        rets = panel.adj.pct_change(fill_method=None)
        rets = rets.where(rets.abs() < 0.5)
        self.market = (1 + rets.mean(axis=1).fillna(0)).cumprod()
        self.market_ma = self.market.rolling(200, min_periods=200).mean()
        dret = self.market.pct_change()
        vol3m = dret.rolling(63, min_periods=50).std() * math.sqrt(250)
        self.vol_me = vol3m.reindex(self.dates)
        self.duplicates = duplicates

    def compute_signals(self):
        p = self.params
        p6 = dict(p, weight_m6=1.0, weight_m12=0.0)
        deltas = []
        for k, d in enumerate(self.dates):
            fx_row = self.fx_idx.loc[d]
            q = core.quality_at(self.panel, d, self.currencies, fx_row, p, None, self.duplicates)
            f = core.features_at(self.panel, d, p, light=True)
            elig = q["eligible"] & f["vol"].notna()
            if self.membership:
                ym = d.strftime("%Y-%m")
                keys = [m for m in self.membership if m <= ym]
                mem = self.membership[max(keys)] if keys else set()
                elig = elig & elig.index.isin(list(mem))
            sig = {"q": q, "f": f, "elig": elig}
            for name in ("ra", "m612", "m12"):
                sig[name] = core.scores_at(f, elig, name, p)
            sig["ra6"] = core.scores_at(f, elig, "ra", p6)
            # MSCI-Volatilitätsschock (Anhang III): Änderung der 3M-Vola > 95. Perzentil der Historie
            shock = False
            if k > 0:
                v0, v1 = self.vol_me.iloc[k - 1], self.vol_me.iloc[k]
                if np.isfinite(v0) and np.isfinite(v1) and v0 > 0:
                    delta = v1 / v0 - 1
                    if len(deltas) >= 36:
                        shock = delta > np.percentile(deltas, 95)
                    deltas.append(delta)
            sig["vol_shock"] = bool(shock)
            m, ma = self.market.get(d), self.market_ma.get(d)
            sig["market_bull"] = bool(not (np.isfinite(ma) and m < ma))
            sig["n_elig"] = int(elig.sum())
            self.signals[d] = sig
            if (k + 1) % 36 == 0:
                self.log(f"[backtest] Signale {k + 1}/{len(self.dates)} ({d.date()})")


# ---------------------------------------------------------------------- Simulation
def _value_path(book: Book, price_eur: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp | None) -> pd.Series:
    sl = price_eur.loc[start:end] if end is None else price_eur.loc[(price_eur.index >= start) & (price_eur.index < end)]
    hold = book.holdings()
    if not hold:
        return pd.Series(book.cash, index=sl.index)
    sh = np.array([book.shares(s) for s in hold])
    px = sl[hold].ffill().fillna(0.0).values
    return pd.Series(book.cash + px @ sh, index=sl.index)


def run_lump_sum(ctx: Context, v: dict, cost: dict, capital: float, taxes: bool = False) -> dict:
    p = ctx.params
    book = Book(cash=capital, tax_on=taxes)
    hcount: dict[str, int] = defaultdict(int)
    parts, cash_w = [], []
    top = v["top"]
    hold_max = v.get("hold_max_pct", p["hold_max_pct"])
    for k, d in enumerate(ctx.dates):
        e = ctx.exec_day[d]
        nxt = ctx.exec_day[ctx.dates[k + 1]] if k + 1 < len(ctx.dates) else None
        sig = ctx.signals[d]
        prices = ctx.price_eur.loc[e]
        book.settle_taxes(e.year, prices)
        sname = "ra6" if (v.get("vol_shock_rule") and sig["vol_shock"]) else v["signal"]
        sc, f, elig = sig[sname], sig["f"], sig["elig"]
        if v["rules"] == "strict":
            _rebalance_strict(book, sc, elig, top, prices, cost, e.year, v.get("weighting") == "score")
        else:
            _rebalance_app(book, sc, f, elig, sig, top, prices, cost, e.year, hcount, hold_max, v, p,
                           market_bull=sig["market_bull"])
        path = _value_path(book, ctx.price_eur, e, nxt)
        parts.append(path)
        tot = path.iloc[0] if len(path) else 0
        cash_w.append(book.cash / tot if tot > 0 else 1.0)
    values = pd.concat(parts) if parts else pd.Series(dtype=float)
    end_prices = ctx.price_eur.iloc[-1]
    after_tax = book.liquidation_value_after_tax(end_prices, ctx.price_eur.index[-1].year)
    return {"values": values, "book": book, "cash_share": float(np.mean(cash_w)) if cash_w else None,
            "after_tax_final": after_tax}


def _rebalance_strict(book, sc, elig, top, prices, cost, year, score_weighted):
    ok = elig & sc["Z"].notna() & sc["rank"].notna()
    target = list(sc.loc[ok].sort_values("rank").index[:top])
    target = [s for s in target if np.isfinite(prices.get(s, np.nan))]
    for s in book.holdings():
        if s not in target:
            book.sell(s, None, prices.get(s, np.nan), cost, year)
    if not target:
        return
    if score_weighted:
        z = sc.loc[target, "Z"]
        raw = np.where(z > 0, 1 + z, 1 / (1 - z))
        w = pd.Series(raw / raw.sum(), index=target)
    else:
        w = pd.Series(1.0 / len(target), index=target)
    total = book.value(prices)
    for s in target:  # Übergewichte abbauen (Toleranzband 25 %)
        cur = book.shares(s) * prices[s]
        tgt = total * w[s]
        if cur > tgt * 1.25:
            book.sell(s, (cur - tgt) / prices[s], prices[s], cost, year)
    needs = {}
    for s in target:
        cur = book.shares(s) * prices[s]
        tgt = total * w[s]
        if cur < tgt * 0.75:
            needs[s] = tgt - cur
    budget = book.cash
    need_total = sum(needs.values())
    for s, amt in needs.items():
        alloc = amt if need_total <= budget else budget * amt / need_total
        book.buy(s, alloc, prices[s], cost)


def _rebalance_app(book, sc, f, elig, sig, top, prices, cost, year, hcount, hold_max, v, p, market_bull=True):
    q = sig["q"]
    hs = core.hold_state(sc["pct"], f["m12"], q["data_ok"], sc["score_valid"], p, hold_max)
    below_ma = (f["above_ma200"] == False)  # noqa: E712
    for s in book.holdings():
        price = prices.get(s, np.nan)
        cond = bool(hs.at[s, "H"]) if s in hs.index else True
        if s in hs.index and hs.at[s, "data_problem"]:
            cond = True
        if v.get("stock_ma_filter") and bool(below_ma.get(s, False)):
            cond = True
        hcount[s] = hcount[s] + 1 if cond else 0
        severe = bool(hs.at[s, "severe"]) if s in hs.index else False
        if cond and (hcount[s] >= p["confirm_months"] or severe):
            book.sell(s, None, price, cost, year)
            hcount[s] = 0
    if v.get("market_filter") and not market_bull:
        for s in book.holdings():
            book.sell(s, None, prices.get(s, np.nan), cost, year)
        return
    extra = (f["above_ma200"] == True) if v.get("stock_ma_filter") else None  # noqa: E712
    cands = core.select_candidates(f, sc, elig, p["top_n"], p, extra)
    if top == 1:
        tp, _ = core.pick_top(cands, f, sc, elig, p)
        cands = [tp] if tp else cands[:1]
    cands = [c for c in cands if np.isfinite(prices.get(c, np.nan))]
    held = book.holdings()
    free = top - len(held)
    buys = [c for c in cands if c not in held][:max(free, 0)]
    if buys and book.cash > 50:
        amt = book.cash / len(buys)
        for c in buys:
            book.buy(c, amt, prices[c], cost)


def run_savings(ctx: Context, sv: dict, cost: dict, monthly: float, etf_series: pd.Series | None,
                start: pd.Timestamp, taxes: bool = False) -> dict | None:
    p = ctx.params
    book = Book(cash=0.0, etf_exemption=TAX["etf_partial_exemption"] if sv.get("etf") else 0.0, tax_on=taxes)
    hcount: dict[str, int] = defaultdict(int)
    dates = [d for d in ctx.dates if ctx.exec_day[d] >= start]
    if not dates:
        return None
    price_eur = ctx.price_eur
    if sv.get("etf"):
        if etf_series is None or etf_series.dropna().empty:
            return None
        price_eur = pd.DataFrame({"ETF": etf_series.reindex(ctx.price_eur.index).ffill(limit=10)})
    flows, parts = [], []
    for k, d in enumerate(dates):
        e = ctx.exec_day[d]
        nxt = ctx.exec_day[dates[k + 1]] if k + 1 < len(dates) else None
        prices = price_eur.loc[e]
        book.settle_taxes(e.year, prices)
        book.cash += monthly
        book.contributions += monthly
        flows.append((e, -monthly))
        if sv.get("etf"):
            book.buy("ETF", book.cash, prices.get("ETF", np.nan), cost)
        else:
            sig = ctx.signals[d]
            sc, f, elig = sig["ra"], sig["f"], sig["elig"]
            hs = core.hold_state(sc["pct"], f["m12"], sig["q"]["data_ok"], sc["score_valid"], p)
            for s in book.holdings():
                cond = bool(hs.at[s, "H"] or hs.at[s, "data_problem"]) if s in hs.index else True
                hcount[s] = hcount[s] + 1 if cond else 0
                severe = bool(hs.at[s, "severe"]) if s in hs.index else False
                if cond and (hcount[s] >= p["confirm_months"] or severe):
                    book.sell(s, None, prices.get(s, np.nan), cost, e.year)
                    hcount[s] = 0
            cands = core.select_candidates(f, sc, elig, p["top_n"], p)
            if sv["top"] == 1:
                tp, _ = core.pick_top(cands, f, sc, elig, p)
                cands = [tp] if tp else cands[:1]
            cands = [c for c in cands if np.isfinite(prices.get(c, np.nan))]
            if cands and book.cash > 50:
                amt = book.cash / len(cands)
                for c in cands:
                    book.buy(c, amt, prices[c], cost)
        parts.append((e, monthly, _value_path(book, price_eur, e, nxt)))
    values = pd.concat([pt for _, _, pt in parts])
    # zeitgewichtete Rendite (ohne Einzahlungseffekt)
    twr = [1.0]
    prev = None
    flow_days = {e: m for e, m, _ in parts}
    for dt, val in values.items():
        if prev is None:
            prev = val
            continue
        base = prev
        flow = flow_days.get(dt, 0.0)
        r = (val - flow) / base - 1 if base > 0 else 0.0
        twr.append(twr[-1] * (1 + r))
        prev = val
    twr_s = pd.Series(twr, index=values.index)
    end_prices = price_eur.iloc[-1]
    final_after_tax = book.liquidation_value_after_tax(end_prices, price_eur.index[-1].year)
    final = float(values.iloc[-1])
    irr = xirr(flows + [(values.index[-1], final)])
    irr_tax = xirr(flows + [(values.index[-1], final_after_tax)])
    return {"values": values, "twr": twr_s, "book": book, "final": final, "final_after_tax": final_after_tax,
            "contributions": book.contributions, "irr": irr, "irr_after_tax": irr_tax}


# ---------------------------------------------------------------------- Auswertung
def _variant_report(name, vid, group, res, bench_monthly, years_recent, capital, res_tax=None, etf_tax=False):
    vals = res["values"]
    book: Book = res["book"]
    norm = vals / vals.iloc[0] * 100 if len(vals) else vals
    m = perf_metrics(vals)
    recent_start = vals.index[-1] - pd.DateOffset(years=years_recent) if len(vals) else None
    m_recent = perf_metrics(vals[vals.index >= recent_start]) if recent_start is not None else {}
    avg_val = vals.mean() if len(vals) else np.nan
    years = m.get("years") or np.nan
    m["trades"] = book.trades
    m["turnover"] = (book.traded_value / 2) / avg_val / years if avg_val and years and book.trades else (0.0 if group == "benchmark" else None)
    m["fees"] = book.fees
    m["spread_cost"] = book.spread_cost
    m["cash_share"] = res.get("cash_share")
    closed = book.closed_gains
    m["win_rate_trades"] = (sum(1 for g in closed if g > 0) / len(closed)) if closed and group == "strategy" else None
    mon = vals.groupby([vals.index.year, vals.index.month]).tail(1).pct_change().dropna()
    if bench_monthly is not None and len(mon):
        bm = bench_monthly.reindex(mon.index)
        both = pd.concat([mon, bm], axis=1).dropna()
        if len(both):
            m["hit_rate_months"] = float((both.iloc[:, 0] > both.iloc[:, 1]).mean())
    final_pre = float(vals.iloc[-1]) / float(vals.iloc[0]) * capital if len(vals) else None
    m["final_value"] = final_pre
    after = None
    if res_tax is not None:
        after = res_tax["after_tax_final"]
        m["taxes_paid"] = res_tax["book"].tax_paid
    elif etf_tax and final_pre:
        gain = final_pre - capital
        taxable = max(0.0, gain * (1 - TAX["etf_partial_exemption"]) - TAX["allowance"])
        after = final_pre - taxable * TAX["rate"]
        m["taxes_paid"] = 0.0
    if after is not None and years and after > 0:
        m["after_tax_final"] = after
        m["cagr_after_tax"] = (after / capital) ** (1 / years) - 1
    yearly = vals.groupby(vals.index.year).last()
    first = vals.iloc[0] if len(vals) else np.nan
    yr = (yearly / yearly.shift(1).fillna(first) - 1).to_dict()
    dd = (vals / vals.cummax() - 1)
    return {"id": vid, "name": name, "group": group, "metrics": _clean(m), "metrics_recent": _clean(m_recent),
            "curve": monthly_points(norm), "drawdown": monthly_points(dd * 100),
            "yearly": {str(k): _f(v) for k, v in yr.items()}}


def _f(x):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return x
    return None if not np.isfinite(x) else round(x, 6)


def _clean(d: dict) -> dict:
    return {k: (_f(v) if not isinstance(v, str) else v) for k, v in d.items()}


def run_backtest(ctx: Context, log=print) -> dict:
    t_start = pd.Timestamp.now()
    if len(ctx.dates) < 36:
        return {"available": False, "reason": "Zu wenige Monate mit ausreichender Kurshistorie (< 36)."}
    ctx.compute_signals()
    capital = BACKTEST["start_capital"]
    cost_real = COST_SCENARIOS["realistisch"]
    rec_y = BACKTEST["recent_years"]
    variants_out = []
    # Maßstab: gleichgewichtetes Universum (monatlich neu gewichtet, ohne Kosten und Steuern)
    ew = run_lump_sum(ctx, {"id": "ew", "signal": "ra", "top": 100000, "rules": "strict"},
                      COST_SCENARIOS["brutto"], capital)
    ew_vals = ew["values"]
    ew_month = ew_vals.groupby([ew_vals.index.year, ew_vals.index.month]).tail(1).pct_change().dropna()
    variants_out.append(_variant_report("Universum gleichgewichtet (ohne Kosten)", "ew_universe", "benchmark",
                                        ew, None, rec_y, capital))
    bench_series = {}
    for key, b in ctx.benchmarks.items():
        s = b["eur"].dropna()
        s = s[s.index >= ctx.exec_day[ctx.dates[0]]]
        if len(s) < 250:
            continue
        bench_series[key] = s
        res = {"values": s / s.iloc[0] * capital, "book": Book(), "cash_share": 0.0}
        variants_out.append(_variant_report(b["name"] + " (ETF, inkl. Fondskosten)", key, "benchmark", res,
                                            ew_month, rec_y, capital, etf_tax=True))
    results = {}
    for v in BACKTEST_VARIANTS:
        log(f"[backtest] Variante {v['id']}")
        pre = run_lump_sum(ctx, v, cost_real, capital, taxes=False)
        taxed = run_lump_sum(ctx, v, cost_real, capital, taxes=True)
        results[v["id"]] = pre
        variants_out.append(_variant_report(v["name"], v["id"], "strategy", pre, ew_month, rec_y, capital, taxed))
    # Kostensensitivität (vor Steuern)
    sens = []
    for vid in ("ra_top10", "app_top10", "app_top1"):
        v = next(x for x in BACKTEST_VARIANTS if x["id"] == vid)
        row = {"id": vid, "name": v["name"]}
        for ck, cv in COST_SCENARIOS.items():
            res = results[vid] if ck == "realistisch" else run_lump_sum(ctx, v, cv, capital)
            mm = perf_metrics(res["values"])
            row[ck] = {"cagr": _f(mm.get("cagr")), "max_drawdown": _f(mm.get("max_drawdown")), "label": cv["label"]}
        sens.append(row)
    # Sparpläne (ab Verfügbarkeit des MSCI-World-ETF, sonst ab Beginn)
    etf = bench_series.get("msci_world_eur")
    sp_start = etf.index[0] if etf is not None else ctx.exec_day[ctx.dates[0]]
    savings = []
    for sv in SAVINGS_VARIANTS:
        pre = run_savings(ctx, sv, cost_real, BACKTEST["monthly_savings"], etf, sp_start, taxes=False)
        taxed = run_savings(ctx, sv, cost_real, BACKTEST["monthly_savings"], etf, sp_start, taxes=True)
        if pre is None or taxed is None:
            continue
        m = perf_metrics(pre["twr"])
        savings.append({"id": sv["id"], "name": sv["name"], "contributions": _f(pre["contributions"]),
                        "final": _f(pre["final"]), "final_after_tax": _f(taxed["final_after_tax"]),
                        "irr": _f(pre["irr"]), "irr_after_tax": _f(taxed["irr_after_tax"]),
                        "twr_cagr": _f(m.get("cagr")), "max_drawdown": _f(m.get("max_drawdown")),
                        "volatility": _f(m.get("volatility")), "trades": pre["book"].trades,
                        "taxes_paid": _f(taxed["book"].tax_paid), "start": sp_start.strftime("%Y-%m-%d"),
                        "curve": monthly_points(pre["values"])})
    series = {"ew_universe": ew_vals, **{k: r["values"] for k, r in results.items()},
              **{k: s for k, s in bench_series.items()}}
    regimes = _regimes(ctx, series, ew_month)
    n_elig = {d.strftime("%Y-%m-%d"): ctx.signals[d]["n_elig"] for d in ctx.dates[::12]}
    shocks = [d.strftime("%Y-%m") for d in ctx.dates if ctx.signals[d]["vol_shock"]]
    warnings = [
        "Survivorship Bias: Das Universum besteht aus HEUTIGEN MSCI-World-Mitgliedern. Firmen, die "
        "zwischenzeitlich ausgeschieden, übernommen oder pleite sind, fehlen. Die Renditen sind daher "
        "wahrscheinlich ZU HOCH. Der Vergleich mit dem gleichgewichteten Universum (gleiche Verzerrung) ist fairer "
        "als der Vergleich mit dem echten MSCI-World-ETF.",
        "Look-ahead durch Universumsauswahl: Die heutige Indexzugehörigkeit war früher nicht bekannt.",
        "ETF-Vergleiche beginnen erst mit Auflage des jeweiligen ETFs und enthalten Fondskosten.",
        "Dividenden sind über bereinigte Kurse reinvestiert; Quellensteuern, Vorabpauschale und "
        "Dividendenbesteuerung im Jahr der Zahlung sind vereinfacht nicht modelliert.",
        "Jede Variante nutzt den vollen Sparerpauschbetrag (1.000 €/Jahr) – real teilen sich alle Anlagen einen.",
        "Sharpe Ratio vereinfacht mit 0 % risikofreiem Zins berechnet.",
        "Kurse von Yahoo Finance (inoffiziell). Historische Fehler in Einzelkursen sind möglich; "
        "unplausible Kurssprünge werden ausgeschlossen.",
    ]
    log(f"[backtest] fertig in {(pd.Timestamp.now() - t_start).total_seconds():.0f}s")
    return {
        "available": True,
        "period": {"start": ctx.exec_day[ctx.dates[0]].strftime("%Y-%m-%d"),
                   "end": ctx.price_eur.index[-1].strftime("%Y-%m-%d"), "months": len(ctx.dates)},
        "assumptions": {"start_capital": capital, "monthly_savings": BACKTEST["monthly_savings"],
                        "costs": COST_SCENARIOS, "default_cost": "realistisch", "tax": TAX,
                        "execution": "Signal am Monatsende, Handel zum Schlusskurs des nächsten Handelstags",
                        "rebalancing": "monatlich", "market_proxy": "gleichgewichtetes Universum (Landeswährungen)",
                        "recent_years": rec_y},
        "variants": variants_out,
        "cost_sensitivity": sens,
        "savings": savings,
        "regimes": regimes,
        "eligible_count": n_elig,
        "vol_shock_months": shocks,
        "warnings": warnings,
    }


def _regimes(ctx: Context, series: dict, ew_month: pd.Series) -> dict:
    out = {"periods": [], "bull_bear": {}}
    for name, a, b in NAMED_PERIODS:
        a, b = pd.Timestamp(a), pd.Timestamp(b)
        row = {"name": name, "start": a.strftime("%Y-%m-%d"), "end": b.strftime("%Y-%m-%d"), "returns": {}}
        for k, s in series.items():
            sub = s[(s.index >= a) & (s.index <= b)]
            if len(sub) > 5 and sub.index[0] - a < pd.Timedelta(days=10):
                row["returns"][k] = _f(sub.iloc[-1] / sub.iloc[0] - 1)
        if row["returns"]:
            out["periods"].append(row)
    ew12 = (1 + ew_month).rolling(12).apply(np.prod, raw=True) - 1
    state = ew12.shift(1)
    for k, s in series.items():
        mon = s.groupby([s.index.year, s.index.month]).tail(1).pct_change().dropna()
        st = state.reindex(mon.index)
        bull = mon[st > 0]
        bear = mon[st <= 0]
        out["bull_bear"][k] = {"bull_avg_month": _f(bull.mean()) if len(bull) else None,
                               "bear_avg_month": _f(bear.mean()) if len(bear) else None,
                               "bull_months": int(len(bull)), "bear_months": int(len(bear))}
    return out
