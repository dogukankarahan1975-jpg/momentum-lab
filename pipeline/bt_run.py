"""Backtests mit damaliger Indexzusammensetzung: S&P 500, DAX-Familie, S&P 500 + DAX, MSCI ACWI (ab 2019).

Erzeugt je Liste eine Datei simulator-<name>.json und eine Übersicht simulators.json für die App.
Das tägliche Screening bleibt davon unberührt.
"""
from __future__ import annotations

import json
import traceback
from pathlib import Path

import pandas as pd

from . import bt_universes as bu
from .backtest import Context
from .core import prepare_panel
from .fx import fx_on_index
from .prices import update_prices
from .universe import SUFFIX_CURRENCY

REFRESH_DAYS = {"sp500": 7, "dax": 28, "acwi": 7}


def _age_ok(store: dict, days: int, today: pd.Timestamp) -> bool:
    f = store.get("fetched")
    return bool(f) and (today - pd.Timestamp(f)).days < days and store.get("months")


# ------------------------------------------------------------------ Quellen laden (mit Zwischenspeicher im Archiv)
def load_sp500(http_get, archive: Path, today, log) -> dict:
    p = bu.store_path(archive, "sp500")
    st = bu.load_store(p)
    if _age_ok(st, REFRESH_DAYS["sp500"], today):
        return st
    try:
        cur, chg = bu.parse_sp500(http_get(bu.WIKI_SP500))
        h = bu.sp500_history(cur, chg, today)
        st = {"fetched": today.strftime("%Y-%m-%d"), **h, "error": None}
        bu.save_store(p, st)
        log(f"[bt-sp500] {len(h['months'])} Monate ab {h['info']['plausible_from']}, {len(chg)} Änderungen")
    except Exception as exc:  # noqa: BLE001
        log(f"[bt-sp500] Fehler: {exc}")
        st = dict(st or {}, error=str(exc)[:200])
    return st


def load_dax(http_get_bytes, http_json, archive: Path, root: Path, universe: pd.DataFrame, today, log) -> dict:
    p = bu.store_path(archive, "dax")
    st = bu.load_store(p)
    names_hist, info = st.get("names"), st.get("info")
    if not _age_ok({"fetched": st.get("fetched"), "months": names_hist}, REFRESH_DAYS["dax"], today):
        try:
            parsed = bu.parse_stoxx_words(bu.pdf_words(http_get_bytes(bu.STOXX_PDF)))
            h = bu.stoxx_history(parsed, today)
            names_hist, info = h["names"], h["info"]
            st.update(fetched=today.strftime("%Y-%m-%d"), names=names_hist, info=info, error=None)
            log(f"[bt-dax] PDF gelesen: {json.dumps(info, ensure_ascii=False)}")
        except Exception as exc:  # noqa: BLE001
            log(f"[bt-dax] Fehler: {exc}")
            st["error"] = str(exc)[:200]
    if not names_hist:
        return {"months": {}, "error": st.get("error") or "keine Daten", "source": "STOXX"}
    # Namen -> Symbole: Korrekturdatei, heutige Liste (deutsche Werte), Yahoo-Suche
    nmap = st.get("name_map", {})
    overrides = bu.read_name_map(root / "config" / "name_map.txt")
    de = universe[universe["symbol"].str.endswith(".DE")] if "symbol" in universe else universe.iloc[0:0]
    by_norm = {bu.norm_name(n)[:10]: s for n, s in zip(de["name"], de["symbol"])}
    all_names = sorted({n for v in names_hist.values() for n in v})
    looked = 0
    for n in all_names:
        k = bu.norm_name(n)
        if k in overrides:
            nmap[n] = overrides[k]
            continue
        if n in nmap:
            continue
        if k[:10] in by_norm:
            nmap[n] = by_norm[k[:10]]
            continue
        if looked >= 150:
            continue
        nmap[n] = bu.yahoo_symbol_for_name(http_json, n)
        looked += 1
    st["name_map"] = nmap
    bu.save_store(p, st)
    rows = bu.dax_rows(names_hist, nmap)
    mapped = sum(1 for n in all_names if nmap.get(n))
    return {"months": rows, "source": "STOXX Historical Index Compositions (PDF)", "error": st.get("error"),
            "info": dict(info or {}, names=len(all_names), names_mapped=mapped)}


