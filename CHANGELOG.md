# Änderungen

## Autopilot v1.0.0 / Pipeline 0.3.0 – 25.11.2026
- **Neu: Autopilot** – ein fester Monatsplan: welche Aktien verkaufen, welche kaufen, mit welchem Betrag, welche aufstocken, wann der nächste Plan kommt. Nur kursbasierte, historisch getestete Regeln (Entscheidung des Nutzers): Stage-1-Momentum, Stage-1-Halteregel, Anzahl Aktien (10 oder 15), Branchengrenze (keine oder höchstens 30 %), Markt-Trendfilter (keiner, keine Neukäufe im Abwärtstrend, alles parken im Abwärtstrend).
- Die Regel wird automatisch und nur mit den Jahren 2003–2014 aus 12 vorab festgelegten Varianten gewählt (höchste Rendite nach Steuern bei höchstens -45 % Zwischenverlust, Vorgabe des Nutzers). 2015–heute ist ein unberührter Prüfzeitraum und wird mit MSCI World ETF und MSCI World Momentum ETF verglichen, auch als Sparplan.
- App: neue Seite „Autopilot“ (Übersicht, Screening), gleicht den Plan mit dem eigenen Depot ab. Stage 1 und Stage 2 bleiben unverändert.

## Stage 2 v1.0.0 / Pipeline 0.2.0 – 25.11.2026
- **Neu: Stage 2 (Fortsetzungsanalyse)** der Stage-1-Kandidaten. Sie hat sechs Kategorien (Gewichte 20/20/20/15/10/15 %) mit Perzentilen gegen dokumentierte Vergleichsgruppen. Dazu kommen Datenqualität (HIGH/MEDIUM/LOW/INSUFFICIENT), ein Anti-Peak-Modul (NORMAL/ELEVATED/HIGH/CRITICAL), die Sparplan-Entscheidung (EXCEPTIONAL bis REJECT, HARD RISK), eine Outperformance-Einschätzung gegenüber dem MSCI World, eine finale Rangfolge und Begründungen. Stage 1 (Methodik 1.0.0) ist unverändert.
- Neues Datenmodul für Kennzahlen, Analystenschätzungen und Jahreswerte (Yahoo, rollierend für das ganze Universum, mit Budget und Drosselungsschutz). Wöchentliches Archiv der Kennzahlen als eigene Point-in-Time-Historie und monatliches Protokoll der Stage-2-Entscheidungen (Live-Bilanz).
- Teil-Backtest der kursbasierten Stage-2-Bausteine: Stage 1 gegen Stage 1+2, gleich- und scoregewichtet, Haltedauer 1/3/6/12 Monate, Kosten, Trefferquote, Prognosegüte (IC mit Newey-West-t). Fundamentale Teile sind ehrlich als nicht testbar gekennzeichnet.
- App: Top 10 mit Umschalter „Finale Rangfolge / Stage 1“, Stage-2-Detailansicht je Aktie, Stage-2-Phase im Screening, Stage-2-Zusammenfassung in Übersicht, Einstellungen und Backtest.
- **Fehlerbehebung Stage 1 (keine Methodikänderung):** Die Kursgegenprüfung verglich den iShares-Kurs mit dem Yahoo-Kurs des Folgetags. Am 24.11.2026 wurden dadurch 218 Aktien fälschlich als „Abweichung zur Zweitquelle“ ausgeschlossen, vor allem japanische (Feiertag am 23.11.). Jetzt wird derselbe Handelstag verglichen, bei abweichender Datumskonvention der Liste zusätzlich der Vortag.
- Statusanzeige der SEC-Quelle korrigiert (Fehler wurden als „ok“ angezeigt). Alle JSON-Dateien werden vor dem Schreiben bereinigt (NaN → leer).

## Pipeline 0.1.1 – 24.11.2026
- iShares-Bestandsliste über neue Adresse (latest-holdings.csv); USD-Kurse werden für die Gegenprüfung in Landeswährung umgerechnet.
- Klarere Fehlermeldung, wenn statt CSV eine Webseite kommt. SEC-Kennung enthält den GitHub-Namen.

## Methodik 1.0.0 / Pipeline 0.1.0 – 24.11.2026
- Erste Version. Universum MSCI World (iShares URTH), Datenqualitätsregeln, risikoadjustiertes 6/12-1-Momentum nach MSCI mit dokumentierten Abweichungen.
- Auswahl: bestes Zehntel, positives 6M- und 12M-Momentum, höchstens 10; Top Pick mit Robustheitsregeln.
- Halteregeln: Halteband 20 %, Verkauf nach Bestätigung an zwei Monatsenden oder sofort unter Median; Sparplan nur in den besten 5 %.
- Backtest mit 13 vorab festgelegten Varianten, Kosten- und Steuermodell.
