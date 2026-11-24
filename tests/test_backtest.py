import numpy as np
import pandas as pd
import pytest

from pipeline import backtest as bt
from pipeline import core
from pipeline.config import TAX


COST0 = {"fee": 0.0, "spread": 0.0}
COST1 = {"fee": 1.0, "spread": 0.002}


def test_book_fifo_costs_and_taxes():
    b = bt.Book(cash=10_000)
    b.buy("A", 5_000, 50.0, COST1)          # Gebühr 1 €, Spread 0,2 %
    assert b.shares("A") == pytest.approx((5_000 - 1) * 0.998 / 50)
    assert b.cash == pytest.approx(5_000)
    b.buy("A", 5_000, 100.0, COST0)
    sh_first = (5_000 - 1) * 0.998 / 50
    b.sell("A", sh_first, 120.0, COST0, 2024)  # FIFO: erste Tranche
    assert b.realized[2024] == pytest.approx(sh_first * 120 - 5_000)
    gain = b.realized[2024]
    b.settle_taxes(2025, pd.Series({"A": 120.0}))
    assert b.tax_paid == pytest.approx((gain - TAX["allowance"]) * TAX["rate"])
    # Verlustvortrag
    b2 = bt.Book(cash=1_000)
    b2.realized[2023] = -500
    b2.realized[2024] = 2_000
    b2.taxed_through = 2022
    b2.settle_taxes(2025, pd.Series(dtype=float))
    assert b2.tax_paid == pytest.approx((2_000 - 500 - TAX["allowance"]) * TAX["rate"])


def test_book_no_taxes_when_disabled():
    b = bt.Book(cash=1_000, tax_on=False)
    b.realized[2024] = 50_000
    b.settle_taxes(2026, pd.Series(dtype=float))
    assert b.tax_paid == 0


def test_liquidation_tax_etf_partial_exemption():
    b = bt.Book(cash=0.0, etf_exemption=0.3)
    b.cash = 10_000
    b.buy("ETF", 10_000, 100.0, COST0)
    after = b.liquidation_value_after_tax(pd.Series({"ETF": 200.0}), 2026)
    gain = 10_000
    assert after == pytest.approx(20_000 - max(0, gain * 0.7 - TAX["allowance"]) * TAX["rate"])


def test_xirr_simple():
    d0 = pd.Timestamp("2020-01-01")
    r = bt.xirr([(d0, -1000.0), (d0 + pd.Timedelta(days=365.25 * 2), 1210.0)])
    assert r == pytest.approx(0.10, abs=1e-4)


def test_backtest_picks_persistent_winner():
    """Synthetischer Markt: eine Aktie mit dauerhaft hoher risikoadjustierter Rendite muss Top 1 sein."""
    idx = pd.bdate_range("2000-01-03", "2009-12-31")
    rng = np.random.default_rng(5)
    n = 30
    cols = [f"S{i:02d}" for i in range(n)]
    rets = rng.normal(0.0002, 0.012, (len(idx), n))
    rets[:, 0] = rng.normal(0.0012, 0.008, len(idx))  # Gewinner
    adj = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=idx, columns=cols)
    vol = pd.DataFrame(1e6, index=idx, columns=cols)
    panel = core.prepare_panel(adj, adj.copy(), vol)
    fx = pd.DataFrame({"USD": 1.0}, index=idx)
    cur = pd.Series("EUR", index=cols)
    ctx = bt.Context(panel, cur, fx, set(), idx[-1], {}, log=lambda *a: None)
    ctx.compute_signals()
    res = bt.run_lump_sum(ctx, {"id": "t", "signal": "ra", "top": 1, "rules": "strict"}, COST0, 10_000)
    held_last = res["book"].holdings()
    assert held_last == ["S00"]
    assert res["values"].iloc[-1] > 10_000
    # Kosten senken das Ergebnis
    res_cost = bt.run_lump_sum(ctx, {"id": "t", "signal": "ra", "top": 10, "rules": "strict"}, COST1, 10_000)
    res_free = bt.run_lump_sum(ctx, {"id": "t", "signal": "ra", "top": 10, "rules": "strict"}, COST0, 10_000)
    assert res_cost["values"].iloc[-1] < res_free["values"].iloc[-1]
    # App-Regeln handeln seltener als strikte Monatsumschichtung
    res_app = bt.run_lump_sum(ctx, {"id": "a", "signal": "ra", "top": 10, "rules": "app"}, COST1, 10_000)
    assert res_app["book"].trades < res_cost["book"].trades
    # Kein Look-ahead: Ausführungstag liegt immer nach dem Signaltag
    assert all(ctx.exec_day[d] > d for d in ctx.dates)
