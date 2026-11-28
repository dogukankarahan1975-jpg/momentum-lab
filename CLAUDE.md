# Momentum Lab – Regeln für Claude

Kostenlose iPhone-Web-App (PWA) für Momentum-Investing: Screening (MSCI ACWI und S&P 500), Top 10, Depot,
Signale, Backtest/Simulator. Daten rechnet eine Python-Pipeline in GitHub Actions, die App liegt auf GitHub Pages.
Eigentümer: Dogu (arbeitet im Bankwesen, technisch versiert, nutzt die App am iPhone).

## Verbindliche Regeln (vom Eigentümer festgelegt)

- **Nur kostenlose Lösungen.** Wenn etwas nicht wirklich kostenlos, dauerhaft oder zuverlässig machbar ist:
  VOR der Umsetzung sagen und den Kompromiss erklären. Nie behaupten, etwas sei kostenlos, wenn später Kosten
  drohen. Keine kostenpflichtigen API-Keys.
- **Nichts erfinden:** keine Scores, Gewichtungen, Schwellenwerte oder historischen Daten ohne Beleg.
  Jede Regel braucht eine Quelle oder eine nachvollziehbare Begründung (siehe docs/METHODIK.md).
- **Unsichere Daten → keine scheinbar sichere Empfehlung.** Lieber „keine Bewertung“ oder „nicht verfügbar“
  als ein falsches Signal. Datenlücken sichtbar machen, nicht glätten.
- **Kein fragwürdiges Scraping**, keine unzulässigen Zugriffe. Nutzungsbedingungen der Quellen beachten
  (Tiingo-Gratisplan: nur private Nutzung, Grenzen siehe pipeline/tiingo.py).
- **Depot bleibt lokal** (IndexedDB im Browser): keine Bankzugänge, keine Bankverbindung, keine sensiblen Daten
  versenden, Backup-Export/-Import erhalten, regelmäßiges Backup empfehlen, nie Daten ohne Zustimmung löschen.
- **Keine Anlageberatung.** Bei Aussagen zu Strategien/Aktien immer „Das ist keine Anlageberatung.“
- **Secrets:** Der Tiingo-Schlüssel liegt nur im GitHub-Secret `TIINGO_API_KEY`. Nie ausgeben, loggen oder
  in Dateien schreiben.

## Kommunikation mit dem Eigentümer

- Immer **Deutsch**, kurz und handyfreundlich.
- **Immer exakt sagen, was er antippen muss** (z. B. „Actions → Momentum Lab → Run workflow → Run workflow“).
- Ehrlich über Grenzen: was getestet ist, was nur mit Demodaten geprüft wurde, was erst der echte Lauf zeigt.
- Fehler offen zugeben und beheben.

## Aufbau

- `pipeline/` – Python: Universum (iShares-Listen), Kurse (Yahoo), Screening (Stage 1 Momentum, Stage 2),
  Backtest-Mitglieder zum Stichtag (`bt_universes.py`, `bt_run.py`: S&P 500 über fja05680-Snapshots,
  ACWI über SEC N-PORT/N-Q), Tiingo-Kursarchiv, Prüfbericht (`audit.py`), Simulator-Daten (`simulator.py`).
  Einstieg: `python -m pipeline.run --mode live|demo`.
- `app/` – App ohne Build-Schritt (ES-Module). Simulator-Logik: `app/js/simulator.js`
  (Steuern: 26,375 %, Pauschbetrag, Aktien-Verlusttopf, Vorabpauschale, 30 % Teilfreistellung).
- `tools/` – `install_package.py` (alter Zip-Weg), `audit_sim.mjs` (unabhängige Nachrechnung), `build_site.py`.
- `archive/` – vom Workflow gepflegte Historie (Universen, Tiingo-Kurse, `audit/latest.json` = Prüfbericht).
  Nicht von Hand ändern.
- `docs/` – METHODIK, DATENQUELLEN, PRUEFBERICHT, `workflow/momentum-lab.yml` (Kopie des Workflows).
- `CHANGELOG.md` – jede Änderung mit Version (`PIPELINE_VERSION` in `pipeline/config.py` hochzählen).

## Vor jedem Commit

```bash
python -m pytest -q tests          # Python-Tests
node tests/js/run.mjs              # App-/Simulator-Tests (u. a. handgerechnete Steuerfälle)
```
Für Pipeline-Änderungen zusätzlich einen Demo-Lauf:
`python -m pipeline.run --mode demo --out /tmp/site/data --cache /tmp/cache --archive /tmp/archive`.
Neue Rechenregeln brauchen einen Test mit von Hand nachgerechnetem Ergebnis.

## Zeit- und Mengengrenzen im Datenlauf

- GitHub-Job max. 150 Min.; `run_all` endet nach 105 Min. (danach S&P-500-Screening im selben Lauf).
- Tiingo: max. 40 Abrufe je Lauf, 450 neue Symbole je Monat.
- Backtest-Universum nur freigeben, wenn ≥ 85 % des damaligen Indexgewichts geprüfte Kurse haben
  (`MIN_COVERAGE`); Schwelle nicht senken, um „mehr Jahre“ zu bekommen.

## Ausliefern

Änderungen über Branch + Pull Request. Nach dem Merge in `main` startet der Datenlauf automatisch,
wenn Dateien in `app/`, `pipeline/`, `tools/`, `config/` oder der Workflow geändert wurden.
Sonst: Actions → Momentum Lab → Run workflow. Den Workflow selbst (`.github/workflows/momentum-lab.yml`)
kann der Workflow-Bot nicht ändern; Änderungen daran dem Eigentümer mit genauen Tipp-Schritten erklären
und `docs/workflow/momentum-lab.yml` mitpflegen.
