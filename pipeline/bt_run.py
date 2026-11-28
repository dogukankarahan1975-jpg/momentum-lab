"""Backtests mit damaliger Indexzusammensetzung: S&P 500, DAX-Familie, S&P 500 + DAX, MSCI ACWI (ab 2019).

Erzeugt je Liste eine Datei simulator-<name>.json und eine Übersicht simulators.json für die App.
Das tägliche Screening bleibt davon unberührt.
"""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path

import pandas as pd

from . import bt_universes as bu
from .backtest import Context
from .core import prepare_panel
from .fx import fx_on_index
from .prices import update_prices
from . import tiingo
from . import audit
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
    errs = []
    cur = None
    for name, getter in (("Wikipedia", lambda: bu.parse_sp500_wiki_current(http_get(bu.WIKI_SP500, bu.WIKI_UA))),
                         ("GitHub-Liste", lambda: bu.parse_sp500_current_csv(http_get(bu.SP500_CUR_CSV)))):
        try:
            cur = getter()
            if len(cur) < 450:
                raise ValueError(f"nur {len(cur)} Zeilen")
            break
        except Exception as exc:  # noqa: BLE001
            cur = None
            errs.append(f"aktuelle Liste {name}: {type(exc).__name__}: {str(exc)[:100]}")
    h = None
    try:
        snaps = bu.parse_sp500_snapshots(http_get(bu.SP500_HIST_CSV))
        h = bu.sp500_from_snapshots(snaps, cur, today)
        if not h["months"]:
            raise RuntimeError(f"Rekonstruktion unplausibel ({h['info']})")
    except Exception as exc:  # noqa: BLE001
        errs.append(f"historische Liste: {type(exc).__name__}: {str(exc)[:120]}")
        h = None
    if h is None:                                   # Ausweichweg: Wikipedia-Änderungstabelle (falls wieder vorhanden)
        for getter in (lambda: http_get(bu.WIKI_SP500, bu.WIKI_UA),
                       lambda: json.loads(http_get(bu.WIKI_SP500_API, bu.WIKI_UA))["parse"]["text"]):
            try:
                c2, chg = bu.parse_sp500(getter())
                h = bu.sp500_history(c2, chg, today)
                if h["months"]:
                    break
                h = None
            except Exception as exc:  # noqa: BLE001
                errs.append(f"Wikipedia-Änderungen: {type(exc).__name__}: {str(exc)[:80]}")
    if h:
        st = {"fetched": today.strftime("%Y-%m-%d"), **h, "error": None, "warnings": errs}
        bu.save_store(p, st)
        log(f"[bt-sp500] {len(h['months'])} Monate, {json.dumps(h['info'])}" + (f" | {errs}" if errs else ""))
    else:
        msg = " | ".join(errs)
        log(f"[bt-sp500] Fehler: {msg}")
        st = dict(st or {}, error=msg[:300])
        bu.save_store(p, dict(st, fetched=None))
    return st


