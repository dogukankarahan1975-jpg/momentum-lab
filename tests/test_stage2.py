"""Tests für Stage 2: Kennzahlen, Perzentile, Kategorien, Datenqualität, Risiko, Entscheidung, Outperformance,
Fundamentaldaten-Parser, Abruf mit Drosselung und Teil-Backtest."""
import gzip
import json

import numpy as np
import pandas as pd
import pytest

from pipeline import backtest as bt
from pipeline import core, fundamentals as fund, stage2
from pipeline.config import FUNDAMENTALS, STAGE2

ASOF = pd.Timestamp("2025-12-31")


def _idx():
    return pd.bdate_range("2021-01-04", ASOF)


# ------------------------------------------------------------------ kursbasierte Kennzahlen
def test_price_metrics_exact_for_smooth_trends():
    idx = _idx()
    t = np.arange(len(idx))
    up = pd.Series(100 * np.exp(0.001 * t), index=idx)
    down = pd.Series(100 * np.exp(-0.001 * t), index=idx)
    loc = pd.DataFrame({"UP": up, "DOWN": down})
    mkt = pd.Series(50 * np.exp(0.0002 * t), index=idx)
    pm, market = stage2.price_metrics_at(loc, loc.copy(), mkt, ASOF)
    p1 = core.price_at(loc, ASOF - pd.DateOffset(months=1), 12)
    p13 = core.price_at(loc, ASOF - pd.DateOffset(months=13), 12)
    assert pm.at["UP", "m12_1"] == pytest.approx(p1["UP"] / p13["UP"] - 1)
    assert pm.at["UP", "pos_months"] == 1.0
    assert pm.at["UP", "info_disc"] == pytest.approx(-1.0)        # nur Plus-Tage = kontinuierlich
    assert pm.at["UP", "prox_52w"] == pytest.approx(1.0)
    assert pm.at["UP", "mdd_12m"] == pytest.approx(0.0)
    assert pm.at["UP", "r2_6m"] == pytest.approx(1.0, abs=1e-9)
    assert pm.at["DOWN", "r2_6m"] == pytest.approx(-1.0, abs=1e-9)  # stabiler Abwärtstrend zählt nicht als Qualität
    assert pm.at["UP", "hh_hl"] == 1.0
    assert pm.at["UP", "beat_share"] == 1.0 and pm.at["DOWN", "beat_share"] == 0.0
    assert pm.at["UP", "rs_world_12m"] > 0 > pm.at["DOWN", "rs_world_12m"]
    assert pm.at["UP", "ma_spread"] > 0 > pm.at["DOWN", "ma_spread"]
    assert market["ret_12m"] == pytest.approx(np.exp(0.0002 * (t[-1] - t[idx <= ASOF - pd.DateOffset(months=12)][-1])) - 1, rel=1e-6)


def test_residual_momentum_and_down_market_behaviour():
    idx = _idx()
    rng = np.random.default_rng(1)
    m = rng.normal(0.0003, 0.01, len(idx))
    a = m + 0.0015 + rng.normal(0, 0.004, len(idx))
    b = m - 0.0015 + rng.normal(0, 0.004, len(idx))
    loc = pd.DataFrame({"A": 100 * np.exp(np.cumsum(a)), "B": 100 * np.exp(np.cumsum(b))}, index=idx)
    mkt = pd.Series(100 * np.exp(np.cumsum(m)), index=idx)
    pm, _ = stage2.price_metrics_at(loc, loc.copy(), mkt, ASOF)
    assert pm.at["A", "resid_mom"] > 0 > pm.at["B", "resid_mom"]
    assert pm.at["A", "beat_share"] > 0.5 > pm.at["B", "beat_share"]
    assert pm.at["A", "down_excess"] > 0
    assert 0.7 < pm.at["A", "beta_36m"] < 1.3


