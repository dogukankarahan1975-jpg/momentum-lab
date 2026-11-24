"""Zentrale, versionierte Parameter von Momentum Lab.

Jede Änderung an METHODOLOGY oder BACKTEST_VARIANTS erfordert eine neue
METHODOLOGY_VERSION und einen Eintrag in CHANGELOG.md. Frühere Screenings
speichern ihre Version und ihren Parameter-Hash, damit sie nachvollziehbar bleiben.
"""
from __future__ import annotations

import hashlib
import json
import math

PIPELINE_VERSION = "0.1.1"
METHODOLOGY_VERSION = "1.0.0"

METHODOLOGY = {
    # --- Momentum-Signal (orientiert an MSCI Momentum, Abschnitt 2.2) ---
    "m6_months": 6,              # 6-1: P(T-1)/P(T-7) - 1
    "m12_months": 12,            # 12-1: P(T-1)/P(T-13) - 1
    "skip_months": 1,            # jüngster Monat ausgeschlossen (Kurzfrist-Reversal)
    "price_window_days": 12,     # max. Abstand eines Stichtagskurses zum Zieldatum
    "vol_weeks": 156,            # Volatilität: wöchentliche Renditen, 3 Jahre
    "vol_min_weeks": 104,        # mindestens 2 Jahre Wochenrenditen
    "winsor_sigma": 3.0,         # robuste Standardisierung (Momente aus ±3σ-winsorisierten Werten)
    "weight_m6": 0.5,
    "weight_m12": 0.5,
    # --- Datenqualität / Ausschlüsse ---
    "min_history_years": 2.0,
    "stale_days": 5,             # letzter Kurs max. 5 Kalendertage vor dem Datenstand
    "min_rows_last_year": 225,   # Lückenprüfung (Handelstage in 365 Kalendertagen)
    "max_daily_jump": 2.5,       # Tagesfaktor > 2,5 oder < 1/2,5 => unplausibel
    "max_adj_ratio_jump": 0.25,  # Sprung im Verhältnis Adj/Close > 25 % => Anpassungsfehler
    "jump_lookback_days": 400,
    "liq_window_days": 63,
    "min_liquidity_eur": 1_000_000,   # Median-Tagesumsatz in EUR
    "max_zero_volume_share": 0.20,
    "min_price_eur": 1.0,
    "crosscheck_tolerance": 0.03,     # Abweichung zur Zweitquelle (iShares-Kurs)
    # --- Auswahl ---
    "top_n": 10,
    "candidate_max_pct": 0.10,   # Kandidat muss im besten Dezil liegen
    "require_positive_m6": True,
    "require_positive_m12": True,
    "toppick_min_z6": 1.0,
    "toppick_min_z12": 1.0,
    "toppick_max_vol_pct": 0.90,
    # --- Halte-/Verkaufsregeln (vor dem Backtest festgelegt) ---
    "hold_max_pct": 0.20,        # Halten solange im besten Quintil ...
    "sell_immediate_pct": 0.50,  # ... sofortiger Verkauf unterhalb des Medians
    "confirm_months": 2,         # sonst Verkauf erst nach Bestätigung an 2 Monatsenden
    "savings_max_pct": 0.05,     # Sparplan fortsetzen solange in den besten 5 %
    "trend_ma_days": 200,        # 200-Tage-Linie: nur Hinweis, kein Filter (Backtest-Variante)
}

# Steuer-/Kostenannahmen für den Backtest (deutscher Privatanleger)
TAX = {
    "rate": 0.26375,             # 25 % Abgeltungsteuer + 5,5 % Soli, ohne Kirchensteuer
    "allowance": 1000.0,         # Sparerpauschbetrag (Einzelperson)
    "etf_partial_exemption": 0.30,  # Teilfreistellung Aktien-ETF
}

COST_SCENARIOS = {
    "brutto": {"label": "ohne Kosten", "fee": 0.0, "spread": 0.0},
    "realistisch": {"label": "1 € Order + 0,20 % Spread", "fee": 1.0, "spread": 0.0020},
    "pessimistisch": {"label": "1 € Order + 0,50 % Spread", "fee": 1.0, "spread": 0.0050},
}

