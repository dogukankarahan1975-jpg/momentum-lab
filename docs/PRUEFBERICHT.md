# Prüfbericht Backtest (Stand 28.11.2026, Pipeline 0.9.8)

Ziel: Prüfen, ob Indexzusammensetzung zu den Stichtagen, Kurse, Buchhaltung und Steuern im Backtest stimmen.
Teil A wurde bei der Entwicklung geprüft, Teil B läuft ab 0.9.7 in jedem Datenlauf automatisch
(Ergebnis: `archive/audit/latest.json`, Kurzfassung in der App unter der Auswahl „Aktienliste für den Backtest“).

## A. Geprüft bei der Entwicklung

### 1. S&P 500 – Zusammensetzung zu den Stichtagen
- Quelle: github.com/fja05680/sp500 (Zusammensetzung an jedem Änderungstag seit 1996, 2.720 Stichtage, letzter 18.08.2026),
  danach Aufnahmen laut Wikipedia; sobald alle späteren Änderungen erfolgt sind, gilt die aktuelle Liste exakt.
- Monatsliste = letzte Zusammensetzung vor dem Monatsende: alle 370 Monate stimmen mit den Rohdaten überein.
- Größe je Monat 487–506 Kürzel (Firmen mit zwei Aktiengattungen zählen doppelt) – plausibel.
- Stichproben gegen offizielle Mitteilungen von S&P Dow Jones Indices – alle Daten exakt:
  - 18.03.2024: Super Micro Computer, Deckers rein; Whirlpool, Zions raus
  - 23.09.2024: Palantir, Dell, Erie rein; American Airlines, Etsy, Bio-Rad raus
  - 19.05.2025: Coinbase rein, Discover raus
- Umbenennungen (z. B. FB → META) nur bei eindeutigem Nachweis (9 Fälle).
- Korrigiert: wiederverwendete Kürzel (z. B. DELL = Dell Inc. bis 2013 und Dell Technologies ab 2024) werden je
  Mitgliedsphase geprüft; die Phase ohne passende Kurse zählt als „ohne Kurse“ statt das Kürzel ganz zu verwerfen.
- Bekannte Grenze: Vor etwa 2006 kann ein Kürzel bei Yahoo die Kurshistorie eines Nachfolgers tragen
  (Beispiel „T“: altes AT&T bis 2005, danach SBC). Betrifft nur Zeiträume, die der Backtest derzeit nicht erreicht.
- Startmonat: erst ab dem Monat, ab dem durchgehend ≥ 85 % der damaligen Mitglieder Kurse haben
  (Stand 27.11.: ab 10/2019; rückt mit den Tiingo-Kursen ehemaliger Mitglieder weiter zurück).

### 2. MSCI ACWI – gefundene und behobene Fehler
- Ältere SEC-Meldungen (N-Q/N-CSR, 2008–2019): Der Leser hat Zeilenumbrüche im HTML-Quelltext als neue Tabellenzeile
  behandelt → keine einzige Meldung gelesen. Behoben, Test mit realem Aufbau ergänzt; Meldungen werden neu gelesen.
- ISIN → Börsenkürzel: Bei rund 250 von 3.700 ISINs war die falsche Börse gewählt (z. B. Pioneer Natural Resources
  in Mailand statt New York, Volvo „VOLVB.ST“ statt „VOLV-B.ST“), weitere 214 Kürzel ohne Yahoo-Kurse, 308 ohne
  Zuordnung. Neu: Prüfpfad über die Yahoo-Suche per ISIN mit Wahl der Heimatbörse (nach Handelswährung/Land),
  bis zu 600 je Lauf. Danach greift wie bisher die Kursprüfung (gemeldeter Kurs vs. Yahoo-Kurs an jedem Stichtag).
- ACWI bleibt gesperrt, bis in jedem Monat ≥ 85 % des damaligen Indexgewichts geprüfte Kurse haben.

### 3. Steuern – gegen Gesetz und BMF geprüft
| Regel | App | Quelle |
|---|---|---|
| Abgeltungsteuer 25 % + Soli 5,5 % = 26,375 % (ohne Kirchensteuer) | ✓ | § 32d EStG |
| Sparer-Pauschbetrag 801 € bis 2022, 1.000 € ab 2023 | ✓ | § 20 Abs. 9 EStG |
| Aktienverluste nur mit Aktiengewinnen, Vortrag ins Folgejahr | ✓ | § 20 Abs. 6 Satz 4 EStG |
| Steuer sofort bei jedem Verkauf, Erstattung bei Verlusten im selben Jahr (wie beim Broker) | ✓ | § 43a Abs. 3 EStG |
| Basiszins 2018–2026: 0,87 / 0,52 / 0,07 / 0 / 0 / 2,55 / 2,29 / 2,53 / 3,20 % | ✓ | BMF-Schreiben je Januar |
| Vorabpauschale: Kurs Jahresanfang × Basiszins × 0,7, höchstens Kursanstieg; Teilfreistellung 30 % | ✓ (korrigiert) | § 18, § 20 InvStG |
| Erwerbsjahr: minus 1/12 je vollem Monat vor dem Kauf | ✓ (korrigiert) | § 18 Abs. 2 InvStG |
| Dividenden im Jahr der Zahlung versteuern (nicht mit Aktienverlusten verrechenbar) | ✓ (neu) | § 20 Abs. 1, Abs. 6 EStG |