def load_dax(http_get_bytes, http_json, archive: Path, root: Path, universe: pd.DataFrame, today, log,
             deadline: float = float("inf")) -> dict:
    p = bu.store_path(archive, "dax")
    st = bu.load_store(p)
    names_hist, info = st.get("names"), st.get("info")
    if not _age_ok({"fetched": st.get("fetched"), "months": names_hist}, REFRESH_DAYS["dax"], today):
        try:
            raw = http_get_bytes(bu.STOXX_PDF)
            if not raw[:5].startswith(b"%PDF"):
                raise ValueError(f"Antwort ist kein PDF ({len(raw)} Bytes, Anfang {raw[:40]!r})")
            words = bu.pdf_words(raw)
            parsed = bu.parse_stoxx_words(words)
            if not parsed:
                sample = []
                for pg in words[2:4]:
                    sample += [" ".join(w["text"] for w in ln) for ln in bu._lines(pg)][:14]
                st["debug_sample"] = sample
                raise ValueError(f"{len(words)} Seiten, aber keine Indexlisten erkannt. Seite 3: " + " / ".join(sample)[:300])
            h = bu.stoxx_history(parsed, today)
            names_hist, info = h["names"], h["info"]
            st.update(fetched=today.strftime("%Y-%m-%d"), names=names_hist, info=info, error=None)
            log(f"[bt-dax] PDF gelesen: {json.dumps(info, ensure_ascii=False)}")
        except Exception as exc:  # noqa: BLE001
            log(f"[bt-dax] Fehler: {exc}")
            st["error"] = f"{type(exc).__name__}: {str(exc)[:420]}"
    if not names_hist:
        bu.save_store(p, dict(st, fetched=None))
        return {"months": {}, "error": st.get("error") or f"PDF ohne erkennbare Indexlisten ({json.dumps(info or {})[:160]})",
                "source": "STOXX"}
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
        if looked >= 150 or time.time() > deadline - 75 * 60:
            continue
        nmap[n] = bu.yahoo_symbol_for_name(http_json, n)
        looked += 1
    st["name_map"] = nmap
    bu.save_store(p, st)
    rows = bu.dax_rows(names_hist, nmap)
    mapped = sum(1 for n in all_names if nmap.get(n))
    return {"months": rows, "source": "STOXX Historical Index Compositions (PDF)", "error": st.get("error"),
            "info": dict(info or {}, names=len(all_names), names_mapped=mapped)}