def test_price_metrics_ignore_future_data():
    idx = pd.bdate_range("2021-01-04", "2026-06-30")
    t = np.arange(len(idx))
    s = pd.Series(100 * np.exp(0.001 * t), index=idx)
    s[s.index > ASOF] *= 3.0                                         # Zukunft: riesiger Sprung
    loc = pd.DataFrame({"X": s})
    pm_future, _ = stage2.price_metrics_at(loc, loc.copy(), None, ASOF)
    pm_cut, _ = stage2.price_metrics_at(loc.loc[:ASOF], loc.loc[:ASOF].copy(), None, ASOF)
    for k in ("m12_1", "m3_1", "ret_1m", "prox_52w", "ext50", "accel_z", "vol63"):
        a, b = pm_future.at["X", k], pm_cut.at["X", k]
        assert (np.isnan(a) and np.isnan(b)) or a == pytest.approx(b), k


def test_trend_status_rules():
    base = {"last_close_loc": 110.0, "ma50": 105.0, "ma200": 100.0, "slope_ma50": 0.01, "slope_ma200": 0.01, "z_acc": 0.5}
    ts = lambda **kw: stage2.trend_status(pd.Series({**base, **kw}))  # noqa: E731
    assert ts() == "Gesunder Aufwärtstrend"
    assert ts(z_acc=2.5) == "Beschleunigender Aufwärtstrend"
    assert ts(last_close_loc=99.0) == "Trendbruch"
    assert ts(last_close_loc=102.0, slope_ma50=-0.01) == "Schwächer werdender Trend"
    assert ts(z_acc=-2.4) == "Schwächer werdender Trend"
    assert ts(last_close_loc=102.0) == "Gesunder Aufwärtstrend"           # Rücksetzer bei steigender 50-Tage-Linie
    assert ts(ma50=98.0, last_close_loc=101.0, slope_ma50=0.01) == "Seitwärtsbewegung"
    assert ts(ma50=np.nan) == "nicht bestimmbar"


def test_group_relative_and_home_groups():
    x = pd.Series({"A": 0.3, "B": 0.1, "C": 0.2, "D": 0.5})
    g = pd.Series({"A": "IT", "B": "IT", "C": "IT", "D": "Energie"})
    rel = stage2.group_relative(x, g, pd.Series(True, index=x.index), min_n=3)
    assert rel["A"] == pytest.approx(0.1) and np.isnan(rel["D"])          # Gruppe zu klein -> NaN
    countries = pd.Series({"AAA": "USA", "BBB.DE": "Deutschland", "CCC.T": "Japan"})
    elig = pd.Series(True, index=countries.index)
    hg = stage2.home_groups(list(countries.index), countries, elig, min_n=1)
    assert hg["BBB.DE"] == "Deutschland"
    hg2 = stage2.home_groups(list(countries.index), countries, elig, min_n=5)
    assert hg2["AAA"] == "Nordamerika" and hg2["CCC.T"] == "Pazifik" and hg2["BBB.DE"] == "Europa & Nahost"


# ------------------------------------------------------------------ Perzentile, Kategorien, Score
CATS = {"Q": {"name": "Q", "short": "Q", "metrics": [
    ("a", "A", 1, "universe", None, "all", "num"),
    ("b", "B", -1, "universe", None, "all", "num"),
    ("c", "C", 1, "sector", None, "nonfin", "num"),
    ("d", "D", 1, "universe", None, "all", "num"),
]}}


def _x(n=100):
    idx = [f"S{i:03d}" for i in range(n)]
    X = pd.DataFrame({"a": np.arange(n, dtype=float), "b": np.arange(n, dtype=float),
                      "c": np.arange(n, dtype=float), "d": np.nan}, index=idx)
    X.loc[idx[:3], "d"] = 1.0                                          # nur 3 % Werte -> Kennzahl inaktiv
    sector = pd.Series(["Finanzen" if i < 20 else ("IT" if i % 2 else "Industrie") for i in range(n)], index=idx)
    return X, sector


