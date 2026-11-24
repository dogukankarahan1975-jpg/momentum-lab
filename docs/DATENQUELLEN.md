# Datenquellen und Kosten (geprüft am 24.11.2026)

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
| Nachrichten | Google News RSS | Sekundärquelle | frei | keine Nachrichten |

## Bewusste Kompromisse

1. **Keine offizielle, kostenlose Quelle für weltweite Aktienkurse.** Yahoo ist der praktikabelste freie Weg, aber inoffiziell. Daher: Gegenprüfung des letzten Kurses mit der iShares-Liste, Plausibilitätsprüfungen und harte Abbruchregeln.
2. **Stooq** verlangt seit Anfang 2026 einen per Captcha erhältlichen Schlüssel und hat ein Tageslimit. Es ist deshalb aktuell nicht eingebunden.
3. **MSCI-Indexdaten** sind nicht frei. Der Vergleich läuft über ETFs (mit Fondskosten, kürzere Historie).
4. **Öffentliches Repository:** Code und berechnete Screening-Daten sind öffentlich einsehbar. Dein Depot nie.
5. **Nachrichten werden nicht bewertet.** Eine KI-Auswertung würde laufende API-Kosten verursachen; eine verlässliche, kostenlose Methode gibt es nicht.

## Wartung

- Hat das Repository 60 Tage keine Aktivität, pausiert GitHub zeitgesteuerte Läufe. Der tägliche Lauf schreibt ein Protokoll (`archive/runs.log`) und hält das Repository damit aktiv. Falls doch pausiert: Reiter „Actions“ → Workflow → „Enable workflow“.
- Optional: unter Settings → Secrets and variables → Actions → Variables die Variable `SEC_CONTACT` mit deiner E-Mail anlegen (empfohlen von der SEC für automatisierte Abrufe).
