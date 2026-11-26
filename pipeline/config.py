"""Zentrale, versionierte Parameter von Momentum Lab.

Jede Änderung an METHODOLOGY oder BACKTEST_VARIANTS erfordert eine neue
METHODOLOGY_VERSION und einen Eintrag in CHANGELOG.md. Frühere Screenings
speichern ihre Version und ihren Parameter-Hash, damit sie nachvollziehbar bleiben.
"""
from __future__ import annotations

import hashlib
import json
import math

PIPELINE_VERSION = "0.7.0"
METHODOLOGY_VERSION = "1.0.0"   # Stage 1 (Momentum-Screening) – unverändert
STAGE2_VERSION = "2.0.0"        # Stage 2 (Fortsetzungsanalyse) – eigene Version

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
    "sp500_tr": {"symbol": "^SP500TR", "name": "S&P 500 (Total-Return-Index, abzgl. 0,07 % ETF-Kosten)", "currency": "USD"},
    "sp500_eur": {"symbol": "SXR8.DE", "name": "iShares Core S&P 500 (EUR, thesaurierend)", "currency": "EUR"},
}
REGIME_SYMBOL_ORDER = ["URTH", "EUNL.DE"]
# Verlängerung des MSCI-World-Sparplans vor dem Start von EUNL (09/2009): ältere iShares-MSCI-World-ETFs
# (ausschüttend; Yahoo-„adjclose“ rechnet Ausschüttungen wieder an). Wird nur verwendet, wenn die Reihe im
# gemeinsamen Zeitraum mit EUNL nachweislich übereinstimmt (siehe simulator.chain_backfill).
MSCI_WORLD_BACKFILL = [
    {"symbol": "IQQW.DE", "name": "iShares MSCI World UCITS ETF (Dist), Xetra", "currency": "EUR"},
    {"symbol": "IWRD.L", "name": "iShares MSCI World UCITS ETF (Dist), London", "currency": "USD"},
]

LN_MAX_JUMP = math.log(METHODOLOGY["max_daily_jump"])