def test_percentiles_direction_applicability_and_activation():
    X, sector = _x()
    res = stage2.score_categories(X, sector, pd.Series(True, index=X.index), [], cats=CATS, mins={"Q": {"min": 2}})
    pct, st = res["pct"], res["status"]
    assert pct.at["S099", "a"] == pytest.approx(1 - 0.5 / 100)
    assert pct.at["S000", "b"] == pytest.approx(1 - 0.5 / 100)          # niedriger = besser
    assert np.isnan(pct.at["S005", "c"])                                 # Bank: Kennzahl nicht anwendbar
    assert st["d"]["active"] is False and np.isnan(pct.at["S000", "d"])  # zu wenige Vergleichswerte
    # Sektor-Perzentil: innerhalb IT (ungerade Indizes ab 21) ist S099 der beste
    assert pct.at["S099", "c"] == pytest.approx(1 - 0.5 / 40)
    det = res["detail"]["Q"]
    assert det["applicable"]["S005"] == 2 and det["applicable"]["S050"] == 3   # inaktive Kennzahl zählt nicht
    assert res["scores"].at["S099", "Q"] == pytest.approx(10 * np.mean([pct.at["S099", k] for k in "abc"]))


def test_category_minimum_and_missing_values():
    X, sector = _x()
    X.loc["S050", ["a", "b"]] = np.nan                                  # nur noch c -> unter Minimum 2
    res = stage2.score_categories(X, sector, pd.Series(True, index=X.index), [], cats=CATS, mins={"Q": {"min": 2}})
    assert np.isnan(res["scores"].at["S050", "Q"])
    assert res["detail"]["Q"]["available"]["S050"] == 1


def test_block_structure_counts_blocks_equally():
    idx = [f"S{i:02d}" for i in range(60)]
    X = pd.DataFrame({"n1": np.arange(60.0), "n2": np.arange(60.0), "n3": np.arange(60.0), "k1": np.arange(60.0)[::-1]}, index=idx)
    cats = {"A": {"name": "A", "short": "A", "blocks": ["niveau", "konsistenz"], "metrics": [
        ("n1", "", 1, "universe", "niveau", "all", "num"), ("n2", "", 1, "universe", "niveau", "all", "num"),
        ("n3", "", 1, "universe", "niveau", "all", "num"), ("k1", "", 1, "universe", "konsistenz", "all", "num")]}}
    res = stage2.score_categories(X, pd.Series("IT", index=idx), pd.Series(True, index=idx), [], cats=cats,
                                  mins={"A": {"blocks": {"niveau": 2, "konsistenz": 1}}})
    p = res["pct"].loc["S59"]
    assert res["scores"].at["S59", "A"] == pytest.approx(10 * (np.mean([p.n1, p.n2, p.n3]) + p.k1) / 2)


def test_final_score_weights_and_minimum():
    sc = pd.DataFrame({"Q": [8.0, 8.0], "R": [6.0, np.nan]}, index=["X", "Y"])
    fs = stage2.final_scores(sc, {"Q": 0.5, "R": 0.5})
    assert fs.at["X", "score"] == pytest.approx(7.0)
    assert np.isnan(fs.at["Y", "score"])                                 # nur 50 % Gewicht verfügbar
    fs2 = stage2.final_scores(sc, {"Q": 0.85, "R": 0.15})
    assert fs2.at["Y", "score"] == pytest.approx(8.0) and fs2.at["Y", "weight_available"] == pytest.approx(0.85)


# ------------------------------------------------------------------ Entscheidung, Risiko, Outperformance
NORMAL = {"level": "NORMAL", "why": "", "flags": [], "counts": {"gesamt": 0}}


def test_decision_thresholds_use_rounded_score():
    d = lambda s, **kw: stage2.decide(s, kw.get("dq", "HIGH"), kw.get("risk", NORMAL), kw.get("ver", True), True)["code"]  # noqa: E731
    assert d(9.04) == "EXCEPTIONAL"
    assert d(8.96) == "EXCEPTIONAL"          # angezeigt 9,0
    assert d(8.94) == "STRONG_BUY"
    assert d(8.46) == "STRONG_BUY" and d(8.44) == "WATCHLIST"   # Schwelle gilt für den angezeigten Wert (1 Nachkommastelle)
    assert d(7.5) == "WATCHLIST" and d(7.44) == "NO_ENTRY" and d(5.9) == "REJECT"
    assert stage2.decide(9.5, "HIGH", NORMAL, True, False) is None       # kein Stage-1-Kandidat
    assert d(None) == "INSUFFICIENT_DATA" and d(9.5, dq="INSUFFICIENT") == "INSUFFICIENT_DATA"


