import json

import numpy as np
import pandas as pd

from pipeline.simulator import build_sim_data
from pipeline import backtest as bt
from pipeline import core


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



def test_sim_data_shapes_and_no_lookahead():
    ctx, sectors = _ctx(n=30, start="2003-01-02", end="2009-12-31")
    meta = pd.DataFrame({"name": [f"N {s}" for s in sectors.index], "sector": sectors.values}, index=sectors.index)
    idx = ctx.price_eur.index
    world = pd.Series(np.linspace(10, 20, len(idx)), index=idx)
    bench = {"msci_world_eur": {"name": "World", "eur": world[world.index >= "2005-01-03"]},
             "sp500_tr": {"name": "SP", "eur": world * 2}}
    d = build_sim_data(ctx, meta, bench, idx[-1], log=lambda *a: None)
    K = len(d["signal_dates"])
    assert len(d["rank"]) == K and len(d["hold"]) == K and len(d["cand"]) == K and len(d["s2"]) == K
    assert len(d["points"]) in (K, K + 1)
    assert all(len(h) == len(d["syms"]) for h in d["hold"])
    assert all(len(p) == len(d["points"]) for p in d["px"])
    assert set("".join(d["hold"])) <= set("0123")
    # Stage-2-Kursteil nur aus den Top 10 der Kandidaten
    for k in range(K):
        assert set(d["s2"][k]) <= set(d["cand"][k][:10])
    # Ausführungstag liegt nach dem Signal (kein Blick in die Zukunft)
    assert all(p > s for s, p in zip(d["signal_dates"], d["points"]))
    assert d["bench"]["msci_world"]["px"][0] is None      # World erst ab 2005
    assert d["bench"]["sp500"]["px"][0] is not None
    json.dumps(d, allow_nan=False)


def test_chain_backfill_extends_only_matching_series():
    from pipeline.simulator import chain_backfill
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2005-01-03", "2012-12-31")
    r = rng.normal(0.0003, 0.01, len(idx))
    old = pd.Series(100 * np.exp(np.cumsum(r)), index=idx)
    main = (old.loc["2009-09-25":] * 0.37)
    noise = pd.Series(50 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(idx)))), index=idx)
    out, info = chain_backfill(main, [{"symbol": "X", "name": "X", "eur": noise}, {"symbol": "OLD", "name": "Alt", "eur": old}], log=lambda *_: None)
    assert info["symbol"] == "OLD" and out.index[0] == idx[0]
    assert abs(out.loc["2009-09-25"] - main.iloc[0]) < 1e-9
    assert np.allclose(out.pct_change().loc["2006"].dropna(), old.pct_change().loc["2006"].dropna())
    out2, info2 = chain_backfill(main, [{"symbol": "X", "name": "X", "eur": noise}], log=lambda *_: None)
    assert info2 is None and out2.index[0] == main.index[0]
