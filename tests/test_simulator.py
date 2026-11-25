import json

import numpy as np
import pandas as pd

from pipeline.simulator import build_sim_data
from tests.test_autopilot import _ctx


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
