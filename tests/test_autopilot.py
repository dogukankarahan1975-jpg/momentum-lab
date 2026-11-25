from datetime import date

import numpy as np
import pandas as pd
import pytest

from pipeline import autopilot as ap
from pipeline import backtest as bt
from pipeline import core

COST0 = {"fee": 0.0, "spread": 0.0}


def test_grid_is_fixed_and_complete():
    v = ap.variants()
    assert len(v) == 12
    assert len({x["id"] for x in v}) == 12
    assert ap.cap_count(10, 0.30) == 3
    assert ap.cap_count(15, 0.30) == 4
    assert ap.cap_count(10, None) is None


def test_pick_buys_respects_sector_cap_and_holdings():
    sectors = pd.Series({"A": "IT", "B": "IT", "C": "IT", "D": "Energie", "E": "IT", "F": "Finanzen"})
    picks, skipped = ap.pick_buys(["A", "B", "C", "D", "E", "F"], held=["A"], free=3, sectors=sectors, cap_n=2)
    assert picks == ["B", "D", "F"]           # C und E: IT schon 2x (A gehalten + B)
    assert [s["symbol"] for s in skipped] == ["C", "E"]
    picks2, _ = ap.pick_buys(["A", "B", "C"], held=[], free=2, sectors=sectors, cap_n=None)
    assert picks2 == ["A", "B"]


def test_next_plan_date():
    assert ap.next_plan_date(date(2026, 11, 25)) == date(2026, 12, 2)   # 1.12. Di -> Plan ab Mi
    assert ap.next_plan_date(date(2026, 12, 10)) == date(2027, 1, 4)    # 1.1. Fr -> Plan ab Mo


def _ctx(seed=7, n=40, start="2000-01-03", end="2016-12-30", crash=True):
    idx = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    cols = [f"S{i:02d}" for i in range(n)]
    rets = rng.normal(0.0003, 0.012, (len(idx), n))
    rets[:, :4] += 0.0008
    if crash:  # gemeinsamer Markteinbruch 2008
        m = (idx >= "2008-06-01") & (idx <= "2009-02-28")
        rets[m, :] -= 0.004
    adj = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=idx, columns=cols)
    vol = pd.DataFrame(1e6, index=idx, columns=cols)
    panel = core.prepare_panel(adj, adj.copy(), vol)
    fx = pd.DataFrame({"USD": 1.0}, index=idx)
    cur = pd.Series("EUR", index=cols)
    ctx = bt.Context(panel, cur, fx, set(), idx[-1], {}, log=lambda *a: None)
    ctx.compute_signals()
    sectors = pd.Series([["IT", "Energie", "Finanzen", "Gesundheit"][i % 4] for i in range(n)], index=cols)
    sectors.iloc[:4] = "IT"   # alle Gewinner in einer Branche
    return ctx, sectors


@pytest.fixture(scope="module")
def ctx_sec():
    return _ctx()


def test_simulate_sector_cap_and_hard_filter(ctx_sec):
    ctx, sectors = ctx_sec
    v = {"id": "t", "n": 6, "sector_cap": 0.34, "market": "none"}
    res = ap.simulate(ctx, v, sectors, COST0, 10_000)
    held = res["book"].holdings()
    assert len(held) <= 6
    assert sum(1 for s in held if sectors[s] == "IT") <= ap.cap_count(6, 0.34)
    hard = ap.simulate(ctx, {"id": "h", "n": 6, "sector_cap": None, "market": "hard"}, sectors, COST0, 10_000)
    # Im harten Filter gibt es Monate komplett in Cash
    bear = [d for d in ctx.dates if not ctx.signals[d]["market_bull"]]
    assert bear, "synthetischer Crash muss Abwärtstrend erzeugen"
    assert hard["bear_months"] == len(bear)


def test_savings_contributions(ctx_sec):
    ctx, sectors = ctx_sec
    v = {"id": "s", "n": 5, "sector_cap": None, "market": "none"}
    res = ap.simulate(ctx, v, sectors, COST0, 0.0, monthly=500.0, start=pd.Timestamp("2012-01-01"))
    assert res["book"].contributions == pytest.approx(500.0 * res["months"])


def test_selection_uses_only_insample_and_reports_oos(ctx_sec):
    ctx, sectors = ctx_sec
    out = ap.run_autopilot_backtest(ctx, sectors, log=lambda *a: None)
    assert out["available"]
    assert len(out["grid"]) == 12
    chosen = next(g for g in out["grid"] if g["chosen"])
    assert chosen["insample"]["end"] <= "2015-01-10"     # Lernzeitraum endet 2014
    ok = [g for g in out["grid"] if g["meets_limit"]]
    if ok:
        assert chosen["insample"]["cagr_after_tax"] == max(g["insample"]["cagr_after_tax"] for g in ok)
    assert out["oos"][out["chosen"]]["start"] >= "2015-01-01"


def test_live_plan_codes(ctx_sec):
    ctx, sectors = ctx_sec
    rule = ap.default_rule()
    names = pd.Series({s: f"Name {s}" for s in sectors.index})
    plan = ap.live_plan(ctx, rule, sectors, names, date(2016, 12, 30))
    assert plan["available"]
    assert set(c for c, _ in plan["status"].values()) <= {"H", "W", "V", "P"}
    assert plan["buy_list"][0]["rank"] == 1
    assert plan["signal_date"] < "2016-12-30"
    assert plan["action"] in ("NORMAL", "KEINE_KAEUFE", "PARKEN")