def load_acwi(http_get, http_json, http_post_json, archive: Path, universe: pd.DataFrame, today, log) -> dict:
    from .details import sec_headers
    p = bu.store_path(archive, "acwi")
    st = bu.load_store(p)
    filings = st.get("filings", {})
    if not (st.get("fetched") and (today - pd.Timestamp(st["fetched"])).days < REFRESH_DAYS["acwi"]):
        try:
            hdr = sec_headers()
            ser = st.get("series") or bu.find_series(json.loads(http_get(bu.SEC_MF, hdr)), "ACWI")
            if not ser:
                raise ValueError("ACWI nicht in der SEC-Fondsliste")
            cik, series = ser
            accs = bu.parse_atom_filings(http_get(bu.SEC_SERIES_ATOM.format(series=series), hdr))
            new = 0
            for acc in accs:
                if acc in filings:
                    continue
                try:
                    d = bu.parse_nport(http_get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/primary_doc.xml", hdr))
                except Exception as exc:  # noqa: BLE001
                    log(f"[bt-acwi] {acc}: {str(exc)[:100]}")
                    continue
                if d["series"] and d["series"] != series:
                    continue
                filings[acc] = {"date": d["date"], "rows": [[r["isin"], r["name"], r["country"], r["cur"], r["px_usd"]]
                                                            for r in d["rows"]]}
                new += 1
            st.update(fetched=today.strftime("%Y-%m-%d"), series=[cik, series], filings=filings, error=None)
            log(f"[bt-acwi] {len(accs)} N-PORT-Meldungen, {new} neu")
        except Exception as exc:  # noqa: BLE001
            log(f"[bt-acwi] Fehler: {exc}")
            st["error"] = str(exc)[:200]
    # je Stichtag die zuletzt eingereichte Meldung
    by_date = {}
    for acc in sorted(filings):
        f = filings[acc]
        if f.get("date") and len(f["rows"]) > 500:
            by_date[f["date"][:7]] = f["rows"]
    # ISIN -> Symbol: heutige ACWI-Liste (Name), sonst OpenFIGI
    imap = st.get("isin_map", {})
    by_norm = {}
    for n, s in zip(universe.get("name", []), universe.get("symbol", [])):
        by_norm.setdefault(bu.norm_name(n)[:10], s)
    todo, countries = [], {}
    for rows in by_date.values():
        for isin, name, country, _c, _p in rows:
            if isin in imap:
                continue
            k = bu.norm_name(name)[:10]
            if k in by_norm:
                imap[isin] = by_norm[k]
            else:
                todo.append(isin)
                countries[isin] = country
    todo = list(dict.fromkeys(todo))
    if todo and http_post_json is not None:
        got = bu.map_isins_openfigi(http_post_json, todo, countries, log=log)
        imap.update(got)
        log(f"[bt-acwi] OpenFIGI: {len(got)} von {len(todo)} ISIN abgefragt, {sum(1 for v in got.values() if v)} zugeordnet")
    st["isin_map"] = imap
    bu.save_store(p, st)
    months = {m: [[imap[i], n, c, "", px, cur] for i, n, c, cur, px in rows if imap.get(i)
                  and not imap[i].endswith((".SS", ".SZ"))] for m, rows in by_date.items()}
    months = bu.fill_quarterly(months, bu.last_month(today))
    n_isin = len({r[0] for v in by_date.values() for r in v})
    return {"months": months, "source": "SEC Formular N-PORT (iShares MSCI ACWI ETF)", "error": st.get("error"),
            "info": {"filings": len(by_date), "isins": n_isin, "isins_mapped": sum(1 for v in imap.values() if v)}}


# ------------------------------------------------------------------ Backtests
def combine(parts: list[dict]) -> dict:
    keys = set.intersection(*[set(p["months"]) for p in parts]) if parts else set()
    return {m: [r for p in parts for r in p["months"][m]] for m in sorted(keys)}


def run_all(*, http_get, http_json, http_post_json, archive: Path, cache: Path, out: Path, root: Path,
            universe: pd.DataFrame, frames: dict, currency: dict, store, fx: pd.DataFrame, asof, today,
            bench_eur: dict, backfill: list, build_sim_data, sanitize, key_base: str, log=print,
            sources: dict | None = None, price_deadline_s: float = 2400) -> list[dict]:
    if sources is None:
        sources = {
            "sp500": load_sp500(http_get, archive, today, log),
            "dax": load_dax(lambda u: http_get(u, binary=True), http_json, archive, root, universe, today, log),
            "acwi": load_acwi(http_get, http_json, http_post_json, archive, universe, today, log),
        }
    # Kurse für alle (auch ehemalige) Mitglieder
    need = sorted({r[0] for s in sources.values() for rows in s.get("months", {}).values() for r in rows} - set(frames))
    hints = {x: SUFFIX_CURRENCY.get("." + x.split(".", 1)[1] if "." in x else "", "USD") for x in need}
    dead_p = archive / "bt-dead.json"
    dead = json.loads(dead_p.read_text()) if dead_p.exists() else {}
    skip = {x for x, d in dead.items() if (today - pd.Timestamp(d)).days < 60}
    if need and price_deadline_s < 120:
        log("[bt] Zu wenig Zeit für zusätzliche Kurse in diesem Lauf – nächster Lauf holt sie nach")
        need = []
    if need:
        log(f"[bt] Kurse für {len(need)} zusätzliche Symbole ({len(skip & set(need))} zuletzt ohne Kurse übersprungen)")
        res = update_prices(need, store, hints, full_refresh=False, deadline_s=price_deadline_s, log=log,
                            refresh_if_older_days=7, fallback=False, skip=skip)
        for x, s in res.status.items():
            if s.startswith("Fehler: nicht gefunden"):
                dead[x] = today.strftime("%Y-%m-%d")
        dead_p.write_text(json.dumps(dead, separators=(",", ":")))
        frames = {**frames, **res.frames}
        currency = {**currency, **res.currency}
    close_local = {x: df["close"] for x, df in frames.items()}

    def local_per_usd(cur, e):
        if cur in ("USD", "", None):
            return 1.0
        row = fx.loc[:e].iloc[-1]
        return float(row[cur] / row["USD"]) if cur in row and "USD" in row else None

    index = []
    for name, spec in bu.BT_UNIVERSES.items():
        entry = {"key": name, "label": spec["label"], "available": False}
        try:
            parts = [sources[p] for p in spec["providers"]]
            errs = [p.get("error") for p in parts if p.get("error") and not p.get("months")]
            months = combine(parts)
            if not months:
                entry["reason"] = errs[0] if errs else "Keine historischen Listen geladen."
                index.append(entry)
                continue
            valid, vstats = bu.validate_rows(months, close_local, local_per_usd)
            start, cov = bu.coverage_start(months, valid)
            n_months = sum(1 for m in months if start and m >= start)
            entry.update(source=" + ".join(p.get("source", "") for p in parts), validation=vstats,
                         coverage_from=start, months=n_months, info=[p.get("info") for p in parts])
            if not start or n_months < bu.MIN_MONTHS:
                entry["reason"] = (f"Zu wenige Monate, in denen mindestens {bu.MIN_COVERAGE:.0%} der damaligen Mitglieder "
                                   f"Kurse haben ({n_months}).")
                index.append(entry)
                continue
            mem = bu.monthly_membership(months, valid, start)
            syms = sorted({x for v in mem.values() for x in v})
            cov_avg = sum(cov[m] for m in mem) / len(mem)
            entry["coverage_avg"] = round(cov_avg, 3)
            key = f"{key_base}|{name}|{start}|{len(syms)}"
            cpath = cache / f"simulator-{name}.json"
            cached = json.loads(cpath.read_text()) if cpath.exists() else None
            if not cached or cached.get("key") != key:
                adj = pd.concat({x: frames[x]["adj"] for x in syms}, axis=1).sort_index()
                adj = adj[adj.index >= "2000-01-01"]
                close = pd.concat({x: frames[x]["close"] for x in syms}, axis=1).reindex(adj.index)
                vol = pd.concat({x: frames[x]["volume"] for x in syms}, axis=1).reindex(adj.index)
                panel = prepare_panel(adj, close, vol)
                cur = pd.Series({x: currency.get(x) for x in syms})
                ctx = Context(panel, cur, fx, set(), asof, bench_eur, log=log, membership=mem)
                ctx.compute_signals()
                names = {}
                for p in parts:
                    for rows in p["months"].values():
                        for r in rows:
                            names[r[0]] = (r[1], r[2], r[3])
                meta = pd.DataFrame([{"symbol": x, "name": names.get(x, (x,))[0], "country": names.get(x, ("", ""))[1],
                                      "sector": names.get(x, ("", "", ""))[2]} for x in syms]).set_index("symbol")
                pit = {"active": True, "kind": name, "coverage_from": start, "coverage_to": max(mem),
                       "months": len(mem), "symbols_total": len({r[0] for v in months.values() for r in v}),
                       "former_members_used": len(syms), "members_without_prices": vstats.get("no_prices", 0),
                       "coverage_avg": round(cov_avg, 3), "source": entry["source"]}
                sim = build_sim_data(ctx, meta, bench_eur, asof, log=log, backfill=backfill, pit_info=pit)
                sim["key"] = key
                sim["universe"] = {"key": name, "label": spec["label"]}
                sim["notes"]["survivorship"] = (
                    f"Damalige Indexzusammensetzung ({entry['source']}): In jedem Monat nur die Aktien, die damals im "
                    f"Index waren. Im Schnitt {cov_avg:.0%} der damaligen Mitglieder mit Kursen; Firmen ohne Kurse "
                    "(meist Pleiten oder Übernahmen) fehlen.")
                cpath.write_text(json.dumps(sanitize(sim), separators=(",", ":"), ensure_ascii=False, allow_nan=False))
                log(f"[bt] {spec['label']}: ab {start}, {len(syms)} Aktien, Abdeckung {cov_avg:.0%}")
            (out / f"simulator-{name}.json").write_text(cpath.read_text())
            entry.update(available=True, file=f"simulator-{name}.json", symbols=len(syms))
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            entry["reason"] = f"Fehler: {str(exc)[:160]}"
        index.append(entry)
    return index