def test_decision_caps_and_hard_risk():
    hi1 = {"level": "HIGH", "why": "x", "flags": [], "counts": {"gesamt": 1}}
    hi3 = {"level": "HIGH", "why": "x", "flags": [], "counts": {"gesamt": 3}}
    crit = {"level": "CRITICAL", "why": "x", "flags": [], "counts": {"gesamt": 2}}
    assert stage2.decide(9.6, "HIGH", crit, True, True)["code"] == "HARD_RISK"
    assert stage2.decide(9.6, "HIGH", hi1, True, True)["code"] == "WATCHLIST"
    assert stage2.decide(9.6, "HIGH", hi3, True, True)["code"] == "NO_ENTRY"
    assert stage2.decide(9.6, "LOW", NORMAL, True, True)["code"] == "WATCHLIST"
    r = stage2.decide(9.6, "MEDIUM", NORMAL, None, True)
    assert r["code"] == "WATCHLIST" and not r["sparplan"] and any("Zweitquelle" in x for x in r["reasons"])
    assert stage2.decide(5.0, "HIGH", hi1, True, True)["code"] == "REJECT"   # Deckel heben nie an
    ok = stage2.decide(8.7, "MEDIUM", NORMAL, True, True)
    assert ok["code"] == "STRONG_BUY" and ok["sparplan"] is True


def _risk_row(**kw):
    base = {"ext50": 0.2, "ext200": 0.5, "dist_ma50": 0.03, "dist_ma200": 0.1, "accel_z": 0.3, "ret_1m": 0.02,
            "vol63": 0.25, "rsi14": 60.0, "trend_status": "Gesunder Aufwärtstrend", "breadth30": 0.2, "rev90": 0.05,
            "m3_1": 0.1, "surprise_last": 0.03, "pe_fwd": 20.0, "eps_fwd_neg": False, "next_earnings": None}
    base.update(kw)
    return pd.Series(base, dtype=object)


THR = {"ext50": 1.0, "ext200": 1.5, "vol63": 0.45}
ACTIVE = {"breadth30": {"active": True}, "rev90": {"active": True}, "ey_fwd": {"active": True}}


def test_risk_levels():
    ra = lambda row, p_ey=0.5: stage2.risk_assessment(row, THR, pd.Series({"ey_fwd": p_ey}), ASOF, ACTIVE)  # noqa: E731
    assert ra(_risk_row())["level"] == "NORMAL"
    one = ra(_risk_row(ext50=1.2, ext200=1.6))                           # beide Abstände = EIN Signal
    assert one["level"] == "ELEVATED" and [f["code"] for f in one["flags"]] == ["T_EXT"]
    assert ra(_risk_row(vol63=0.5))["level"] == "HIGH"                  # erhöhte Volatilität
    assert ra(_risk_row(accel_z=3.2))["level"] == "HIGH"                # extreme Beschleunigung
    rsi_alone = ra(_risk_row(rsi14=85.0))
    assert rsi_alone["level"] == "NORMAL" and rsi_alone["flags"][0]["counts"] is False   # RSI nur ergänzend
    assert ra(_risk_row(rsi14=85.0, ext50=1.2))["level"] == "HIGH"      # zusammen mit Abstand
    crit = ra(_risk_row(rev90=-0.04, breadth30=-0.3), p_ey=0.05)        # sinkende Erwartungen + teuer
    assert crit["level"] == "CRITICAL" and {"F_REV", "V_VAL"} <= {f["code"] for f in crit["flags"]}
    assert ra(_risk_row(rev90=-0.04, trend_status="Trendbruch"))["level"] == "CRITICAL"
    two_f = ra(_risk_row(rev90=-0.04, surprise_last=-0.05))
    assert two_f["level"] == "HIGH"
    ev = ra(_risk_row(next_earnings=(ASOF + pd.Timedelta(days=5)).strftime("%Y-%m-%d")))
    assert ev["level"] == "NORMAL" and ev["flags"][0]["code"] == "E_EARNINGS"   # Termin = nur Hinweis
    inactive = stage2.risk_assessment(_risk_row(rev90=-0.04), THR, pd.Series({"ey_fwd": 0.5}), ASOF, {})
    assert inactive["level"] == "NORMAL"                                # Kennzahl ohne Vergleichsbasis -> kein Signal


