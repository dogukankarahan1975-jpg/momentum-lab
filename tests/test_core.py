import math

import numpy as np
import pandas as pd
import pytest

from pipeline import core
from pipeline.config import METHODOLOGY


def make_panel(prices: dict, start="2019-01-01", end="2023-06-30", volume=1e6):
    idx = pd.bdate_range(start, end)
    adj = pd.DataFrame({k: v(idx) if callable(v) else v for k, v in prices.items()}, index=idx)
    vol = pd.DataFrame(volume, index=idx, columns=adj.columns)
    return core.prepare_panel(adj, adj.copy(), vol), idx


def test_price_at_window():
    idx = pd.bdate_range("2023-01-02", "2023-01-31")
    df = pd.DataFrame({"A": np.arange(len(idx), dtype=float)}, index=idx)
    df.loc["2023-01-20":"2023-01-27", "A"] = np.nan
    v = core.price_at(df, pd.Timestamp("2023-01-27"), 12)
    assert v["A"] == df.loc["2023-01-19", "A"]
    v2 = core.price_at(df, pd.Timestamp("2023-01-27"), 5)
    assert np.isnan(v2["A"])


def test_momentum_returns_exact():
    g = 0.30
    panel, idx = make_panel({"A": lambda i: 100 * np.exp(g * (i - i[0]).days / 365.0)})
    asof = idx[-1]
    f = core.features_at(panel, asof)

    def p(t):
        return core.price_at(panel.adj, t, 12)["A"]
    t1 = asof - pd.DateOffset(months=1)
    exp_m12 = p(t1) / p(asof - pd.DateOffset(months=13)) - 1
    exp_m6 = p(t1) / p(asof - pd.DateOffset(months=7)) - 1
    assert f.at["A", "m12"] == pytest.approx(exp_m12)
    assert f.at["A", "m6"] == pytest.approx(exp_m6)
    assert f.at["A", "m12"] == pytest.approx(math.exp(g * 365 / 365) - 1, rel=0.02)
    assert f.at["A", "above_ma200"] == True  # noqa: E712
    assert f.at["A", "dd_52w"] == pytest.approx(0.0)