BACKTEST = {
    "start_capital": 10_000.0,
    "monthly_savings": 500.0,
    "first_rebalance": "2003-01-31",
    "recent_years": 10,
}

# Vorab festgelegte Varianten (keine nachträgliche Optimierung!)
BACKTEST_VARIANTS = [
    {"id": "m12_top10", "name": "Einfaches 12-1-Momentum, Top 10", "signal": "m12", "top": 10, "rules": "strict"},
    {"id": "m612_top10", "name": "6+12-Momentum kombiniert, Top 10", "signal": "m612", "top": 10, "rules": "strict"},
    {"id": "ra_top10", "name": "Risikoadjustiert (MSCI-Stil), Top 10", "signal": "ra", "top": 10, "rules": "strict"},
    {"id": "ra_top5", "name": "Risikoadjustiert, Top 5", "signal": "ra", "top": 5, "rules": "strict"},
    {"id": "ra_top1", "name": "Risikoadjustiert, Top 1", "signal": "ra", "top": 1, "rules": "strict"},
    {"id": "ra_top10_score", "name": "Risikoadjustiert, Top 10 scoregewichtet", "signal": "ra", "top": 10, "rules": "strict", "weighting": "score"},
    {"id": "app_top10", "name": "App-Regeln: Top 10 mit Puffer & Bestätigung", "signal": "ra", "top": 10, "rules": "app"},
    {"id": "app_top1", "name": "App-Regeln: Top Pick", "signal": "ra", "top": 1, "rules": "app"},
    {"id": "app_top10_ma200", "name": "App-Regeln + 200-Tage-Filter", "signal": "ra", "top": 10, "rules": "app", "stock_ma_filter": True},
    {"id": "app_top10_regime", "name": "App-Regeln + Markt-Trendfilter", "signal": "ra", "top": 10, "rules": "app", "market_filter": True},
    {"id": "app_top10_volshock", "name": "App-Regeln + MSCI-Volatilitätsschock-Regel", "signal": "ra", "top": 10, "rules": "app", "vol_shock_rule": True},
    {"id": "app_top10_hold10", "name": "Sensitivität: Halteband 10 %", "signal": "ra", "top": 10, "rules": "app", "hold_max_pct": 0.10},
    {"id": "app_top10_hold30", "name": "Sensitivität: Halteband 30 %", "signal": "ra", "top": 10, "rules": "app", "hold_max_pct": 0.30},
]

SAVINGS_VARIANTS = [
    {"id": "sp_top1", "name": "Sparplan in den Top Pick", "top": 1},
    {"id": "sp_top10", "name": "Sparplan verteilt auf Top 10", "top": 10},
    {"id": "sp_etf", "name": "Sparplan in MSCI-World-ETF", "etf": True},
]

# Benchmarks / Marktproxys (Yahoo-Symbole). ETF-Daten enthalten Fondskosten.
BENCHMARKS = {
    "msci_world_eur": {"symbol": "EUNL.DE", "name": "iShares Core MSCI World (EUR)", "currency": "EUR"},
    "msci_world_usd": {"symbol": "URTH", "name": "iShares MSCI World ETF (USD)", "currency": "USD"},
    "msci_momentum_eur": {"symbol": "IS3R.DE", "name": "iShares MSCI World Momentum Factor (EUR)", "currency": "EUR"},
    "msci_usa_momentum": {"symbol": "MTUM", "name": "iShares MSCI USA Momentum Factor (USD)", "currency": "USD"},
}
REGIME_SYMBOL_ORDER = ["URTH", "EUNL.DE"]

LN_MAX_JUMP = math.log(METHODOLOGY["max_daily_jump"])


def params_hash() -> str:
    payload = json.dumps({"m": METHODOLOGY, "v": BACKTEST_VARIANTS, "t": TAX}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]
