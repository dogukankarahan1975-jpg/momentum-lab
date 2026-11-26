"""Stage 2 v2 – Fortsetzungs-Rangfolge (Methodik S2 v2.0.0).

Ziel (Vorgabe des Nutzers): Unter den Stage-1-Kandidaten (Top 10) diejenigen finden, bei denen das Momentum am
ehesten weiterläuft. Stage 2 schließt nichts aus und vergibt keine Kauf-/Verbotsurteile, sondern sortiert die Top 10
nach Signalen, für die es Forschung zur Fortsetzung von Momentum gibt. Gekauft werden die besten 5.

Kursteil (rückwirkend testbar, im Simulator verwendet):
  info_disc  gleichmäßiger statt sprunghafter Anstieg (Frog-in-the-Pan)  Da, Gurun & Warachka (2014)
  prox_52w   Nähe zum 52-Wochen-Hoch                                     George & Hwang (2004)
  resid_mom  marktbereinigtes Momentum ggü. MSCI World                   Blitz, Huij & Martens (2011)
Gewinnteil (nur live, keine kostenlose Historie):
  rev90      Änderung der EPS-Schätzung über 90 Tage                     Chan, Jegadeesh & Lakonishok (1996)
  breadth30  Anteil Anhebungen minus Senkungen der Schätzungen (30 Tage)  Chan, Jegadeesh & Lakonishok (1996)
  surprise4  Gewinnüberraschung, Ø der letzten 4 Quartale              Bernard & Thomas (1989)

Jede Kennzahl wird als Perzentil gegen die Momentum-Vergleichsgruppe (alle Stage-1-Kandidaten im besten Zehntel)
gemessen. Kursteil = Mittel der Kurs-Perzentile (mind. 2 von 3), Gewinnteil = Mittel der Gewinn-Perzentile (mind. 1).
Score = 10 × (½ Kursteil + ½ Gewinnteil); ohne Gewinndaten 10 × Kursteil (gekennzeichnet). Keine Imputation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import stage2
from .config import STAGE2

S2V2_VERSION = "2.0.0"
TOP_N = 5

SIGNALS = [
    {"key": "info_disc", "label": "Gleichmäßiger Anstieg statt Sprünge", "dir": -1, "part": "kurs",
     "study": "Da, Gurun & Warachka (2014), Frog in the Pan",
     "why": "Momentum, das aus vielen kleinen Schritten entsteht, läuft länger weiter als Momentum aus wenigen großen Sprüngen."},
    {"key": "prox_52w", "label": "Nähe zum 52-Wochen-Hoch", "dir": 1, "part": "kurs",
     "study": "George & Hwang (2004), The 52-Week High and Momentum Investing",
     "why": "Aktien nahe ihrem Jahreshoch setzen ihren Trend im Schnitt eher fort; Anleger reagieren dort zu zögerlich auf gute Nachrichten."},
    {"key": "resid_mom", "label": "Stärke gegenüber dem Gesamtmarkt", "dir": 1, "part": "kurs",
     "study": "Blitz, Huij & Martens (2011), Residual Momentum",
     "why": "Momentum, das nicht nur vom steigenden Gesamtmarkt kommt, ist stabiler und bricht seltener ein."},
    {"key": "rev90", "label": "Gewinnschätzungen steigen (90 Tage)", "dir": 1, "part": "gewinn",
     "study": "Chan, Jegadeesh & Lakonishok (1996), Momentum Strategies",
     "why": "Steigende Gewinnerwartungen der Analysten stützen den Kursanstieg und sagen weitere Überrendite voraus."},
    {"key": "breadth30", "label": "Mehr Anhebungen als Senkungen (30 Tage)", "dir": 1, "part": "gewinn",
     "study": "Chan, Jegadeesh & Lakonishok (1996)",
     "why": "Wenn viele Analysten gleichzeitig anheben, ist die Verbesserung breit getragen."},
    {"key": "surprise4", "label": "Gewinne über den Erwartungen (Ø 4 Quartale)", "dir": 1, "part": "gewinn",
     "study": "Bernard & Thomas (1989), Post-Earnings-Announcement Drift",
     "why": "Nach positiven Gewinnüberraschungen steigen Aktien im Schnitt noch über Monate weiter."},
]
KURS = [s["key"] for s in SIGNALS if s["part"] == "kurs"]
GEWINN = [s["key"] for s in SIGNALS if s["part"] == "gewinn"]


def _pct(values: pd.Series, x: float, direction: int) -> float | None:
    v = values.dropna()
    if not np.isfinite(x) or len(v) < 10:
        return None
    if direction < 0:
        v, x = -v, -x
    return float(((v < x).sum() + 0.5 * (v == x).sum()) / len(v))


def continuation_scores(metrics: pd.DataFrame, peers: list[str], targets: list[str], use_gewinn: bool = True) -> pd.DataFrame:
    """Perzentile gegen die Vergleichsgruppe und Score je Ziel-Aktie."""
    peer = metrics.reindex(peers)
    rows = {}
    for s in targets:
        r = {"symbol": s}
        for sig in SIGNALS:
            if sig["part"] == "gewinn" and not use_gewinn:
                continue
            k = sig["key"]
            val = metrics.at[s, k] if (s in metrics.index and k in metrics.columns) else np.nan
            val = float(val) if val is not None and np.isfinite(val) else np.nan
            r[f"v_{k}"] = None if not np.isfinite(val) else val
            r[f"p_{k}"] = _pct(peer[k], val, sig["dir"]) if k in peer.columns else None
        kp = [r.get(f"p_{k}") for k in KURS if r.get(f"p_{k}") is not None]
        gp = [r.get(f"p_{k}") for k in GEWINN if r.get(f"p_{k}") is not None] if use_gewinn else []
        kurs = float(np.mean(kp)) if len(kp) >= 2 else None
        gew = float(np.mean(gp)) if len(gp) >= 1 else None
        r["kurs"] = kurs
        r["gewinn"] = gew
        if kurs is None:
            r["score"] = None
        elif gew is None:
            r["score"] = 10 * kurs
        else:
            r["score"] = 10 * (0.5 * kurs + 0.5 * gew)
        r["price_only"] = gew is None
        rows[s] = r
    df = pd.DataFrame.from_dict(rows, orient="index")
    if not len(df):
        return df
    df["rank"] = df["score"].rank(ascending=False, method="first")
    return df


def peer_group(sc: pd.DataFrame, f: pd.DataFrame, elig: pd.Series, pool: list[str]) -> list[str]:
    peers = list(pool)
    if len(peers) < STAGE2["peer_min_n"]:
        pct = sc["pct"]
        peers = [s for s in elig[elig].index if np.isfinite(pct.get(s, np.nan)) and pct[s] <= STAGE2["peer_fallback_pct"]]
    return peers


def _f(x, nd=4):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if np.isfinite(x) else None


def run_stage2_v2(*, loc, eur, mkt, market_name, asof, today, meta, stage1: pd.DataFrame, cands: list, peers: list,
                  store, fx_row, snap90=None, demo=False, sources=None, fund_stats=None) -> dict:
    cands = list(cands)[:10]
    cols = list(dict.fromkeys(list(peers) + cands))
    cols = [c for c in cols if c in loc.columns]
    pm, market = stage2.price_metrics_at(loc[cols], eur[[c for c in cols if c in eur.columns]], mkt, asof)
    pm["trend_status"] = [stage2.trend_status(pm.loc[s]) for s in pm.index]
    fm = stage2.fundamental_metrics(store, cols, today, fx_row, snap90)
    metrics = pm.join(fm[[c for c in fm.columns if c in GEWINN or c in ("fund_at", "fund_age", "next_earnings")]], how="left")
    sc = continuation_scores(metrics, peers, cands, use_gewinn=True)
    ranking = []
    order = sc.sort_values(["score"], ascending=False, na_position="last").index.tolist() if len(sc) else []
    for i, s in enumerate(order, 1):
        r = sc.loc[s]
        signals = []
        for sig in SIGNALS:
            signals.append({"key": sig["key"], "label": sig["label"], "part": sig["part"],
                            "value": _f(r.get(f"v_{sig['key']}")), "pct": _f(r.get(f"p_{sig['key']}"), 3)})
        flags = []
        ts = metrics.at[s, "trend_status"] if s in metrics.index else None
        if ts == "Trendbruch":
            flags.append("Trendbruch: Kurs unter der 200-Tage-Linie bzw. 50- unter 200-Tage-Linie")
        ne = metrics.at[s, "next_earnings"] if "next_earnings" in metrics.columns and s in metrics.index else None
        if isinstance(ne, str) and ne:
            try:
                d = (pd.Timestamp(ne) - today).days
                if 0 <= d <= STAGE2["event_window_days"]:
                    flags.append(f"Quartalszahlen in {d} Tagen ({ne}): kurzfristig größere Schwankung möglich")
            except Exception:  # noqa: BLE001
                pass
        st1 = stage1.loc[s] if s in stage1.index else None
        ranking.append({
            "symbol": s, "name": str(meta["name"].get(s, s)), "sector": str(meta["sector"].get(s, "") or ""),
            "stage1": {"rank": None if st1 is None or not np.isfinite(st1["rank"]) else int(st1["rank"]),
                       "score": _f(st1["Z"], 3) if st1 is not None else None},
            "stage2": {"rank": i, "score": _f(r["score"], 3), "score_display": None if r["score"] is None else round(float(r["score"]), 1),
                       "kurs": _f(r["kurs"], 3), "gewinn": _f(r["gewinn"], 3), "price_only": bool(r["price_only"])},
            "buy": i <= TOP_N and r["score"] is not None,
            "signals": signals, "flags": flags,
            "fund_at": metrics.at[s, "fund_at"] if "fund_at" in metrics.columns and s in metrics.index else None,
        })
    msgs = []
    n_price_only = sum(1 for x in ranking if x["stage2"]["price_only"])
    if n_price_only:
        msgs.append({"level": "info", "text": f"{n_price_only} von {len(ranking)} Kandidaten ohne aktuelle Analystendaten: "
                                              "ihr Score beruht nur auf dem Kursteil."})
    if not ranking:
        msgs.append({"level": "info", "text": "Keine Stage-1-Kandidaten, deshalb keine Stage-2-Rangfolge."})
    return {
        "schema": 2, "stage2_version": S2V2_VERSION, "status": "ok" if ranking else "leer", "demo": demo,
        "asof": asof.strftime("%Y-%m-%d"), "top_n": TOP_N, "market": market_name,
        "method": {"signals": SIGNALS, "peers": len(peers),
                   "rule": "Score = 10 × (½ Kursteil + ½ Gewinnteil), jeweils Mittel der Perzentile gegen die "
                           "Momentum-Vergleichsgruppe; ohne Analystendaten nur Kursteil. Gekauft werden die 5 besten."},
        "ranking": ranking, "buy": [x["symbol"] for x in ranking if x["buy"]],
        "messages": msgs, "sources": sources or {}, "fundamentals_fetch": fund_stats or {},
    }