def params_hash() -> str:
    payload = json.dumps({"m": METHODOLOGY, "v": BACKTEST_VARIANTS, "t": TAX}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


# =============================================================================================
# STAGE 2 – Fortsetzungsanalyse der Stage-1-Kandidaten (Methodik S2 v1.0.0)
# =============================================================================================
# Alle Werte wurden VOR dem ersten Lauf mit echten Daten festgelegt. Die Kategorie-Gewichte und
# Entscheidungsschwellen sind die Vorgabe des Nutzers (heuristisch, noch nicht validiert).
# Innerhalb einer Kategorie sind alle Kennzahlen gleich gewichtet (A und F: zwei gleich gewichtete
# Blöcke). Jede Kennzahl wird als Perzentil gegen eine dokumentierte Vergleichsgruppe skaliert:
#   "universe" = alle zulässigen MSCI-World-Aktien (Frage: besser als der Markt?)
#   "sector"   = zulässige Aktien desselben GICS-Sektors (Branchen fair vergleichen)
#   "peers"    = Stage-1-Kandidatengruppe (bestes Zehntel, positives Momentum): Überhitzung wird nur
#                gegen andere Momentum-Aktien gemessen, damit starkes Momentum nicht pauschal bestraft wird.

STAGE2 = {
    "weights": {"A": 0.20, "B": 0.20, "C": 0.20, "D": 0.15, "E": 0.10, "F": 0.15},
    "min_weight_available": 0.80,      # Score nur, wenn Kategorien mit >= 80 % Gewicht berechenbar sind
    # Entscheidung nach (auf eine Nachkommastelle gerundetem) Score – Vorgabe des Nutzers, heuristisch
    "thresholds": [[9.0, "EXCEPTIONAL"], [8.5, "STRONG_BUY"], [7.5, "WATCHLIST"], [6.0, "NO_ENTRY"], [0.0, "REJECT"]],
    # Datenqualität / Aktualität
    "fund_max_age_days": 21,           # ältere Kennzahlen gelten als fehlend
    "fund_fresh_days": 7,              # für "HIGH DATA QUALITY"
    "ts_max_age_days": 400,            # Jahreswerte (Bilanz/GuV)
    "dq_high_min_coverage": 0.90,      # Anteil vorhandener Kennzahlen für HIGH
    # Vergleichsgruppen
    "ref_min_coverage": 0.60,          # Kennzahl wird nur genutzt, wenn >= 60 % der Vergleichsgruppe Werte haben
    "ref_min_n": 200,                  # ... und mindestens 200 Aktien (Universums-Kennzahlen)
    "sector_min_n": 15,                # Sektor-Perzentil nur mit >= 15 Werten, sonst Universum
    "home_min_n": 20,                  # Heimatmarkt = Land mit >= 20 Aktien, sonst MSCI-Region
    "peer_min_n": 30,                  # Momentum-Vergleichsgruppe; sonst beste 20 % des Rankings
    "peer_fallback_pct": 0.20,
    # Anti-Peak-/Anti-Chasing-Modul (Schwellen: Perzentil-Konvention bzw. statistische Konvention)
    "risk": {
        "ext_peer_pct": 0.90,          # Abstand zu 50/200-Tage-Linie im obersten Zehntel der Momentum-Gruppe
        "vol_peer_pct": 0.90,          # Volatilität im obersten Zehntel der Momentum-Gruppe
        "accel_z": 2.0,                # 1-Monats-Rendite > 2 Standardabweichungen
        "accel_z_extreme": 3.0,        # > 3 Standardabweichungen = extrem
        "rsi_extreme": 80.0,           # ergänzend; zählt nur zusammen mit einem anderen technischen Signal
        "val_sector_pct": 0.10,        # Gewinnrendite im teuersten Zehntel des eigenen Sektors
        "high_exclude_flags": 3,       # HIGH mit >= 3 Warnsignalen => kein Einstieg (NO ENTRY)
    },
    "outperf": {"beat_months_min": 7, "min_evaluable": 5},
    "event_window_days": 14,           # Quartalszahlen in den nächsten 14 Tagen: Hinweis
    # Fenster (Handelstage bzw. Monate)
    "win": {"vol_d": 252, "vol_short": 63, "ma_short": 50, "ma_long": 200, "slope_lag": 20, "r2": 126,
            "rsi": 14, "accel": 21, "acc_recent": 63, "acc_base": 252,
            "resid_months": 36, "resid_min": 30, "beat_months": 12, "down_months": 36, "down_min": 6,
            "hh_months": 12, "price_window_days": 12},
}

# Kennzahlen je Kategorie: (Schlüssel, Bezeichnung, Richtung +1 höher=besser / -1 niedriger=besser,
# Vergleichsgruppe, Block, gilt für: all | nonfin | fin, Anzeigeformat)
STAGE2_CATEGORIES = {
    "A": {"name": "Momentum-Persistenz", "short": "Momentum", "blocks": ["niveau", "konsistenz"], "metrics": [
        ("m12_1", "12-1-Monats-Momentum", 1, "universe", "niveau", "all", "pct"),
        ("m6_1", "6-1-Monats-Momentum", 1, "universe", "niveau", "all", "pct"),
        ("m3_1", "3-1-Monats-Momentum", 1, "universe", "niveau", "all", "pct"),
        ("m12_2", "12-2-Monats-Momentum", 1, "universe", "niveau", "all", "pct"),
        ("pos_months", "Anteil positiver Monate (12-1)", 1, "universe", "konsistenz", "all", "share"),
        ("info_disc", "Sprunghaftigkeit der Kursgewinne (Frog-in-the-Pan)", -1, "universe", "konsistenz", "all", "num"),
    ]},
    "B": {"name": "Gewinn- und Revisionsmomentum", "short": "Gewinne", "metrics": [
        ("breadth30", "Revisionsbreite EPS, 30 Tage", 1, "universe", None, "all", "share_signed"),
        ("rev30", "EPS-Schätzung ggü. vor 30 Tagen", 1, "universe", None, "all", "pct"),
        ("rev90", "EPS-Schätzung ggü. vor 90 Tagen", 1, "universe", None, "all", "pct"),
        ("surprise4", "Gewinnüberraschung, Ø 4 Quartale", 1, "universe", None, "all", "pct"),
        ("rev_growth", "Umsatzwachstum (Quartal ggü. Vorjahr)", 1, "universe", None, "all", "pct"),
        ("eps_growth", "Gewinnwachstum je Aktie (Quartal ggü. Vorjahr)", 1, "universe", None, "all", "pct"),
        ("margin_change", "Veränderung operative Marge (Geschäftsjahr)", 1, "universe", None, "nonfin", "pp"),
        ("rev_est90", "Umsatzschätzung ggü. vor ca. 90 Tagen", 1, "universe", None, "all", "pct"),
    ]},
    "C": {"name": "Relative Stärke und Outperformance", "short": "Rel. Stärke", "metrics": [
        ("resid_mom", "Marktbereinigtes Momentum ggü. MSCI World (12-1 M)", 1, "universe", None, "all", "num"),
        ("beat_share", "Monate besser als MSCI World (12 M)", 1, "universe", None, "all", "share"),
        ("rs_sector", "Relative Stärke zum eigenen Sektor (6-1 M)", 1, "universe", None, "all", "pct"),
        ("rs_home", "Relative Stärke zum Heimatmarkt (6-1 M)", 1, "universe", None, "all", "pct"),
    ]},
    "D": {"name": "Trendqualität und Kursstärke", "short": "Trend", "metrics": [
        ("prox_52w", "Nähe zum 52-Wochen-Hoch", 1, "universe", None, "all", "ratio"),
        ("ma_spread", "Abstand 50- zur 200-Tage-Linie", 1, "universe", None, "all", "pct"),
        ("r2_6m", "Trendstabilität (R², 6 Monate)", 1, "universe", None, "all", "num"),
        ("mdd_12m", "Maximaler Rückgang 12 Monate", 1, "universe", None, "all", "pct"),
        ("down_excess", "Überrendite in Monaten mit fallendem MSCI World", 1, "universe", None, "all", "pct"),
        ("hh_hl", "Monate mit höherem Hoch und höherem Tief (12 M)", 1, "universe", None, "all", "share"),
    ]},
    "E": {"name": "Unternehmensqualität und Fundamentaldaten", "short": "Qualität", "metrics": [
        ("roe", "Eigenkapitalrendite", 1, "sector", None, "all", "pct"),
        ("roic_pre", "Kapitalrendite ROIC (EBIT / investiertes Kapital)", 1, "sector", None, "nonfin", "pct"),
        ("op_margin", "Operative Marge", 1, "sector", None, "nonfin", "pct"),
        ("fcf_margin", "Free-Cashflow-Marge", 1, "sector", None, "nonfin", "pct"),
        ("de", "Verschuldung (Finanzschulden / Eigenkapital)", -1, "sector", None, "nonfin", "x"),
        ("interest_cov", "Zinsdeckung (EBIT / Zinsaufwand)", 1, "sector", None, "nonfin", "x"),
        ("roa", "Gesamtkapitalrendite", 1, "sector", None, "fin", "pct"),
        ("profit_margin", "Nettomarge", 1, "sector", None, "fin", "pct"),
        ("dilution", "Veränderung der Aktienanzahl (1 Jahr)", -1, "sector", None, "all", "pct"),
    ]},
    "F": {"name": "Bewertung, Volatilität und Überhitzung", "short": "Bewertung/Risiko", "blocks": ["bewertung", "ueberhitzung"], "metrics": [
        ("ey_fwd", "Gewinnrendite Forward (= 1 / Forward-KGV)", 1, "sector", "bewertung", "all", "pct"),
        ("ey_ttm", "Gewinnrendite 12 M (= 1 / KGV)", 1, "sector", "bewertung", "all", "pct"),
        ("ebitda_ev", "EBITDA / Unternehmenswert (= 1 / EV-EBITDA)", 1, "sector", "bewertung", "nonfin", "pct"),
        ("sp", "Umsatz / Börsenwert (= 1 / KUV)", 1, "sector", "bewertung", "nonfin", "pct"),
        ("bp", "Buchwert / Börsenwert (= 1 / KBV)", 1, "sector", "bewertung", "fin", "pct"),
        ("peg", "PEG (Forward-KGV / erwartetes Gewinnwachstum)", -1, "sector", "bewertung", "all", "num"),
        ("ext50", "Abstand zur 50-Tage-Linie (in Standardabweichungen)", -1, "peers", "ueberhitzung", "all", "num"),
        ("ext200", "Abstand zur 200-Tage-Linie (in Standardabweichungen)", -1, "peers", "ueberhitzung", "all", "num"),
        ("accel_z", "Kursbewegung letzter Monat (in Standardabweichungen)", -1, "peers", "ueberhitzung", "all", "num"),
        ("vol63", "Volatilität 3 Monate", -1, "peers", "ueberhitzung", "all", "pct"),
    ]},
}
# Mindestanforderungen je Kategorie ("methodisch ausreichend")
STAGE2_MIN = {
    "A": {"blocks": {"niveau": 2, "konsistenz": 1}},
    "B": {"min": 3, "core_any": ["breadth30", "rev30", "rev90", "surprise4"]},
    "C": {"min": 2},
    "D": {"min": 3},
    "E": {"share": 0.5},
    "F": {"blocks": {"bewertung": 1, "ueberhitzung": 2}},
}
STAGE2_PRICE_CATEGORIES = ["A", "C", "D"]       # vollständig aus Kursen berechenbar
FIN_SECTORS = {"Finanzen"}

# Teil-Backtest: nur die kursbasierten Stage-2-Bausteine (A, C, D und Überhitzungsblock von F)
STAGE2_BACKTEST = {
    "holding_months": [1, 3, 6, 12],
    "ic_horizons": [1, 3, 6, 12],
    "variants": [
        {"id": "s1_top10", "name": "Stage 1: Top 10, gleich gewichtet", "pick": 10, "rank_by": "stage1", "weighting": "equal"},
        {"id": "s1_top5", "name": "Stage 1: Top 5, gleich gewichtet", "pick": 5, "rank_by": "stage1", "weighting": "equal"},
        {"id": "s12_top5", "name": "Stage 1+2: beste 5 der Top 10 nach Stage-2-Kursscore", "pick": 5, "rank_by": "stage2", "weighting": "equal"},
        {"id": "s12_top10_sw", "name": "Stage 1+2: Top 10, nach Stage-2-Kursscore gewichtet", "pick": 10, "rank_by": "stage2", "weighting": "score"},
        {"id": "s12_top5_sw", "name": "Stage 1+2: beste 5, nach Stage-2-Kursscore gewichtet", "pick": 5, "rank_by": "stage2", "weighting": "score"},
    ],
}

# Fundamentaldaten-Abruf (Yahoo, inoffiziell): Budgets schützen vor Sperren
FUNDAMENTALS = {
    "qs_age_candidates": 1,            # Tage: Stage-1-Kandidaten, Beobachtungsliste
    "qs_age_peers": 3,                 # Momentum-Vergleichsgruppe
    "qs_age_universe": 7,              # übriges Universum (rollierend)
    "ts_age": 45,                      # Jahreswerte
    "qs_calls": 320, "ts_calls": 80,   # normales Tagesbudget
    "qs_calls_boot": 750, "ts_calls_boot": 300,   # Aufbauphase (Abdeckung < 65 %)
    "boot_coverage": 0.65,
    "deadline_s": 900, "deadline_s_boot": 1800,
    "delay_s": 0.35,
}


def stage2_params_hash() -> str:
    payload = json.dumps({"s": STAGE2, "c": STAGE2_CATEGORIES, "m": STAGE2_MIN, "b": STAGE2_BACKTEST}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]