def test_weekly_volatility_known():
    idx = pd.bdate_range("2019-01-01", "2023-06-30")
    wk = pd.Series(np.where(np.arange(len(idx)) // 5 % 2 == 0, 1.0, 1.0), index=idx)
    # wöchentliche Renditen abwechselnd +2 % / -2 %: Kurs springt freitags
    fridays = idx[idx.weekday == 4]
    level = 100.0
    vals = []
    sign = 1
    fri_set = set(fridays)
    for d in idx:
        if d in fri_set:
            level *= (1 + 0.02 * sign)
            sign *= -1
        vals.append(level)
    panel, _ = make_panel({"A": pd.Series(vals, index=idx).values}, "2019-01-01", "2023-06-30")
    f = core.features_at(panel, idx[-1])
    r = np.array([0.02, -0.02] * 78)
    exp = np.std([(1.02 if k % 2 == 0 else 0.98) - 1 for k in range(156)], ddof=1) * math.sqrt(52)
    assert f.at["A", "vol"] == pytest.approx(exp, rel=0.05)
    assert wk is not None and r is not None


def test_standardize_no_clipping_and_robust():
    rng = np.random.default_rng(1)
    x = pd.Series(rng.normal(0, 1, 500))
    x.iloc[0] = 50.0  # Ausreißer
    z = core.standardize(x, pd.Series(True, index=x.index), 3.0)
    assert z.iloc[0] > 20  # nicht gekappt
    assert abs(z.iloc[1:].mean()) < 0.15
    assert 0.85 < z.iloc[1:].std() < 1.15  # Skala kaum vom Ausreißer verzerrt


def _feat(n=40, seed=0):
    rng = np.random.default_rng(seed)
    idx = [f"S{i:02d}" for i in range(n)]
    f = pd.DataFrame({"m6": rng.normal(0.05, 0.2, n), "m12": rng.normal(0.1, 0.3, n),
                      "vol": rng.uniform(0.15, 0.5, n)}, index=idx)
    return f


def test_scores_rank_and_shadow_pct():
    f = _feat()
    elig = pd.Series(True, index=f.index)
    elig.iloc[3] = False
    s = core.scores_at(f, elig, "ra")
    ranked = s["rank"].dropna()
    assert len(ranked) == 39 and ranked.min() == 1 and ranked.max() == 39
    assert np.isnan(s.at["S03", "rank"]) and 0 <= s.at["S03", "pct"] <= 1
    best = s["Z"][elig].idxmax()
    assert s.at[best, "rank"] == 1 and s.at[best, "pct"] == 0
    # Schatten-Perzentil konsistent: Anzahl besserer zulässiger Scores / (n-1)
    better = (s["Z"][elig] > s.at["S03", "Z"]).sum()
    assert s.at["S03", "pct"] == pytest.approx(better / 38)


def test_select_candidates_rules():
    f = _feat(60, 2)
    elig = pd.Series(True, index=f.index)
    s = core.scores_at(f, elig, "ra")
    cands = core.select_candidates(f, s, elig, 10)
    assert len(cands) <= 10
    for c in cands:
        assert f.at[c, "m6"] > 0 and f.at[c, "m12"] > 0
        assert s.at[c, "pct"] <= METHODOLOGY["candidate_max_pct"]
    assert cands == sorted(cands, key=lambda c: s.at[c, "rank"])
    # Bärenmarkt: alle negativ => keine Kandidaten
    f2 = f.copy()
    f2["m6"] = -abs(f2["m6"]) - 0.01
    s2 = core.scores_at(f2, elig, "ra")
    assert core.select_candidates(f2, s2, elig, 10) == []


def test_pick_top_requires_all_checks():
    f = pd.DataFrame({"m6": [0.5, 0.4, 0.1] + [0.0] * 20, "m12": [0.2, 0.9, 0.1] + [0.0] * 20,
                      "vol": [0.25, 0.25, 0.3] + [0.3] * 20}, index=[f"S{i}" for i in range(23)])
    elig = pd.Series(True, index=f.index)
    s = core.scores_at(f, elig, "ra")
    cands = ["S0", "S1", "S2"]
    tp, info = core.pick_top(cands, f, s, elig, METHODOLOGY)
    assert tp in cands
    assert all(info["checks"][tp].values())
    tp2, _ = core.pick_top(cands, f, s, elig, METHODOLOGY, verified=pd.Series({"S0": False, "S1": False, "S2": False}))
    assert tp2 is None


def test_hold_state():
    pct = pd.Series({"A": 0.05, "B": 0.25, "C": 0.6, "D": 0.1, "E": np.nan})
    m12 = pd.Series({"A": 0.3, "B": 0.2, "C": 0.1, "D": -0.05, "E": 0.1})
    ok = pd.Series({"A": True, "B": True, "C": True, "D": True, "E": False})
    valid = pd.Series({"A": True, "B": True, "C": True, "D": True, "E": False})
    h = core.hold_state(pct, m12, ok, valid)
    assert list(h["H"]) == [False, True, True, True, True]
    assert list(h["severe"]) == [False, False, True, False, False]
    assert h.at["E", "data_problem"]


def test_quality_flags():
    idx = pd.bdate_range("2020-01-01", "2023-06-30")
    n = len(idx)
    base = 50 * np.exp(np.cumsum(np.full(n, 0.0003)))
    adj = pd.DataFrame({k: base.copy() for k in "ABCDEFGH"}, index=idx)
    close = adj.copy()
    vol = pd.DataFrame(1e6, index=idx, columns=adj.columns)
    adj.loc[idx[-15]:, "B"] = np.nan          # veraltet
    close.loc[idx[-15]:, "B"] = np.nan
    adj.loc[:idx[-300], "C"] = np.nan         # kurze Historie
    close.loc[:idx[-300], "C"] = np.nan
    adj.iloc[-50:, adj.columns.get_loc("D")] *= 3    # Sprung
    close.iloc[-50:, close.columns.get_loc("D")] *= 3
    vol.iloc[-60:, vol.columns.get_loc("E")] = 0     # kein Umsatz
    adj["F"] *= 0.01                                  # Penny
    close["F"] *= 0.01
    vol["G"] = 1000                                   # illiquide
    panel = core.prepare_panel(adj, close, vol)
    cur = pd.Series({k: "EUR" for k in "ABCDEFG"} | {"H": "XXX"})
    q = core.quality_at(panel, idx[-1], cur, pd.Series({"USD": 1.1}), METHODOLOGY,
                        pd.Series({"A": 0.001, "B": np.nan}), duplicates={"A"})
    r = q["reasons"]
    assert "duplicate" in r["A"] and not q.at["A", "eligible"]
    assert "stale" in r["B"] and not q.at["B", "data_ok"]
    assert "short_history" in r["C"] and q.at["C", "data_ok"]
    assert "jump" in r["D"]
    assert "zero_volume" in r["E"]
    assert "penny" in r["F"]
    assert "liquidity" in r["G"]
    assert "currency" in r["H"] and not q.at["H", "data_ok"]


def test_month_end_dates_and_prev():
    idx = pd.bdate_range("2023-01-01", "2023-04-15")
    me = core.month_end_dates(idx, pd.Timestamp("2023-01-01"), pd.Timestamp("2023-03-31"))
    assert [d.strftime("%Y-%m-%d") for d in me] == ["2023-01-31", "2023-02-28", "2023-03-31"]
    assert core.last_trading_day_of_prev_month(idx, pd.Timestamp("2023-04-14")) == pd.Timestamp("2023-03-31")