def test_outperformance_levels():
    good = pd.Series({"rs_world_3m": 0.05, "rs_world_6m": 0.1, "rs_world_12m": 0.2, "beat_n": 9, "breadth30": 0.3,
                      "rev90": 0.04, "rev_growth": 0.1, "eps_growth": 0.2, "sharpe12": 1.5}, dtype=object)
    mk = {"sharpe12": 0.6}
    out = stage2.outperformance(good, mk, NORMAL, ACTIVE)
    assert out["level"] == "HIGH" and out["positives"] == 6
    weak = good.copy()
    weak["rs_world_3m"], weak["beat_n"], weak["rev90"], weak["breadth30"] = -0.02, 4, -0.03, -0.2
    assert stage2.outperformance(weak, mk, NORMAL, ACTIVE)["level"] == "MARKET_LIKE"
    crit = {"level": "CRITICAL", "why": "", "flags": [], "counts": {"gesamt": 2}}
    assert stage2.outperformance(good, mk, crit, ACTIVE)["level"] == "LOW"
    sparse = pd.Series({"rs_world_3m": 0.05, "rs_world_6m": 0.1, "rs_world_12m": 0.2}, dtype=object)
    assert stage2.outperformance(sparse, mk, NORMAL, {})["level"] == "INSUFFICIENT"


# ------------------------------------------------------------------ Fundamentaldaten: Parser
QS = {"quoteSummary": {"error": None, "result": [{
    "price": {"currency": "GBp", "regularMarketPrice": {"raw": 2500.0}, "marketCap": {"raw": 1e11}, "longName": "Test plc"},
    "financialData": {"financialCurrency": "USD", "currentPrice": {"raw": 2500.0}, "totalRevenue": {"raw": 5e10},
                      "freeCashflow": {"raw": 5e9}, "debtToEquity": {"raw": 45.0}, "returnOnEquity": {"raw": 0.18},
                      "operatingMargins": {"raw": 0.22}, "revenueGrowth": {"raw": 0.07}, "earningsGrowth": {"raw": 0.12},
                      "numberOfAnalystOpinions": {"raw": 20}},
    "defaultKeyStatistics": {"forwardPE": {"raw": 12.5}, "forwardEps": {"raw": 2.5}, "trailingEps": {"raw": 2.2},
                             "priceToBook": {"raw": 2.0}, "enterpriseToEbitda": {"raw": 8.0}},
    "summaryDetail": {"trailingPE": {"raw": 14.2}, "priceToSalesTrailing12Months": {"raw": 2.0}},
    "earningsTrend": {"trend": [
        {"period": "0y", "endDate": "2026-12-31", "earningsEstimate": {"avg": {"raw": 2.3}, "numberOfAnalysts": {"raw": 10}, "growth": {"raw": 0.05}},
         "revenueEstimate": {"avg": {"raw": 5.2e10}}, "epsTrend": {"current": {"raw": 2.3}, "30daysAgo": {"raw": 2.2}, "90daysAgo": {"raw": 2.0}},
         "epsRevisions": {"upLast30days": {"raw": 6}, "downLast30days": {"raw": 1}}},
        {"period": "+1y", "endDate": "2027-12-31", "earningsEstimate": {"avg": {"raw": 2.5}, "numberOfAnalysts": {"raw": 8}, "growth": {"raw": 0.087}},
         "revenueEstimate": {"avg": {"raw": 5.5e10}}, "epsTrend": {"current": {"raw": 2.5}, "30daysAgo": {"raw": 2.5}, "90daysAgo": {"raw": 2.4}},
         "epsRevisions": {"upLast30days": {"raw": 2}, "downLast30days": {"raw": 2}}},
        {"period": "+5y", "growth": {"raw": 0.1}}]},
    "earningsHistory": {"history": [
        {"quarter": {"raw": 1735603200}, "epsActual": {"raw": 0.55}, "epsEstimate": {"raw": 0.5}, "surprisePercent": {"raw": 0.1}},
        {"quarter": {"raw": 1743379200}, "epsActual": {"raw": 0.5}, "epsEstimate": {"raw": 0.52}}]},
    "calendarEvents": {"earnings": {"earningsDate": [{"raw": 1770681600}]}},
}]}}


