import pandas as pd

from pipeline import tiingo


def test_parse_prices_split_adjusts_close():
    rows = [{"date": f"2020-01-{d:02d}T00:00:00.000Z", "close": 100.0 if d < 15 else 50.0, "adjClose": 50.0,
             "volume": 1, "splitFactor": 2.0 if d == 15 else 1.0} for d in range(1, 29)]
    df = tiingo.parse_prices(rows)
    assert abs(df["close"].iloc[0] - 50.0) < 1e-9 and abs(df["close"].iloc[-1] - 50.0) < 1e-9


class _R:
    def __init__(self, code, js=None):
        self.status_code, self._js = code, js
        self.ok = code == 200

    def json(self):
        return self._js


class _S:
    def __init__(self):
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        if "/lehmq/" in url or "/leh/" in url:
            return _R(200, [{"date": f"2005-{m:02d}-01", "close": 50.0, "adjClose": 50.0, "volume": 1} for m in range(1, 13)]
                      + [{"date": f"2006-{m:02d}-01", "close": 60.0, "adjClose": 60.0, "volume": 1} for m in range(1, 13)])
        return _R(404)


def test_fill_missing_budget_and_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "x")
    s = _S()
    frames, info = tiingo.fill_missing(["LEH", "GONE", "SAP.DE"], tmp_path, pd.Timestamp("2026-11-28"), log=lambda *_: None,
                                       session=s, sleep_s=0)
    assert set(frames) == {"LEH"} and info["fetched"] == 1 and info["not_found"] == 1
    assert len(s.calls) == 2                                  # SAP.DE wird nicht bei Tiingo gesucht
    # zweiter Lauf: nichts neu laden, aus dem Archiv lesen
    s2 = _S()
    frames2, _ = tiingo.fill_missing(["LEH", "GONE"], tmp_path, pd.Timestamp("2026-11-29"), log=lambda *_: None,
                                     session=s2, sleep_s=0)
    assert set(frames2) == {"LEH"} and s2.calls == []
    monkeypatch.delenv("TIINGO_API_KEY")
    frames3, info3 = tiingo.fill_missing(["NEW1"], tmp_path, pd.Timestamp("2026-11-29"), log=lambda *_: None, session=_S())
    assert frames3 == {} and info3["key"] is False


def test_audit_anomalies():
    from pipeline import audit
    sim = {"points": ["2020-01-02", "2020-02-03", "2020-03-02"], "syms": ["A", "B"], "names": ["A", "B"],
           "px": [[10, 40, 41], [10, 11, 1]]}
    a = audit.anomalies(sim)
    assert [x["symbol"] for x in a] == ["A", "B"] and a[0]["return"] == 3.0


def test_bench_lines_sp500_uses_real_etf_with_checked_backfill():
    import numpy as np
    import pandas as pd
    from pipeline.simulator import bench_lines
    idx = pd.bdate_range("2004-01-01", "2026-10-30")
    rng = np.random.default_rng(1)
    tr = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(idx)))), index=idx)
    etf_idx = idx[idx >= "2010-05-19"]
    etf = tr.loc[etf_idx] * 0.37 * np.exp(-0.0028 * ((etf_idx - etf_idx[0]).days / 365.25))   # Quellensteuer-Effekt
    points = list(pd.date_range("2005-01-31", "2026-10-31", freq="ME"))
    out = bench_lines({"sp500_tr": {"name": "Index", "eur": tr}, "sp500_eur": {"name": "iShares Core S&P 500", "eur": etf}},
                      points, None, log=lambda *_: None)
    sp = out["sp500"]
    assert sp["name"] == "iShares Core S&P 500"
    assert sp["extended"]["symbol"] == "^SP500TR" and sp["start"] < "2010-01-01"
    # ab ETF-Start exakt die ETF-Renditen (Verkettung, keine Schätzung)
    k = [i for i, d in enumerate(points) if d >= pd.Timestamp("2012-01-01")]
    a, b = k[0], k[-1]
    e = etf.reindex(etf.index.union(pd.DatetimeIndex(points))).ffill().reindex(points)
    assert abs(sp["px"][b] / sp["px"][a] - e.iloc[b] / e.iloc[a]) < 1e-3
    # ohne ETF-Kurse: Index abzgl. Kosten
    out2 = bench_lines({"sp500_tr": {"name": "Index", "eur": tr}}, points, None, log=lambda *_: None)
    assert out2["sp500"]["name"] == "Index" and "extended" not in out2["sp500"]


def test_etf_crosscheck(tmp_path):
    import json
    import pandas as pd
    from pipeline.audit import etf_crosscheck
    pts = list(pd.date_range("2015-01-30", "2020-12-31", freq="ME") + pd.Timedelta(days=1))   # Monatsanfang
    fx = pd.DataFrame({"USD": 1.1}, index=pd.bdate_range("2014-12-01", "2021-01-31"))
    px = [100 * 1.01 ** i for i in range(len(pts))]
    (tmp_path / "audit").mkdir()
    ref = {(d - pd.Timedelta(days=1)).strftime("%Y-%m"): 110 * 1.01 ** i for i, d in enumerate(pts)}  # Monatsende davor
    (tmp_path / "audit" / "tiingo-reference.json").write_text(json.dumps({"IVV": ref}))
    res = etf_crosscheck({"points": [d.strftime("%Y-%m-%d") for d in pts],
                          "bench": {"sp500": {"name": "SXR8", "px": px}}}, fx, tmp_path)
    assert len(res) == 1 and res[0]["ok"] is True and abs(res[0]["diff_pa_pct"]) < 0.01
    assert res[0]["median_abs_month_diff_pct"] < 0.01
    assert abs(res[0]["cagr_ours_pct"] - (1.01 ** 12 - 1) * 100) < 0.02
