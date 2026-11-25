# Datenquellen und Kosten (geprüft am 24.11.2026, Stage 2 ergänzt am 25.11.2026)

Alle Dienste sind ohne Kreditkarte, Abo oder Testzugang nutzbar.

| Zweck | Quelle | Art | Kosten / Grenzen | Ausfallplan |
|---|---|---|---|---|
| Hosting der App | GitHub Pages | Infrastruktur | kostenlos für **öffentliche** Repositories im Free-Tarif; Website max. 1 GB | Code liegt zusätzlich als ZIP bei dir; jeder andere statische Host funktioniert |
| Täglicher Datenlauf | GitHub Actions | Infrastruktur | Standard-Runner in öffentlichen Repositories kostenlos und unbegrenzt (Preisänderung 01/2026 betrifft nur private Repos und Self-Hosted) | manueller Start über „Run workflow“ |
| Aktienuniversum + Zweitkurs | iShares MSCI World ETF (URTH), Bestandsliste | Datenbank (BlackRock) | frei abrufbar | archivierte letzte Liste, danach Notfall-Universum |
| Kurse | Yahoo Finance (Chart-Endpunkt; Bibliothek yfinance als Reserve) | **inoffiziell** | frei, aber ohne Vertrag; Drosselung möglich | Cache der Historie; bei Sperre werden ältere Kurse genutzt und deutlich gekennzeichnet |
| Wechselkurse | Europäische Zentralbank, Referenzkurse | **offiziell** | frei | letzte gespeicherte Kopie |
| US-Fundamentaldaten, Pflichtmitteilungen | SEC EDGAR (XBRL „companyfacts“, „submissions“) | **offiziell** | frei; max. 10 Anfragen/Sekunde mit Kontaktangabe | Yahoo-Unternehmensdaten |
| Fundamentaldaten außerhalb USA | Yahoo Finance | Datenbank (inoffiziell) | frei | Anzeige „nicht verfügbar“ |
| Stage 2: Kennzahlen, Analystenschätzungen (EPS-Trend 7/30/60/90 Tage, Revisionen), Gewinnüberraschungen, Quartalstermine | Yahoo Finance „quoteSummary“ (ein Aufruf je Aktie; Zugang per Cookie/Crumb wie im Browser, Reserve: Bibliothek yfinance) | Datenbank / Schätzungen = Sekundärquelle (**inoffiziell**) | frei, kein Schlüssel; Grenzen nicht dokumentiert → eigenes Budget: normal ca. 320 Abrufe pro Lauf, Aufbauphase bis 750, Pausen, Abbruch bei Drosselung | ältere Werte bis 21 Tage; danach „fehlt“ und Datenqualität sinkt, keine Freigabe |
| Stage 2: Jahreswerte (EBIT, Zinsaufwand, investiertes Kapital, Aktienanzahl, Umsatz, operatives Ergebnis) | Yahoo Finance „fundamentals-timeseries“ | Datenbank (inoffiziell) | frei; ändert sich jährlich → Erneuerung alle 45 Tage, ca. 80 Abrufe pro Lauf (Aufbau 300) | Kennzahl ausgesetzt, solange weniger als 60 % der Vergleichsgruppe Werte haben |
| Stage 2: Sektor je Aktie | iShares-Bestandsliste (GICS-Sektor) | Datenbank (BlackRock) | frei | archivierte Liste |
| Stage 2: MSCI World als Vergleich | iShares Core MSCI World UCITS ETF (EUNL) über Yahoo | Datenbank | frei | ohne Reihe keine relative Stärke (Warnung) |
| Nachrichten | Google News RSS | Sekundärquelle | frei | keine Nachrichten |

## Bewusste Kompromisse

1. **Keine offizielle, kostenlose Quelle für weltweite Aktienkurse.** Yahoo ist der praktikabelste freie Weg, aber inoffiziell. Daher: Gegenprüfung des letzten Kurses mit der iShares-Liste, Plausibilitätsprüfungen und harte Abbruchregeln.
2. **Stooq** verlangt seit Anfang 2026 einen per Captcha erhältlichen Schlüssel und hat ein Tageslimit. Es ist deshalb aktuell nicht eingebunden.
3. **MSCI-Indexdaten** sind nicht frei. Der Vergleich läuft über ETFs (mit Fondskosten, kürzere Historie).
4. **Öffentliches Repository:** Code und berechnete Screening-Daten sind öffentlich einsehbar. Dein Depot nie.
5. **Nachrichten werden nicht bewertet.** Eine KI-Auswertung würde laufende API-Kosten verursachen; eine verlässliche, kostenlose Methode gibt es nicht.
6. **Analystendaten (Stage 2)** sind nur über Yahoo kostenlos erhältlich, ohne Vertrag und ohne Historie. Anbieter mit Historie (z. B. FactSet, LSEG/I/B/E/S, S&P Capital IQ) sind kostenpflichtig. Kostenlose API-Schlüssel anderer Anbieter enthalten Schätzungsrevisionen meist nur im Bezahltarif. Deshalb gilt: Yahoo wird sparsam abgerufen, alles wird gecacht, und die App archiviert die Werte ab jetzt wöchentlich selbst (`archive/fundamentals/`). So entsteht eine eigene zeitpunktgenaue Historie für spätere Tests.
7. **Unternehmensprognosen (Guidance)** gibt es nicht kostenlos in strukturierter Form. Sie fließen nicht in Stage 2 ein.
8. **Sektor- und Heimatmarkt-Vergleiche** nutzen den gleichgewichteten Durchschnitt der Aktien im Universum, weil offizielle MSCI-Sektorindizes nicht frei verfügbar sind.

## Wartung

- Hat das Repository 60 Tage keine Aktivität, pausiert GitHub zeitgesteuerte Läufe. Der tägliche Lauf schreibt ein Protokoll (`archive/runs.log`) und hält das Repository damit aktiv. Falls doch pausiert: Reiter „Actions“ → Workflow → „Enable workflow“.
- Optional: unter Settings → Secrets and variables → Actions → Variables die Variable `SEC_CONTACT` mit deiner E-Mail anlegen (empfohlen von der SEC für automatisierte Abrufe).