Korrigiert in 0.9.7:
- Dividenden wurden bisher erst beim Verkauf versteuert (sie stecken in den bereinigten Kursen). Jetzt: jährlich,
  Steuer sofort einbehalten, Einstand um die wiederangelegte Dividende erhöht. Wirkung: Aktien-Strategien etwas
  schlechter (grob 0,2–0,4 Prozentpunkte pro Jahr, je nach Dividendenrendite).
- Vorabpauschale je Anteil mit dem Kurs am Jahresanfang statt mit dem Kaufbetrag.
- „Falls du heute alles verkaufst“: Gebühren und Spread des Schlussverkaufs werden abgezogen.

Von Hand nachgerechnete Testfälle (alle exakt auf den Cent, automatisch bei jedem Lauf):
- Aktiengewinn 3.000 € (2023): (3.000 − 1.000) × 26,375 % = 527,50 €
- Verlust 500 € (2023), Gewinn 2.500 € (2024): (2.500 − 500 − 1.000) × 26,375 % = 263,75 €
- Dividende 2.040 €: (2.040 − 1.000) × 26,375 % = 274,30 €
- Vorabpauschale 2025: 1.000 Anteile, Kurs 100 → 110: 1.771 € × 70 % − 1.000 € = 239,70 € × 26,375 %

Vereinfachungen (bewusst): keine Kirchensteuer; Freistellungsauftrag voll für dieses Depot; ausländische
Quellensteuer nicht gesondert (bei US-Aktien mit W-8BEN ist die Gesamtbelastung ähnlich); Dividenden aus den
Yahoo-/Tiingo-Kursbereinigungen abgeleitet.

### ETF-Sparpläne (MSCI World, S&P 500) – Prüfung 0.9.8
Die beiden ETF-Linien sind **keine nachgebaute Indexzusammensetzung**, sondern die echten Börsenkurse der ETFs in
Euro. Ein ETF-Kurs enthält an jedem Tag automatisch genau die damaligen Indexmitglieder – eine
Zusammensetzung „von heute“ kann darin nicht stecken.

| Linie | Quelle | Davor (nur nach Prüfung) |
|---|---|---|
| MSCI World | iShares Core MSCI World UCITS (EUNL, Xetra, thesaurierend) ab 09/2009 | ältere iShares-MSCI-World-ETFs (IQQW/IWRD) |
| S&P 500 | iShares Core S&P 500 UCITS (SXR8, Xetra, thesaurierend) ab 05/2010 – **neu in 0.9.8** | S&P 500 Total-Return-Index in Euro abzgl. 0,07 % p. a. |

Bis 0.9.7 war die S&P-500-Linie der Index abzüglich 0,07 % Kosten. Das war etwa 0,3 % p. a. zu günstig, weil ein
irischer ETF auf US-Dividenden 15 % Quellensteuer zahlt. Seit 0.9.8 echter ETF-Kurs.

Warum Online-Rechner andere Werte zeigen:
- **Rendite pro Jahr (deine Raten)** ist der interne Zinsfuß der Sparraten (geldgewichtet). Spätere Raten sind
  kürzer investiert. Die meisten Rechner zeigen stattdessen die Kursentwicklung des Fonds pro Jahr – diese steht
  jetzt als „Der ETF selbst: x % pro Jahr“ auf der Karte.
- Viele Seiten rechnen in US-Dollar (S&P 500 in Dollar hatte wegen des Wechselkurses andere Jahre als in Euro).
- Start- und Endmonat: Ein Monat mehr oder weniger verändert die Jahresrendite merklich (z. B. Start im März 2020).
- Manche Rechner nehmen den Index ohne Kosten, Quellensteuer und Steuern.

Gegenprobe in jedem Lauf: unsere Linien gegen die US-Schwester-ETFs IVV (S&P 500) und URTH (MSCI World) von Tiingo,
mit EZB-Kurs in Euro umgerechnet. Erwartet: Abweichung von wenigen Zehnteln Prozent pro Jahr (Quellensteuer,
Kosten, Handelszeiten); über 1 % p. a. wird in der App als Befund angezeigt.

## B. Automatische Prüfung in jedem Datenlauf (ab 0.9.7)
Je Backtest-Liste (S&P 500, ACWI, heutige Liste) werden 6 Strategien × 5 Einstellungen auf den echten Daten
gerechnet und geprüft:
1. Jede Order zum Tageskurs aus den Daten.
2. Gekauft wird nur, was am Stichtag auf der Liste stand – und laut Indexliste damals Mitglied war.
3. Eingezahlt = Startkapital + Monatsbudgets laut Einstellung.
4. Endwert = Konto + Stückzahl × letzter Kurs.
5. Steuer unabhängig aus Verkaufsgewinnen, Dividenden, Verlustvortrag und Pauschbetrag nachgerechnet.

Zusätzlich:
- Kursvergleich Yahoo ↔ Tiingo (zweite, unabhängige Quelle) für 20 große US-Aktien, Monatsrenditen seit 2005.
- ETF-Linien gegen IVV und URTH (Tiingo, in Euro), ab 0.9.8.
- Ausreißer-Suche: Monatsrenditen über +200 % oder unter −80 % (mögliche Datenfehler) zur Sichtprüfung.

## Was ein Backtest grundsätzlich nicht leisten kann
- Kurse von Firmen, die es nicht mehr gibt, fehlen teilweise. Die Lücke wird angezeigt, der Start verschoben.
- Ausführung zum Schlusskurs des ersten Handelstags; echte Kurse beim Kauf weichen ab (Spread-Annahme 0,2 %).
- Ein guter Backtest ist keine Prognose. Das ist keine Anlageberatung.
