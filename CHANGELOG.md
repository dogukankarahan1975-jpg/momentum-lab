# Änderungen

## Pipeline 0.4.1 – 25.11.2026: Simulator transparenter
- ETF-Sparpläne: reiner Sparplan (jeden Monat kaufen, nie verkaufen); angezeigt wird das Vermögen ohne Verkauf, die Steuer bei einem gedachten Verkauf nur nachrichtlich.
- Neu: „Jede Order nachvollziehen“ – je Monat Konto vorher, Steuer, Budget, Verkaufserlöse, angelegter Betrag, Betrag je Aktie, Konto danach; jede Order mit Kurs, Stückzahl, Betrag, beim Verkauf Kaufdatum, Ø-Kaufkurs, Gewinn und Grund; Steuerabrechnungen; Bestand am Ende.
- Neu: Budget-Einstellung „Budget + Verkaufserlöse anlegen“ oder „Nur festes Monatsbudget anlegen“ (Erlöse bleiben auf dem Konto). Gilt nur für Aktien-Strategien.
- Stage 2 kauft nur echte Treffer (Risiko NORMAL und hohe Outperformance im Kursteil), bei keinem Treffer keine Aktie. Monatsliste zeigt je Top-10-Kandidat Risiko-Stufe und Outperformance.

## Pipeline 0.4.0 – 25.11.2026: Backtest-Simulator
- **Neu: Simulator** im Reiter Backtest: Strategien frei kombinieren (MSCI World und S&P 500 als thesaurierender ETF-Sparplan, Stage-1-Top-5- und Top-10-Liste, Stage 2 nur Kursteil), Monatsbudget mit jährlicher Dynamik, Gebühren je Kauf und Verkauf, ETF-Sparplangebühr, Spread, Haltedauer (bis zum Verkaufssignal der App, 6 oder 12 Monate) und Regel für fehlende Kandidaten (Rest in ETF, auf Konto oder immer Top 5/10).
- Grundlage: Für jedes Monatsende seit 2003 wird das Stage-1-Screening nur mit den Kursen bis zu diesem Tag nachgestellt; jede Monatsliste ist einsehbar. Ergebnis je Strategie: Endwert vor und nach Steuern, Rendite p. a. (interner Zinsfuß), größter Rückgang, Orders, Gebühren, Spread, laufend gezahlte Steuern; Jahr-für-Jahr-Protokoll mit Bestand.
- Neue Vergleichsreihen: S&P 500 Total-Return-Index (abzgl. 0,07 % Kosten p. a.), ersatzweise iShares Core S&P 500 (SXR8).
- Die bisherigen festen Varianten stehen weiter in der „Expertenansicht“.

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
