"""Historische Indexzusammensetzung (point in time)."""
import re

import numpy as np
import pandas as pd

from pipeline import pit

HEAD = "Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Price,Location,Exchange,Currency,FX Rate,Market Currency,Accrual Date"


def fake_csv(date: pd.Timestamp, members: list[tuple[str, float]], n_fill: int = 1100) -> str:
    lines = ["iShares MSCI ACWI ETF", f'Fund Holdings as of,"{date.strftime("%b %d, %Y")}"', "", HEAD]
    for t, p in members:
        lines.append(f'"{t}","{t} CORP","Information Technology","Equity","1.00","0.10","1.00","1.00","{p}","United States","NASDAQ","USD","1.00","USD","-"')
    for i in range(n_fill):
        lines.append(f'"F{i:04d}","FILL {i} INC","Financials","Equity","1.00","0.01","1.00","1.00","10.00","United States","New York Stock Exchange Inc.","USD","1.00","USD","-"')
    return "\n".join(lines)


def test_history_download_coverage_and_validation(tmp_path):
    today = pd.Timestamp("2008-12-15")
    calls = []

    def http_get(url):
        d = pd.Timestamp(re.search(r"asOfDate=(\d{8})", url).group(1))
        calls.append(d)
        members = [("AAA", 100.0 * (1.01 ** d.month)), ("BBB", 50.0)] if d.month < 8 else [("AAA", 100.0 * (1.01 ** d.month)), ("CCC", 20.0)]
        return fake_csv(d, members)

    path = tmp_path / "history-acwi.json.gz"
    h, info = pit.update_history(http_get, path, "acwi", today, log=lambda *_: None)
    assert info["coverage_from"] == "2008-04" and info["coverage_to"] == "2008-11" and info["coverage_months"] == 8
    months = pit.month_list("2008-04", today)
    # Kurse: AAA passt (Faktor konstant), CCC ist ein anderer Wert unter gleichem Ticker (passt nicht)
    idx = pd.bdate_range("2008-01-01", "2008-12-31")
    aaa = pd.Series([100.0 * (1.01 ** d.month) for d in idx], index=idx)
    ccc = pd.Series(np.linspace(5, 500, len(idx)), index=idx)
    valid, stats = pit.validate(h, {"AAA": aaa, "CCC": ccc, "BBB": pd.Series(dtype=float)})
    assert "AAA" in valid and "CCC" not in valid and "BBB" not in valid
    assert stats["mismatch"] >= 1 and stats["no_prices"] >= 1
    mem = pit.membership(h, valid | {"BBB"}, months)
    assert "BBB" in mem["2008-05"] and "BBB" not in mem["2008-09"]
    # zweiter Lauf: nichts mehr herunterzuladen
    calls.clear()
    pit.update_history(http_get, path, "acwi", today, log=lambda *_: None)
    assert not calls


def test_history_rejects_current_list_instead_of_old(tmp_path):
    today = pd.Timestamp("2008-08-15")

    def http_get(url):   # Server ignoriert asOfDate und liefert die heutige Liste
        return fake_csv(pd.Timestamp("2026-11-24"), [("AAA", 1.0)])

    h, info = pit.update_history(http_get, tmp_path / "h.json.gz", "acwi", today, log=lambda *_: None)
    assert info["coverage_months"] == 0 and h["failed"] and h.get("disabled_until")
    calls = []
    pit.update_history(lambda u: calls.append(u) or "", tmp_path / "h.json.gz", "acwi", today, log=lambda *_: None)
    assert not calls        # 30 Tage Pause
