"""Synthetische DEMO-Daten – ausschließlich für Tests und die Vorschau.

Alle Namen und Symbole sind frei erfunden ("Demo ..."). Die Pipeline markiert solche
Läufe mit "demo": true; die App zeigt dann ein deutliches DEMO-Banner und keine Empfehlungen
als echte Signale. Die Daten enthalten absichtlich Fehler (veraltete Kurse, Sprünge,
fehlende Umsätze, Penny-Stock, Doppel-Gattung), um die Qualitätsprüfung zu testen.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

COUNTRIES = [
    ("USA", "", "USD", 110), ("Deutschland", ".DE", "EUR", 30), ("Frankreich", ".PA", "EUR", 25),
    ("Großbritannien", ".L", "GBp", 30), ("Japan", ".T", "JPY", 45), ("Schweiz", ".SW", "CHF", 15),
    ("Kanada", ".TO", "CAD", 20), ("Australien", ".AX", "AUD", 15), ("Schweden", ".ST", "SEK", 10),
]
SECTORS = ["IT", "Finanzen", "Gesundheit", "Zyklischer Konsum", "Kommunikation", "Industrie",
           "Basiskonsum", "Energie", "Versorger", "Immobilien", "Rohstoffe"]
WORDS = ["Alpha", "Boreal", "Cobalt", "Delta", "Ember", "Fjord", "Granit", "Helix", "Iris", "Jade", "Kepler",
         "Lumen", "Meridian", "Nimbus", "Orbit", "Polaris", "Quarz", "Radiant", "Sierra", "Tundra", "Umbra",
         "Vektor", "Wolfram", "Xenon", "Yukon", "Zenit"]
FX_START = {"USD": 1.05, "JPY": 140.0, "GBP": 0.86, "CHF": 0.95, "CAD": 1.45, "AUD": 1.60, "SEK": 11.0}


def generate(asof: str = "2026-11-20", seed: int = 7):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2001-01-02", asof)
    n_days = len(dates)
    universe = []
    i = 0
    for country, suf, cur, n in COUNTRIES:
        for _ in range(n):
            i += 1
            w = WORDS[i % len(WORDS)]
            sym = f"DMO{i:03d}{suf}"
            legal = {"": "Inc", ".DE": "AG", ".PA": "SA", ".L": "plc", ".T": "KK", ".SW": "AG",
                     ".TO": "Corp", ".AX": "Ltd", ".ST": "AB"}[suf]
            universe.append({"symbol": sym, "name": f"Demo {w} {i:03d} {legal}", "country": country,
                             "sector": SECTORS[i % len(SECTORS)], "currency_raw": cur, "suffix": suf})
    uni = pd.DataFrame(universe)
    n = len(uni)
    # Doppel-Gattung (gleicher Emittent)
    uni.loc[n - 1, "name"] = uni.loc[n - 2, "name"] + " Class B"
    uni.loc[n - 2, "name"] = uni.loc[n - 2, "name"] + " Class A"
    uni.loc[n - 1, "country"] = uni.loc[n - 2, "country"]

    market = rng.normal(0.07 / 252, 0.011, n_days)
    crash = (dates >= "2008-09-01") & (dates <= "2009-03-06")
    market[crash] -= 0.0025
    rebound = (dates > "2009-03-06") & (dates <= "2009-06-30")
    market[rebound] += 0.004
    covid = (dates >= "2020-02-20") & (dates <= "2020-03-23")
    market[covid] -= 0.012
    sector_f = {s: rng.normal(0, 0.006, n_days) for s in SECTORS}
    # persistente erwartete Rendite je Aktie (AR(1) auf Monatsbasis) => Momentum-Effekt
    months = pd.PeriodIndex(dates, freq="M")
    mcodes, muniq = pd.factorize(months)
    adj = np.empty((n_days, n))
    vol = np.empty((n_days, n))
    for j in range(n):
        beta = rng.uniform(0.6, 1.4)
        idio_sd = rng.uniform(0.009, 0.028)
        mu = np.zeros(len(muniq))
        for t in range(1, len(muniq)):
            mu[t] = 0.85 * mu[t - 1] + rng.normal(0, 0.0045)
        drift = mu[mcodes] / 21
        # Momentum-Crash 2009: Gewinner fallen, Verlierer steigen
        drift[rebound] -= 2.5 * mu[mcodes][rebound] / 21
        r = beta * market + sector_f[uni.at[j, "sector"]] + drift + rng.normal(0, idio_sd, n_days)
        lvl = rng.uniform(15, 300)
        if uni.at[j, "currency_raw"] == "JPY":
            lvl *= 120
        if uni.at[j, "currency_raw"] == "GBp":
            lvl *= 100
        adj[:, j] = lvl * np.exp(np.cumsum(r))
        vol[:, j] = rng.lognormal(np.log(rng.uniform(2e5, 4e6)), 0.4, n_days)
    adj_df = pd.DataFrame(adj, index=dates, columns=uni["symbol"])
    vol_df = pd.DataFrame(vol, index=dates, columns=uni["symbol"]).round()
    # Dividenden: close = adj * Faktor (Faktor fällt rückwärts)
    close_df = adj_df.copy()
    for j, sym in enumerate(uni["symbol"]):
        y = rng.uniform(0.0, 0.035)
        steps = np.exp(y * (np.arange(n_days)[::-1] / 252))
        close_df[sym] = adj_df[sym] * steps
    # Börsenfeiertage je Land simulieren (zufällige fehlende Tage, nicht für USA)
    for j, sym in enumerate(uni["symbol"]):
        if uni.at[j, "suffix"] != "":
            miss = rng.random(n_days) < 0.02
            adj_df.loc[miss, sym] = np.nan
            close_df.loc[miss, sym] = np.nan
            vol_df.loc[miss, sym] = np.nan
    # IPO / kurze Historie
    late = uni["symbol"].iloc[5]
    for df in (adj_df, close_df, vol_df):
        df.loc[df.index < pd.Timestamp(asof) - pd.Timedelta(days=400), late] = np.nan
    # Fehlerfälle für die Qualitätsprüfung
    stale = uni["symbol"].iloc[7]
    for df in (adj_df, close_df, vol_df):
        df.loc[df.index > pd.Timestamp(asof) - pd.Timedelta(days=20), stale] = np.nan
    jump = uni["symbol"].iloc[9]
    k = n_days - 60
    adj_df.iloc[k:, adj_df.columns.get_loc(jump)] *= 3.2
    close_df.iloc[k:, close_df.columns.get_loc(jump)] *= 3.2
    zero = uni["symbol"].iloc[11]
    vol_df.iloc[-70:, vol_df.columns.get_loc(zero)] = 0
    penny = uni["symbol"].iloc[13]
    scale = 0.4 / close_df[penny].iloc[-1]
    adj_df[penny] *= scale
    close_df[penny] *= scale
    missing = uni["symbol"].iloc[15]
    # Starker Gewinner (damit eine plausible Spitze existiert)
    win = uni["symbol"].iloc[20]
    boost = np.linspace(0, 1.1, 260)
    adj_df.iloc[-260:, adj_df.columns.get_loc(win)] *= np.exp(boost)
    close_df.iloc[-260:, close_df.columns.get_loc(win)] *= np.exp(boost)

    frames, currency = {}, {}
    for j, sym in enumerate(uni["symbol"]):
        if sym == missing:
            continue
        df = pd.DataFrame({"close": close_df[sym], "adj": adj_df[sym], "volume": vol_df[sym]}).dropna(subset=["close"])
        cur = uni.at[j, "currency_raw"]
        if cur == "GBp":
            df["close"] /= 100
            df["adj"] /= 100
            cur = "GBP"
        frames[sym] = df
        currency[sym] = cur
    # Wechselkurse (Einheiten je EUR)
    fx = pd.DataFrame(index=dates)
    for c, s0 in FX_START.items():
        fx[c] = s0 * np.exp(np.cumsum(rng.normal(0, 0.005, n_days)))
    # Referenzkurse der "Zweitquelle"
    ref = {}
    for sym, df in frames.items():
        if df.index[-1] >= pd.Timestamp(asof) - pd.Timedelta(days=3):
            ref[sym] = float(df["close"].iloc[-1]) * (1 + rng.normal(0, 0.002))
    bad = uni["symbol"].iloc[17]
    if bad in ref:
        ref[bad] *= 1.12
    # Benchmarks aus dem Marktfaktor
    mk = pd.Series(100 * np.exp(np.cumsum(market * 0.9)), index=dates)
    bench = {
        "EUNL.DE": (mk[mk.index >= "2009-09-25"] * 0.3, "EUR"),
        "URTH": (mk[mk.index >= "2012-01-12"] * 0.5 * fx["USD"].reindex(mk.index), "USD"),
        "IS3R.DE": (mk[mk.index >= "2014-10-03"] * 0.2 * np.exp(np.linspace(0, 0.25, (mk.index >= "2014-10-03").sum())), "EUR"),
        "MTUM": (mk[mk.index >= "2013-04-18"] * 0.6 * fx["USD"].reindex(mk.index), "USD"),
    }
    for sym, (s, cur) in bench.items():
        frames[sym] = pd.DataFrame({"close": s, "adj": s, "volume": 1e6})
        currency[sym] = cur
    uni["currency_hint"] = uni["currency_raw"]
    uni["ref_price"] = uni["symbol"].map(ref)
    uni["isin"] = ["XX" + f"{k:010d}" for k in range(len(uni))]
    uni["index_weight"] = np.round(rng.uniform(0.01, 0.5, len(uni)), 3)
    uni["exchange"] = "Demo-Börse"
    uni["universe_source"] = "DEMO (synthetisch)"
    from .universe import issuer_key
    uni["issuer_key"] = [issuer_key(nm, c) for nm, c in zip(uni["name"], uni["country"])]
    return uni.drop(columns=["currency_raw", "suffix"]), frames, currency, fx


def demo_details(sym: str, name: str, rng: np.random.Generator) -> dict:
    rev = float(rng.uniform(1e9, 8e10))
    return {
        "fund": {"demo": {
            "metrics": {"fiscal_year": 2025, "revenue": rev, "revenue_growth": float(rng.normal(0.08, 0.1)),
                        "net_margin": float(rng.uniform(0.02, 0.3)), "op_margin": float(rng.uniform(0.05, 0.35)),
                        "eps_diluted": float(rng.uniform(1, 12)), "fcf_margin": float(rng.uniform(-0.05, 0.25)),
                        "roe": float(rng.uniform(0.02, 0.35)), "debt_to_equity": float(rng.uniform(0, 2.5)),
                        "dilution": float(rng.normal(0.0, 0.02)), "pe": float(rng.uniform(8, 60))},
        }, "yahoo": {"longBusinessSummary": f"{name} ist ein frei erfundenes Demo-Unternehmen zum Testen der App."}},
        "fund_date": None, "news": [], "news_date": None,
    }
