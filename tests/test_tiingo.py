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