def test_parse_quote_summary():
    r = fund.parse_quote_summary(QS)
    assert r["currency"] == "GBp" and r["fin_currency"] == "USD" and r["pe_fwd"] == 12.5
    assert r["trend"]["0y"]["up30"] == 6 and r["trend"]["0y"]["eps_90d"] == 2.0 and "+5y" not in r["trend"]
    assert r["trend"]["+1y"]["eps_growth"] == pytest.approx(0.087)
    assert len(r["history"]) == 2 and r["history"][0]["surprise"] == pytest.approx(0.1)
    assert r["history"][1]["surprise"] == pytest.approx((0.5 - 0.52) / 0.52)     # selbst berechnet, wenn Feld fehlt
    assert r["next_earnings"] == "2026-02-10"
    with pytest.raises(fund.NotFound):
        fund.parse_quote_summary({"quoteSummary": {"result": None, "error": {"code": "Not Found", "description": "Quote not found"}}})


def test_parse_timeseries_derived_metrics():
    def item(name, vals):
        return {"meta": {"type": [name]}, name: [{"asOfDate": d, "currencyCode": "EUR", "reportedValue": {"raw": v}} for d, v in vals]}
    js = {"timeseries": {"error": None, "result": [
        item("annualTotalRevenue", [("2023-12-31", 100.0), ("2024-12-31", 120.0)]),
        item("annualOperatingIncome", [("2023-12-31", 10.0), ("2024-12-31", 18.0)]),
        item("annualEBIT", [("2024-12-31", 20.0)]),
        item("annualInterestExpense", [("2024-12-31", -4.0)]),
        item("annualInvestedCapital", [("2024-12-31", 100.0)]),
        item("annualDilutedAverageShares", [("2023-12-31", 50.0), ("2024-12-31", 51.0)]),
    ]}}
    r = fund.parse_timeseries(js)
    assert r["roic_pre"] == pytest.approx(0.2) and r["interest_cov"] == pytest.approx(5.0)
    assert r["dilution"] == pytest.approx(0.02)
    assert r["margin_change"] == pytest.approx(0.15 - 0.10)
    gap = fund.derive_timeseries({"annualDilutedAverageShares": {"2020-12-31": 50.0, "2024-12-31": 60.0},
                                  "annualTotalRevenue": {"2024-12-31": 1.0}})
    assert gap["dilution"] is None                                       # keine aufeinanderfolgenden Jahre


def test_fundamental_metrics_currency_and_consistency():
    rec = fund.parse_quote_summary(QS)
    store = fund.FundamentalsStore({"T.L": {"qs": rec, "qs_at": "2025-12-30"},
                                    "OLD": {"qs": rec, "qs_at": "2025-10-01"}})
    fx_row = pd.Series({"GBP": 0.85, "USD": 1.10})
    fm = stage2.fundamental_metrics(store, ["T.L", "OLD", "NONE"], ASOF, fx_row)
    price_usd = 25.0 / 0.85 * 1.10                                      # 2.500 Pence = 25 GBP -> USD
    assert fm.at["T.L", "ey_fwd"] == pytest.approx(2.5 / price_usd)
    assert fm.at["T.L", "breadth30"] == pytest.approx(np.mean([(6 - 1) / 10, (2 - 2) / 8]))
    assert fm.at["T.L", "rev90"] == pytest.approx(np.mean([0.3 / 2.0, 0.1 / 2.4]))
    assert fm.at["T.L", "peg"] == pytest.approx(12.5 / 8.7)
    assert fm.at["T.L", "de"] == pytest.approx(0.45) and fm.at["T.L", "fcf_margin"] == pytest.approx(0.1)
    assert np.isnan(fm.at["OLD", "ey_fwd"]) and np.isnan(fm.at["NONE", "roe"])    # veraltet / fehlend
    bad = json.loads(json.dumps(rec))
    bad["eps_fwd"] = 250.0                                              # Einheitenfehler (Faktor 100)
    st2 = fund.FundamentalsStore({"B.L": {"qs": bad, "qs_at": "2025-12-30"}})
    fm2 = stage2.fundamental_metrics(st2, ["B.L"], ASOF, fx_row)
    assert np.isnan(fm2.at["B.L", "ey_fwd"]) and bool(fm2.at["B.L", "ey_inconsistent"])