def load_acwi(http_get, http_json, http_post_json, archive: Path, universe: pd.DataFrame, today, log,
              deadline: float = float("inf")) -> dict:
    from .details import sec_headers
    p = bu.store_path(archive, "acwi")
    st = bu.load_store(p)
    filings = st.get("filings", {})
    old_fmt = {a for a, f in filings.items() if f.get("rows") and len(f["rows"][0]) < 6}
    if old_fmt or not (st.get("fetched") and (today - pd.Timestamp(st["fetched"])).days < REFRESH_DAYS["acwi"]):
        try:
            hdr = sec_headers()
            ser = st.get("series") or bu.find_series(json.loads(http_get(bu.SEC_MF, hdr)), "ACWI")
            if not ser:
                raise ValueError("ACWI nicht in der SEC-Fondsliste")
            cik, series = ser
            accs = bu.parse_atom_filings(http_get(bu.SEC_SERIES_ATOM.format(series=series), hdr))
            new = 0
            for acc in accs:
                if acc in filings and acc not in old_fmt:   # ältere Speicherung ohne Positionswert -> neu laden
                    continue
                if time.time() > deadline - 70 * 60:
                    log("[bt-acwi] Zeitlimit – restliche Meldungen im nächsten Lauf")
                    break
                try:
                    d = bu.parse_nport(http_get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/primary_doc.xml", hdr))
                except Exception as exc:  # noqa: BLE001
                    log(f"[bt-acwi] {acc}: {str(exc)[:100]}")
                    continue
                if d["series"] and d["series"] != series:
                    continue
                filings[acc] = {"date": d["date"], "rows": [[r["isin"], r["name"], r["country"], r["cur"], r["px_usd"],
                                                             round(r["val_usd"], 2)] for r in d["rows"]]}
                new += 1
            st.update(fetched=today.strftime("%Y-%m-%d"), series=[cik, series], filings=filings, error=None)
            log(f"[bt-acwi] {len(accs)} N-PORT-Meldungen, {new} neu")
        except Exception as exc:  # noqa: BLE001
            log(f"[bt-acwi] Fehler: {exc}")
            st["error"] = str(exc)[:200]
    # vor 2019: N-Q (Quartale 1/3) und N-CSR/N-CSRS (Halbjahres-/Jahresbericht) – einmalig, verteilt auf mehrere Läufe
    NQ_VER = 2                     # 2: Leser korrigiert (Zeilenumbrüche im Quelltext) -> erneut lesen
    if st.get("nq_ver") != NQ_VER:
        st["nq"] = {a: f for a, f in st.get("nq", {}).items() if f.get("rows")}
        st["nq_ver"], st["nq_done"] = NQ_VER, False
    if st.get("series") and not st.get("nq_done"):
        try:
            hdr = sec_headers()
            cik, series = st["series"]
            complete = True
            nq = st.setdefault("nq", {})
            n_new = 0
            for typ in ("N-Q", "N-CSR"):
                try:
                    nq_accs = bu.parse_atom_filings(http_get(bu.SEC_SERIES_ATOM_TYPE.format(series=series, type=typ), hdr))
                except Exception as exc:  # noqa: BLE001
                    log(f"[bt-acwi] {typ}-Liste: {str(exc)[:100]}")
                    complete = False
                    continue
                for acc in nq_accs:
                    if acc in nq or acc in filings:
                        continue
                    if time.time() > deadline - 65 * 60:
                        log("[bt-acwi] Zeitlimit – restliche ältere Meldungen im nächsten Lauf")
                        complete = False
                        break
                    try:
                        items = json.loads(http_get(bu.SEC_INDEX_JSON.format(cik=cik, acc=acc), hdr))["directory"]["item"]
                        docs = sorted((it for it in items if str(it.get("name", "")).lower().endswith((".htm", ".html", ".txt"))
                                       and "ex" not in str(it.get("name", "")).lower().split(".")[0][-6:]
                                       and not str(it.get("name", "")).startswith(acc[:10])),
                                      key=lambda it: -int(str(it.get("size") or 0) or 0))[:3]
                        got = None
                        for it in docs:
                            raw = http_get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{it['name']}", hdr)
                            got = bu.parse_nq_acwi(raw)
                            if got and len(got["rows"]) > 300 and got.get("date"):
                                break
                            got = None
                        nq[acc] = got or {"none": True}
                        n_new += 1 if got else 0
                    except Exception as exc:  # noqa: BLE001
                        log(f"[bt-acwi] {acc}: {str(exc)[:100]}")
            log(f"[bt-acwi] ältere Meldungen (N-Q/N-CSR): {sum(1 for v in nq.values() if v.get('rows'))} mit Bestandsliste, {n_new} neu")
            st["nq_done"] = complete
        except Exception as exc:  # noqa: BLE001
            log(f"[bt-acwi] ältere Meldungen: {exc}")
    # je Stichtag die zuletzt eingereichte Meldung
    by_date = {}
    for acc in sorted(filings):
        f = filings[acc]
        if f.get("date") and len(f["rows"]) > 500 and len(f["rows"][0]) >= 6:
            by_date[f["date"][:7]] = f["rows"]
    # ISIN -> Symbol: heutige ACWI-Liste (Name), sonst OpenFIGI
    imap = st.get("isin_map", {})
    # Zuordnung über den Namen nur bei GLEICHEM vollständigen Namen und GLEICHEM Land (früher: erste 10 Buchstaben –
    # das ordnete z. B. chinesische A-Aktien der H-Aktie oder „National Bank of Greece“ der kanadischen Bank zu)
    by_norm, uni_norm = {}, {}
    for n, sym, isn in zip(universe.get("name", []), universe.get("symbol", []),
                           universe.get("isin", [""] * len(universe))):
        isn = str(isn or "").strip().upper()
        if len(isn) == 12:      # ISIN der heutigen Liste kann aus diesen SEC-Daten stammen -> nur für Name + Land
            by_norm.setdefault((bu.norm_full(n), isn[:2]), sym)      # voller Name (mit Aktienklasse) + Land der ISIN
        uni_norm.setdefault(sym, bu.norm_full(n))
    meta_all, weight_all = {}, {}
    for rows in by_date.values():
        for isin, name, country, cur, px, val in rows:
            meta_all[isin] = (name, cur, country)
            weight_all[isin] = max(weight_all.get(isin, 0.0), val or 0.0)
    todo, countries = [], {}
    for rows in by_date.values():
        for isin, name, country, *_ in rows:
            if isin in imap:
                continue
            k = (bu.norm_full(name), str(isin)[:2])
            if k in by_norm:
                imap[isin] = by_norm[k]
            else:
                todo.append(isin)
                countries[isin] = country
    # alte Doppelzuordnungen (ein Kürzel für mehrere ISIN) auflösen und die übrigen ISIN neu bei OpenFIGI abfragen
    if st.get("imap_ver", 1) < 2:
        losers = bu.dedupe_isin_map(imap, meta_all, uni_norm, weight_all)
        for i in losers:
            imap.pop(i, None)
            st.get("yahoo_isin", {}).pop(i, None)
            todo.append(i)
            countries[i] = meta_all[i][2]
        log(f"[bt-acwi] Doppelzuordnungen aufgelöst: {len(losers)} ISIN werden neu zugeordnet")
        st["imap_ver"] = 2
    todo = list(dict.fromkeys(todo))
    if todo and http_post_json is not None:
        got = bu.map_isins_openfigi(http_post_json, todo, countries, log=log)
        imap.update(got)
        log(f"[bt-acwi] OpenFIGI: {len(got)} von {len(todo)} ISIN abgefragt, {sum(1 for v in got.values() if v)} zugeordnet")
    # Prüfpfad: verdächtige oder kurslose Zuordnungen über die Yahoo-Suche (ISIN, Heimatbörse) neu bestimmen
    try:
        dead = set(json.loads((archive / "bt-dead.json").read_text())) if (archive / "bt-dead.json").exists() else set()
        badp = archive / "bt-acwi-bad.json"
        bad = set(json.loads(badp.read_text())) if badp.exists() else set()
        yl = st.setdefault("yahoo_isin", {})
        meta, weight = {}, {}
        for rows in by_date.values():
            for isin, name, country, cur, px, val in rows:
                meta[isin] = (cur, country)
                weight[isin] = max(weight.get(isin, 0.0), val or 0.0)
        sus = [i for i in meta if i not in yl and not (imap.get(i) or "").endswith((".SS", ".SZ"))
               and (imap.get(i) or meta[i][1] != "CN")
               and (bu.suspicious_symbol(imap.get(i), *meta[i]) or imap.get(i) in dead or imap.get(i) in bad)]
        sus.sort(key=lambda i: -weight.get(i, 0.0))
        n_fix = 0
        for i in sus[:600]:
            if time.time() > deadline - 52 * 60:
                break
            sym = bu.yahoo_symbol_for_isin(http_json, i, *meta[i]) if http_json else None
            yl[i] = sym or ""
            n_fix += 1 if sym and sym != imap.get(i) else 0
            time.sleep(0.3)
        for i, sym in yl.items():
            if sym:
                imap[i] = sym
        # danach darf kein Kürzel mehr zu zwei ISIN gehören (sonst springt das Kursverhältnis -> „unstimmig“)
        for i in bu.dedupe_isin_map(imap, meta_all, uni_norm, weight_all):
            imap[i] = ""
        if sus:
            log(f"[bt-acwi] Yahoo-Suche: {min(len(sus), 600)} verdächtige Zuordnungen geprüft, {n_fix} korrigiert, "
                f"{max(0, len(sus) - 600)} offen")
    except Exception as exc:  # noqa: BLE001
        log(f"[bt-acwi] Yahoo-Suche: {exc}")
    st["isin_map"] = imap
    bu.save_store(p, st)
    # nicht zuordenbare ISIN zählen als fehlende Mitglieder (außer vermutlich China-A, die bewusst ausgeschlossen sind)
    ref = {m: [[imap.get(i), n, c, "", px, cur, val] for i, n, c, cur, px, val in rows
               if not (imap.get(i) or "").endswith((".SS", ".SZ")) and (imap.get(i) or c != "CN")]
           for m, rows in by_date.items()}
    # ältere Meldungen (vor der ersten N-PORT-Meldung): Zuordnung über den exakten Namen
    nport_start = min(by_date) if by_date else None
    nq_info = {"filings": 0, "rows": 0, "mapped": 0, "weight_mapped": 0.0}
    if nport_start:
        idx = bu.build_name_index([r for rows in by_date.values() for r in rows], [])
        idx["first"], idx["w"] = {}, {}
        for m in sorted(by_date):
            for r in by_date[m]:
                idx["first"].setdefault(r[0], m)
                idx["w"][r[0]] = max(idx["w"].get(r[0], 0.0), r[5] or 0.0)
        uni_idx = bu.build_name_index([[sym, n, bu.COUNTRY_ISO.get(str(c).upper(), "")] for sym, n, c in
                                       zip(universe.get("symbol", []), universe.get("name", []),
                                           universe.get("country", [""] * len(universe)))], [])
        wt_all = wt_map = 0.0
        for acc, f in sorted(st.get("nq", {}).items(), key=lambda kv: (kv[1].get("date") or "")):
            if not f.get("rows") or not f.get("date") or f["date"][:7] >= nport_start:
                continue
            out, used = [], set()
            for name, cc, shares, val in f["rows"]:
                isin = bu.match_name(idx, name, cc)
                sym = imap.get(isin) if isin else None
                if not sym:
                    sym = bu.match_name(uni_idx, name, cc)
                if sym and sym.endswith((".SS", ".SZ")):
                    continue
                if sym in used:          # ein Kürzel nur einmal je Meldung (sonst zwei verschiedene Kurse)
                    sym = None
                used.add(sym)
                out.append([sym, name, cc, "", val / shares, "USD", round(val, 2)])
                wt_all += val
                wt_map += val if sym else 0.0
            ref[f["date"][:7]] = out
            nq_info["filings"] += 1
            nq_info["rows"] += len(out)
            nq_info["mapped"] += sum(1 for r in out if r[0])
        nq_info["weight_mapped"] = round(wt_map / wt_all, 3) if wt_all else 0.0
    months = bu.fill_quarterly(ref, bu.last_month(today))
    n_isin = len({r[0] for v in by_date.values() for r in v})
    src = "SEC-Meldungen des iShares MSCI ACWI ETF (N-PORT ab 2019" + (", davor N-Q/N-CSR)" if nq_info["filings"] else ")")
    return {"months": months, "ref_months": ref, "source": src, "error": st.get("error"), "nport_start": nport_start,
            "info": {"filings": len(by_date), "isins": n_isin, "isins_mapped": sum(1 for v in imap.values() if v),
                     "older_filings": nq_info["filings"], "older_rows": nq_info["rows"],
                     "older_mapped": nq_info["mapped"], "older_weight_mapped": nq_info["weight_mapped"]}}


# ------------------------------------------------------------------ Backtests
def combine(parts: list[dict], key: str = "months") -> dict:
    ms = [p.get(key) if p.get(key) is not None else p.get("months", {}) for p in parts]
    keys = set.intersection(*[set(m) for m in ms]) if ms else set()
    return {m: [r for x in ms for r in x[m]] for m in sorted(keys)}


def run_all(*, http_get, http_json, http_post_json, archive: Path, cache: Path, out: Path, root: Path,
            universe: pd.DataFrame, frames: dict, currency: dict, store, fx: pd.DataFrame, asof, today,
            bench_eur: dict, backfill: list, build_sim_data, sanitize, key_base: str, log=print,
            sources: dict | None = None, price_deadline_s: float = 2400,
            deadline: float = float("inf")) -> list[dict]:
    """deadline: späteste Uhrzeit (time.time()), zu der dieser Teil fertig sein muss. Alles, was danach noch
    anstünde, wird auf den nächsten Lauf verschoben – so bleibt der ganze GitHub-Lauf sicher unter seinem Limit."""
    left = lambda: deadline - time.time()  # noqa: E731
    if sources is None:
        sources = {}
        for key, fn in (("sp500", lambda: load_sp500(http_get, archive, today, log)),
                        ("acwi", lambda: load_acwi(http_get, http_json, http_post_json, archive, universe, today, log,
                                                   deadline=deadline)),
                        ):                 # DAX-Familie auf Wunsch entfernt (Namenszuordnung zu unzuverlässig)
            if left() < 60 * 60:
                log(f"[bt] {key}: Zeitlimit – Liste wird im nächsten Lauf geladen")
                st = bu.load_store(bu.store_path(archive, key)) or {}
                sources[key] = {"months": st.get("months", {}) if key == "sp500" else {},
                                "error": "Zeit hat in diesem Lauf nicht gereicht – nächster Lauf"}
                continue
            sources[key] = fn()
    price_deadline_s = max(0.0, min(price_deadline_s, left() - 40 * 60))
    # Kurse für alle (auch ehemalige) Mitglieder
    need = sorted({r[0] for s in sources.values() for rows in s.get("months", {}).values() for r in rows if r[0]} - set(frames))
    hints = {x: SUFFIX_CURRENCY.get("." + x.split(".", 1)[1] if "." in x else "", "USD") for x in need}
    dead_p = archive / "bt-dead.json"
    dead = json.loads(dead_p.read_text()) if dead_p.exists() else {}
    skip = {x for x, d in dead.items() if (today - pd.Timestamp(d)).days < 60}
    tarc = tiingo.TiingoArchive(archive.parent)
    skip |= tarc.have()          # schon von Tiingo geladen -> nicht bei Yahoo (evtl. neu vergebenes Kürzel) suchen
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
    # US-Aktien ohne Yahoo-Kurse (Pleiten/Übernahmen): Tiingo, falls Schlüssel hinterlegt (nur S&P 500)
    us_hist = sorted({r[0] for r in (x for rows in sources.get("sp500", {}).get("months", {}).values() for x in rows)
                      if r[0] and "." not in r[0]} - set(frames))
    tinfo = {}
    if us_hist:
        try:
            tframes, tinfo = tiingo.fill_missing(us_hist, archive.parent, today, log=log,
                                                 deadline=min(deadline - 30 * 60, time.time() + 8 * 60))
            frames = {**frames, **tframes}
            currency = {**currency, **{x: "USD" for x in tframes}}
        except Exception as exc:  # noqa: BLE001
            log(f"[tiingo] Fehler: {type(exc).__name__}: {exc}")
    close_local = {x: df["close"] for x, df in frames.items()}

    def local_per_usd(cur, e):
        if cur in ("USD", "", None):
            return 1.0
        row = fx.loc[:e].iloc[-1]
        return float(row[cur] / row["USD"]) if cur in row and "USD" in row else None

    index = []
    audit_mem: dict = {}
    order = ["acwi", "dax", "sp500", "spdax"]
    for name, spec in sorted(bu.BT_UNIVERSES.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 9):
        entry = {"key": name, "label": spec["label"], "available": False}
        try:
            parts = [sources[p] for p in spec["providers"]]
            errs = [p.get("error") or "keine Daten" for p in parts if not p.get("months")]
            months = combine(parts)
            if not months:
                entry["reason"] = errs[0] if errs else "Keine historischen Listen geladen."
                index.append(entry)
                continue
            refm = combine(parts, "ref_months") if any(p.get("ref_months") for p in parts) else None
            if refm:   # Yahoo-Kurse sind in der Handelswährung des Symbols -> mit dieser umrechnen, nicht mit curCd
                refm = {m: [r[:5] + [currency.get(r[0]) or r[5]] + r[6:] if r[0] else r for r in rows]
                        for m, rows in refm.items()}
            cut = next((p.get("nport_start") for p in parts if p.get("nport_start")), None)
            early = {}
            if refm and cut and any(m < cut for m in refm):
                bad, early = bu.bad_early_mappings(refm, close_local, local_per_usd, cut)
                if bad:   # über den Namen zugeordnet, aber Kurs passt nicht -> vor `cut` als nicht zugeordnet behandeln
                    fix = lambda rows: [[None] + r[1:] if r[0] in bad else r for r in rows]  # noqa: E731
                    months = {m: (fix(rows) if m < cut else rows) for m, rows in months.items()}
                    refm = {m: (fix(rows) if m < cut else rows) for m, rows in refm.items()}
            months_raw = months
            months, epi = bu.episode_filter(months, close_local)
            valid, vstats = bu.validate_rows(months, close_local, local_per_usd, ref_months=refm)
            vstats.update(early)
            vstats.update(epi)
            if name == "acwi":   # nicht bestandene Symbole merken -> nächster Lauf sucht sie per ISIN neu
                members = {r[0] for rows in months.values() for r in rows if r[0]}
                archive.mkdir(parents=True, exist_ok=True)
                (archive / "bt-acwi-bad.json").write_text(json.dumps(sorted(members - valid)))
            start, cov = bu.coverage_start(months, valid)
            ccov = bu.count_coverage(months, valid)
            try:      # Warum beginnt die Testreihe nicht früher? Monat davor aufschlüsseln (für App und Prüfbericht)
                entry["coverage_gap"] = bu.coverage_gap(months_raw, months, valid, cov, start, close_local)
                entry["coverage_by_year"] = {y: round(min(v for m, v in cov.items() if m[:4] == y), 3)
                                             for y in sorted({m[:4] for m in cov})}
            except Exception as exc:  # noqa: BLE001
                log(f"[bt-{name}] Lückenanalyse: {exc}")
            weighted = any(len(r) > 6 for rows in months.values() for r in rows[:1])
            n_months = sum(1 for m in months if start and m >= start)
            if "sp500" in spec["providers"] and tinfo:
                entry["tiingo"] = {k: tinfo.get(k) for k in ("key", "stored", "open")}
            entry.update(source=" + ".join(p.get("source", "") for p in parts), validation=vstats,
                         coverage_from=start, months=n_months, info=[p.get("info") for p in parts])
            if months:
                lm = max(months)
                entry["coverage_last"] = {"month": lm, "share": round(cov[lm], 3), "count_share": round(ccov[lm], 3),
                                          "by_weight": weighted}
            dinfo = next((p.get("info") for p in parts if isinstance(p.get("info"), dict) and "names_mapped" in p["info"]), None)
            if dinfo and dinfo.get("names") and dinfo.get("names_mapped", 0) / dinfo["names"] < 0.9:
                entry["reason"] = (f"DAX-Namen erst zu {dinfo['names_mapped'] / dinfo['names']:.0%} Kurskürzeln zugeordnet "
                                   "(nötig 90 %) – gesperrt, bis die geprüfte Namensliste fertig ist.")
                index.append(entry)
                continue
            stale = bool(months) and max(months) < (pd.Timestamp(bu.last_month(today) + "-01") - pd.DateOffset(months=2)).strftime("%Y-%m")
            if stale:
                entry["reason"] = f"Indexliste endet {max(months)} statt im letzten Monat – gesperrt, bis das behoben ist."
                index.append(entry)
                continue
            if not start or n_months < bu.MIN_MONTHS:
                what = "des damaligen Indexgewichts" if weighted else "der damaligen Mitglieder"
                low = min(cov.values()) if cov else 0
                entry["reason"] = (f"Zu wenige Monate, in denen mindestens {bu.MIN_COVERAGE:.0%} {what} "
                                   f"Kurse haben ({n_months}; niedrigster Monat {low:.0%}, "
                                   f"geprüft {vstats.get('ok', 0)} ok / {vstats.get('no_prices', 0)} ohne Kurse / "
                                   f"{vstats.get('mismatch', 0)} unstimmig).")
                index.append(entry)
                continue
            mem = bu.monthly_membership(months, valid, start)
            syms = sorted({x for v in mem.values() for x in v})
            cov_avg = sum(cov[m] for m in mem) / len(mem)
            ccov_avg = sum(ccov[m] for m in mem) / len(mem)
            entry["coverage_avg"] = round(cov_avg, 3)
            entry["coverage_count_avg"] = round(ccov_avg, 3)
            entry["coverage_by_weight"] = weighted
            key = f"{key_base}|{name}|{start}|{len(syms)}"
            cpath = cache / f"simulator-{name}.json"
            cached = json.loads(cpath.read_text()) if cpath.exists() else None
            if (not cached or cached.get("key") != key) and left() < 15 * 60:
                if cached:
                    log(f"[bt] {name}: Zeitlimit – Ergebnis vom letzten Lauf wird weiter gezeigt")
                    key = cached.get("key")
                else:
                    raise TimeoutError("Zeit hat in diesem Lauf nicht gereicht – wird im nächsten Lauf berechnet")
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
                       "coverage_avg": round(cov_avg, 3), "coverage_count_avg": round(ccov_avg, 3),
                       "coverage_by_weight": weighted, "source": entry["source"]}
                sim = build_sim_data(ctx, meta, bench_eur, asof, log=log, backfill=backfill, pit_info=pit)
                sim["key"] = key
                sim["universe"] = {"key": name, "label": spec["label"]}
                sim["notes"]["survivorship"] = (
                    f"Damalige Indexzusammensetzung ({entry['source']}): In jedem Monat nur die Aktien, die damals im "
                    f"Index waren. Im Schnitt {ccov_avg:.0%} der damaligen Mitglieder mit Kursen"
                    + (f" ({cov_avg:.0%} des Indexgewichts)" if weighted else "")
                    + "; Firmen ohne Kurse (meist Pleiten, Übernahmen oder kleine Schwellenland-Werte) fehlen.")
                cpath.write_text(json.dumps(sanitize(sim), separators=(",", ":"), ensure_ascii=False, allow_nan=False))
                log(f"[bt] {spec['label']}: ab {start}, {len(syms)} Aktien, Abdeckung {cov_avg:.0%}")
            (out / f"simulator-{name}.json").write_text(cpath.read_text())
            entry.update(available=True, file=f"simulator-{name}.json", symbols=len(syms))
            audit_mem[name] = {m: sorted(v) for m, v in mem.items()}
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            entry["reason"] = (str(exc) if isinstance(exc, TimeoutError) else f"Fehler: {str(exc)[:160]}")
        index.append(entry)
    # Prüfbericht (archive/audit/latest.json): Simulator auf echten Daten, Kursvergleich, Ausreißer
    try:
        if left() > 8 * 60 and store is not None:
            rep = {"generated": pd.Timestamp.utcnow().strftime("%Y-%m-%dT%H:%MZ"), "universes": {}}
            files = {**{n: out / f"simulator-{n}.json" for n in audit_mem}, "current": out / "simulator.json"}
            for n, f in files.items():
                if not f.exists():
                    continue
                res = audit.run_node_audit(root, f, audit_mem.get(n), cache, log=log)
                rep["universes"][n] = {"simulator": res, "anomalies": audit.anomalies(json.loads(f.read_text()))}
                ent = next((e for e in index if e["key"] == n), {})
                for k in ("coverage_from", "coverage_gap", "coverage_by_year", "validation"):
                    if ent.get(k) is not None:
                        rep["universes"][n][k] = ent[k]
                if res and "failed" in res:
                    log(f"[audit] {n}: {res['checks']} Prüfungen, {res['failed']} mit Befund")
                    for e in index:
                        if e["key"] == n:
                            e["audit"] = {"checks": res["checks"], "failed": res["failed"]}
            rep["prices"] = audit.price_crosscheck(frames, archive.parent, today, log=log)
            try:
                sim_any = next((f for f in files.values() if f.exists()), None)
                if sim_any is not None:
                    rep["etf_lines"] = audit.etf_crosscheck(json.loads(sim_any.read_text()), fx, archive.parent)
                    for e in index:
                        e["etf_check"] = rep["etf_lines"]
                    for r in rep["etf_lines"]:
                        log(f"[audit] ETF {r['line']}: unsere Linie {r['cagr_ours_pct']} % p. a. vs. {r['reference']} "
                            f"{r['cagr_reference_pct']} % p. a. ({r['from']}–{r['to']})")
            except Exception as exc:  # noqa: BLE001
                log(f"[audit] ETF-Vergleich: {exc}")
            for e in index:
                if e["key"] in rep["universes"]:
                    e.setdefault("audit", {})["anomalies"] = len(rep["universes"][e["key"]]["anomalies"])
            audit.write_report(archive.parent, rep)
    except Exception as exc:  # noqa: BLE001
        log(f"[audit] Fehler: {exc}")
    keys = list(bu.BT_UNIVERSES)
    return sorted(index, key=lambda e: keys.index(e["key"]) if e["key"] in keys else 99)