# ------------------------------------------------------------------ Abruf: Prioritäten, Budget, Drosselung
class FakeClient:
    kind = "fake"

    def __init__(self, behaviour):
        self.behaviour, self.calls = behaviour, []

    def quote_summary(self, sym):
        self.calls.append(("qs", sym))
        b = self.behaviour(sym)
        if isinstance(b, Exception):
            raise b
        return {"price": 1.0, "trend": {}, "history": []}

    def timeseries(self, sym, today):
        self.calls.append(("ts", sym))
        return {"roic_pre": 0.1}


def test_plan_refresh_priorities():
    store = fund.FundamentalsStore({"P1": {"qs": {}, "qs_at": "2025-12-30"}, "U1": {"qs": {}, "qs_at": "2025-12-28"},
                                    "U2": {"qs": {}, "qs_at": "2025-12-01"}, "NF": {"qs_err": "nicht gefunden: x", "qs_try": "2025-12-29"}})
    qs, ts, boot = fund.plan_refresh(store, ASOF, ["C1"], ["P1", "P2"], ["C1", "P1", "P2", "U1", "U2", "U3", "NF"], FUNDAMENTALS)
    assert qs[:2] == ["C1", "P2"]                    # Kandidaten zuerst, dann fällige Vergleichsgruppe
    assert "P1" not in qs and "U1" not in qs          # noch frisch genug
    assert qs.index("U3") < qs.index("U2")            # nie geladene vor alten
    assert "NF" not in qs                             # "nicht gefunden" erst nach 7 Tagen erneut
    assert boot is True


def test_refresh_stops_when_rate_limited_and_respects_budget():
    store = fund.FundamentalsStore()
    cl = FakeClient(lambda s: fund.RateLimited("429"))
    sleeps = []
    st = fund.refresh(store, [f"S{i}" for i in range(20)], [], ASOF, FUNDAMENTALS, False, clients=[cl],
                      sleep=sleeps.append, clock=lambda: 0.0, log=lambda *a: None)
    assert st["blocked"] and len(cl.calls) == 3 and st["skipped_qs"] == 17
    assert 30 in sleeps and 90 in sleeps
    cl2 = FakeClient(lambda s: None)
    params = dict(FUNDAMENTALS, qs_calls=5, delay_s=0)
    st2 = fund.refresh(store, [f"S{i}" for i in range(20)], ["S0"], ASOF, params, False, clients=[cl2],
                       sleep=lambda s: None, clock=lambda: 0.0, log=lambda *a: None)
    assert st2["qs_ok"] == 5 and st2["skipped_qs"] == 15 and st2["ts_ok"] == 1
    assert store.data["S0"]["qs_at"] == "2025-12-31" and store.data["S0"]["ts"]["roic_pre"] == 0.1


def test_refresh_falls_back_to_second_client_and_records_not_found():
    store = fund.FundamentalsStore()
    broken = FakeClient(lambda s: fund.CrumbError("kein Crumb"))
    good = FakeClient(lambda s: fund.NotFound("x") if s == "GONE" else None)
    st = fund.refresh(store, ["A", "GONE", "B"], [], ASOF, dict(FUNDAMENTALS, delay_s=0), False, clients=[broken, good],
                      sleep=lambda s: None, clock=lambda: 0.0, log=lambda *a: None)
    assert st["qs_ok"] == 2 and st["qs_notfound"] == 1 and st["path"] == "fake"
    assert len(broken.calls) == 1                     # nach dem ersten Fehler dauerhaft umgeschaltet
    assert store.data["GONE"]["qs_err"].startswith("nicht gefunden")


def test_yahoo_client_crumb_and_errors():
    class R:
        def __init__(self, code, js=None, text=""):
            self.status_code, self._js, self.text = code, js, text

        def json(self):
            if self._js is None:
                raise ValueError("kein JSON")
            return self._js

    class S:
        def __init__(self):
            self.n401 = 1

        def get(self, url, params=None, timeout=None):
            if "fc.yahoo.com" in url:
                return R(404)
            if "getcrumb" in url:
                return R(200, text="AbC123")
            if "quoteSummary/MISSING" in url:
                return R(404)
            if self.n401:
                self.n401 -= 1
                return R(401)
            assert params["crumb"] == "AbC123"
            return R(200, QS)
    c = fund.YahooClient(session=S())
    assert c.quote_summary("T.L")["pe_fwd"] == 12.5                     # 401 -> Crumb erneuert -> ok
    with pytest.raises(fund.NotFound):
        c.quote_summary("MISSING")


def test_weekly_snapshot_and_revision_from_history(tmp_path):
    rec = fund.parse_quote_summary(QS)
    store = fund.FundamentalsStore({"T.L": {"qs": rec, "qs_at": "2025-12-30"}})
    p = fund.write_weekly_snapshot(store, ["T.L"], tmp_path, ASOF)
    assert p is not None and p.name.endswith(".csv.gz")
    assert fund.write_weekly_snapshot(store, ["T.L"], tmp_path, ASOF) is None    # pro Woche nur einmal
    snap, d = fund.load_snapshot_near(tmp_path, ASOF + pd.Timedelta(days=3))
    assert snap.at["T.L", "rev0y_avg"] == pytest.approx(5.2e10) and d is not None
    newer = json.loads(json.dumps(rec))
    newer["trend"]["0y"]["rev_avg"] = 5.46e10                         # +5 % für dasselbe Geschäftsjahr
    st2 = fund.FundamentalsStore({"T.L": {"qs": newer, "qs_at": "2025-12-30"}})
    fm = stage2.fundamental_metrics(st2, ["T.L"], ASOF, pd.Series({"GBP": 0.85, "USD": 1.1}), snap)
    assert fm.at["T.L", "rev_est90"] == pytest.approx(np.mean([0.05, 0.0]))
    with gzip.open(p, "rt") as fh:
        assert "eps0y_now" in fh.readline()


# ------------------------------------------------------------------ Teil-Backtest
def test_stage2_partial_backtest_runs_and_reports():
    idx = pd.bdate_range("2006-01-02", "2015-12-31")
    rng = np.random.default_rng(3)
    n = 120
    cols = [f"S{i:03d}" for i in range(n)]
    m = rng.normal(0.0003, 0.01, len(idx))
    drift = rng.normal(0, 0.0006, n)
    rets = m[:, None] * rng.uniform(0.7, 1.3, n) + drift + rng.normal(0, 0.012, (len(idx), n))
    adj = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=idx, columns=cols)
    panel = core.prepare_panel(adj, adj.copy(), pd.DataFrame(1e6, index=idx, columns=cols))
    fx = pd.DataFrame({"USD": 1.0}, index=idx)
    mkt = pd.Series(100 * np.exp(np.cumsum(m)), index=idx)
    ctx = bt.Context(panel, pd.Series("EUR", index=cols), fx, set(), idx[-1], {}, log=lambda *a: None)
    ctx.compute_signals()
    meta = pd.DataFrame({"sector": ["IT" if i % 2 else "Industrie" for i in range(n)], "country": "USA"}, index=cols)
    from pipeline.stage2_backtest import newey_west_t, run_stage2_validation
    res = run_stage2_validation(ctx, meta, {"msci_world_eur": {"name": "MW", "eur": mkt}}, log=lambda *a: None)
    assert res["available"], res.get("reason")
    assert {s["holding_months"] for s in res["strategies"]} == {1, 3, 6, 12}
    s1 = next(s for s in res["strategies"] if s["id"] == "s1_top10" and s["holding_months"] == 1)
    assert s1["metrics"]["cagr"] is not None and s1["selection"]["decisions"] > 0
    assert 0 <= s1["selection"]["hit_rate"] <= 1
    assert res["ic"]["rows"][0]["factor"] == "s2p" and res["ic"]["rows"][0]["h1"]["months"] > 12
    assert pd.Timestamp(res["period"]["start"]) >= mkt.index[0] + pd.DateOffset(months=36)
    assert any("Look-ahead" in w for w in res["warnings"])
    assert newey_west_t(np.array([0.1] * 20 + [0.12] * 20), 0) > 10
