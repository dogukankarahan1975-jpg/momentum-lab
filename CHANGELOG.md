# Änderungen

## Pipeline 0.9.9 – 28.11.2026
- Fehler behoben: Im Screening-Ablauf stand „undefined Aktien, Quelle: undefined“ und „NaN ohne Kursdaten“ (App-Fehler aus 0.9.8, die Daten selbst waren richtig).
- ACWI-Backtest: Hauptursache für „unstimmig“ gefunden. Durch eine zu grobe Namenszuordnung (erste 10 Buchstaben) gehörten 108 Kürzel zu zwei verschiedenen Wertpapieren, z. B. chinesische A-Aktie und H-Aktie derselben Bank, „National Bank of Greece“ → National Bank of Canada, Alphabet A/C. Dann sprang das Kursverhältnis und der Titel wurde verworfen (68 der 81 „unstimmigen“). Jetzt: ein Kürzel gehört genau einer ISIN (Heimatbörse und voller Name entscheiden), die übrigen 262 ISIN werden neu über OpenFIGI zugeordnet.
- Ältere ACWI-Meldungen (vor 2019): bessere Namenszuordnung (kurze Namen wie „BP PLC“, „3M Co“; bei mehrdeutigen Namen die ISIN aus der ersten N-PORT-Meldung). Jede Zuordnung muss weiterhin den strengen Kursabgleich bestehen.
- Yahoo-ISIN-Suche bekommt mehr Zeit pro Lauf.
- ETF-Gegenprobe korrigiert: verglich Monatsanfang mit Monatsende (daher scheinbar 1 % p. a. Abweichung). Die Kurse selbst stimmen: Yahoo und Tiingo liefern für URTH identische Monatsrenditen.

## Pipeline 0.9.8 – 28.11.2026
- Screening wahlweise für MSCI ACWI oder S&P 500: Umschalter oben unter Übersicht, Screening, Top 10 und Signale. Der Datenlauf erstellt beide Screenings (S&P 500 nach dem ACWI-Lauf, eigene Dateien unter data/sp500/ und eigenes Archiv unter archive/sp500/). Bestandsliste: iShares Core S&P 500 (UCITS mit ISIN, sonst US-Fonds IVV). Depot-Aktien, die nur in der anderen Liste stehen, werden in ihrer eigenen Liste bewertet (Hinweis „bewertet im …“), nie ohne Daten mit einem Signal versehen.
- S&P-500-ETF-Sparplan: rechnet jetzt mit den echten Kursen des iShares Core S&P 500 UCITS ETF (Xetra, Euro, SXR8) statt mit dem Index abzüglich Kosten. Vor dem Start des ETF (2010) wird der Total-Return-Index (abzgl. 0,07 % p. a.) nur angehängt, wenn er im gemeinsamen Zeitraum nachweislich zum ETF passt (gleiche Prüfung wie beim MSCI World).
- ETF-Karten zeigen zusätzlich „Der ETF selbst: x % pro Jahr“ (Kursentwicklung in Euro). Online-Rechner zeigen meist diesen Wert; „Rendite pro Jahr (deine Raten)“ ist der Zinssatz auf die monatlichen Einzahlungen.
- Gegenprobe der ETF-Linien in jedem Lauf: S&P 500 gegen IVV, MSCI World gegen URTH (Tiingo, in Euro mit EZB-Kurs).
- Zeitbudget: Backtest-Teil endet nach 105 statt 118 Minuten, damit das S&P-500-Screening im selben Lauf Platz hat.

## Pipeline 0.9.7 – 28.11.2026 (Prüfung, siehe docs/PRUEFBERICHT.md)
- ACWI vor 2019: Leser der alten SEC-Meldungen korrigiert (Zeilenumbrüche im HTML-Quelltext); alle Meldungen werden neu gelesen.
- ACWI: falsche Börsenzuordnungen (z. B. US-Aktie in Mailand, schwedische Aktienklassen) werden über die Yahoo-Suche per ISIN mit Heimatbörse korrigiert.
- S&P 500: wiederverwendete Kürzel je Mitgliedsphase geprüft; Monate nach dem letzten Datensatz-Stichtag nutzen die exakte aktuelle Liste, sobald alle Änderungen erfolgt sind.
- Steuer: Dividenden werden jährlich versteuert (bisher erst beim Verkauf); Vorabpauschale je Anteil nach § 18 InvStG (Kurs am Jahresanfang, 1/12-Kürzung im Erwerbsjahr).
- Neu: automatische Prüfung in jedem Datenlauf (Simulator auf echten Daten, Indexmitgliedschaft am Stichtag, unabhängige Steuer-Nachrechnung, Kursvergleich Yahoo ↔ Tiingo, Ausreißer). Ergebnis in archive/audit/latest.json und als Kurzfassung in der App.

## Pipeline 0.9.6 – 27.11.2026
- MSCI ACWI vor 2019: ältere SEC-Meldungen des iShares MSCI ACWI ETF (N-Q und N-CSR/N-CSRS, ab 2008) werden ausgelesen (Name, Stückzahl, Wert je Aktie). Zuordnung zu Kurskürzeln nur über den exakten Namen aus den späteren N-PORT-Meldungen (mit ISIN) bzw. der heutigen Liste; mehrdeutige Namen werden nicht verwendet. Strenge Kursprüfung: Das Verhältnis Yahoo-Kurs / gemeldeter Kurs darf sich zwischen zwei Stichtagen höchstens um 12 % ändern (außer um typische Split-Faktoren), sonst gilt die Aktie in diesem Zeitraum als nicht zugeordnet. Der Backtest beginnt erst, wenn durchgehend mindestens 85 % des damaligen Indexgewichts geprüfte Kurse haben.
- Die älteren Meldungen werden über mehrere Läufe verteilt geladen (Zeitlimit).
- DAX-Familie und „S&P 500 + DAX“ aus dem Backtest entfernt.
- Installation: holt vor dem Installieren den neuesten Stand; ein bereits installiertes Paket wird übersprungen.

## Pipeline 0.9.5 – 27.11.2026
- Optional Tiingo (kostenloser Starter-Tarif, Registrierung nötig, GitHub-Secret `TIINGO_API_KEY`): Kurse ehemaliger S&P-500-Mitglieder, die bei Yahoo fehlen. Höchstens 40 Abrufe pro Lauf und 450 Symbole pro Monat (Limit 50/Stunde, 500/Monat). Jede Aktie wird einmal geladen und unter archive/tiingo/ gespeichert. Nutzungsbedingung von Tiingo: nur private Nutzung.
- Simulator: neue Auswahl „In welchen Monaten?“ bei vierteljährlichem, halbjährlichem und jährlichem Screening (z. B. Jan/Apr/Jul/Okt, Feb/Mai/Aug/Nov oder Mär/Jun/Sep/Dez). Damit lässt sich prüfen, wie viel vom Ergebnis Timing-Glück ist.
- Simulator: neues Feld „Startkapital (€, einmalig)“ und Auswahl „Monatsbudget einzahlen: immer / nur die ersten 6–120 Monate (Starthilfe)“. Nach der Starthilfe wird nichts mehr eingezahlt; es werden nur noch die Verkaufserlöse angelegt. „Eingezahlt“ zählt nur echtes Geld (Startkapital + gezahlte Budgets).
- Backtest „alles heute verkaufen“: Ordergebühren und Spread des Schlussverkaufs werden jetzt abgezogen (auch steuerlich).
- Text unter „Jahr für Jahr“ korrigiert: Steuer wird bei jedem Verkauf sofort einbehalten, nicht im Folgejahr.
- DAX-Backtest gesperrt, solange weniger als 90 % der Firmennamen einem Kurskürzel zugeordnet sind oder die Liste nicht bis heute reicht.

## Pipeline 0.9.3/0.9.4 – 27.11.2026
- Fehler aus 0.9.2 behoben: Einige ISINs aus den SEC-Meldungen waren falsch zugeordnet (z. B. Siemens Energy → Siemens Energy India, Banco Santander → Santander Chile, veraltete ISIN von Linde/Aon). Jetzt nur noch aus der neuesten Meldung und nur, wenn das ISIN-Länderkürzel zur Heimatbörse passt; sonst bleibt die ISIN leer.
- Zeitlimit: Der Lauf vom 26.11. abends lief in GitHubs 150-Minuten-Grenze (viele neue Kurse, SEC-Meldungen neu, DAX-Namenssuche). Der Backtest-Teil hat jetzt eine feste Endzeit (118 Minuten nach Start der Pipeline): Was dann noch fehlt, holt der nächste Lauf nach; bereits Berechnetes bleibt sichtbar. Reihenfolge: ACWI, DAX, S&P 500, Kombination.
- Frankfurt-Prüfung streicht keine Aktien mehr: Viele Werte (TSMC, Samsung, indische Aktien) stehen dort nur als ADR/GDR mit anderer ISIN, sind bei Trade Republic aber kaufbar. Ergebnis ist nur noch ein Hinweis unter Einstellungen → Datenquellen. Nicht kaufbare Aktien weiter mit „Gibt es bei Trade Republic nicht“ ausblenden.

## Pipeline 0.9.2 – 26.11.2026
- S&P 500: Wikipedia hat die Tabelle der Aufnahmen/Streichungen 2026 von der Listenseite entfernt. Neue Quelle für die Zusammensetzung an jedem Änderungstag seit 1996: gepflegter Datensatz github.com/fja05680/sp500 (MIT-Lizenz, zuletzt aktualisiert Sept. 2026). Aufnahmen danach aus der aktuellen Wikipedia-Liste („Date added“). Umbenennungen (z. B. FB → META) werden nur bei eindeutigem Nachweis übernommen.
- DAX-Familie: Index wird jetzt über die Beschriftung „DAX®“, „TecDAX®“, „MDAX®“, „SDAX®“ vor der Änderungstabelle erkannt (im echten PDF gibt es keine Überschrift als Text). ESG- und Strategie-Indizes werden übersprungen. Bei erneutem Fehlschlag wird ein Textausschnitt gespeichert.
- MSCI ACWI: Abdeckung wird am Indexgewicht gemessen (Positionswerte aus der SEC-Meldung), wie MSCI selbst. Zahl der Mitglieder mit Kursen wird zusätzlich angezeigt. Kursprüfung rechnet mit der Handelswährung der Yahoo-Kurse; Fremdwährungen aus `currencyConditional` werden gelesen.
- Screening: ISIN für rund 90 % der ACWI-Aktien aus den SEC-Meldungen (Name wird gegengeprüft) → die Prüfung „an der Börse Frankfurt handelbar“ und „ISIN kopieren“ funktionieren jetzt.
- Russische Titel (seit 2022 eingefroren) erzeugen keine Warnung mehr.

## Pipeline 0.9.1 – 26.11.2026
- Simulator: „Wie oft wird gescreent und gekauft?“ – monatlich, vierteljährlich, halbjährlich oder jährlich. Dazwischen sammeln sich Budget und Verkaufserlöse auf dem Konto und werden beim nächsten Screening verteilt.
- ACWI: Kursprüfung verglich vierteljährliche Meldekurse mit jedem Monatsende (Fehlalarm bei 733 Aktien). Jetzt nur an den echten Meldestichtagen. Nicht zuordenbare ISIN zählen als fehlende Mitglieder.
- DAX-Familie: Leser an den echten Aufbau des STOXX-PDFs angepasst (Anfangsliste steht vor der Überschrift, Seitenkopf wird übersprungen); Streichungen werden auch bei leicht abweichender Schreibweise erkannt.
- S&P 500: zweiter Abrufweg über die Wikipedia-Schnittstelle; Fehlermeldungen werden in der App angezeigt.

## Pipeline 0.9.0 – 26.11.2026: Backtests mit damaliger Indexzusammensetzung
- Im Simulator wählbar: „S&P 500“, „DAX-Familie (DAX, MDAX, SDAX, TecDAX)“, „S&P 500 + DAX-Familie“ und „MSCI ACWI“. In jedem Monat zählen nur die Aktien, die damals im Index waren.
  - S&P 500: aktuelle Liste und alle Aufnahmen/Streichungen von Wikipedia, rückwärts rekonstruiert; nur Monate mit 480–520 Mitgliedern.
  - DAX-Familie: offizielles PDF „Historical Index Compositions“ von STOXX; Firmennamen werden Yahoo-Symbolen zugeordnet (Korrekturen in `config/name_map.txt`).
  - MSCI ACWI: Pflichtmeldungen des iShares MSCI ACWI ETF an die US-Börsenaufsicht (SEC, Formular N-PORT), vierteljährlich ab Ende 2019, mit ISIN; Börsensymbole über OpenFIGI.
- Jede Liste wird gegen die Kurse geprüft. Der Backtest beginnt erst ab dem Monat, ab dem durchgehend mindestens 85 % der damaligen Mitglieder Kurse haben. Firmen ohne Kurse (meist Pleiten/Übernahmen) fehlen und werden ausgewiesen.
- Die bisherige Variante „heutige ACWI-Liste“ bleibt zum Vergleich wählbar, klar als verzerrt gekennzeichnet.
- Das tägliche Screening ist unverändert (MSCI ACWI).

## App – 26.11.2026 (Pipeline 0.8.1)
- Simulator: Enddatum wählbar („bis heute“ oder Ende eines Jahres), z. B. 2008–2010 testen.
- Aktienseite: „ISIN kopieren“ (wenn die ISIN bekannt ist, sonst wird der Name kopiert).
- Historische Indexlisten: iShares ignoriert das Stichtags-Datum und liefert immer die aktuelle Liste. Die Pipeline erkennt das, verwendet nichts Falsches und versucht es erst nach 30 Tagen erneut.

## Pipeline 0.8.0 – 26.11.2026: Backtest mit historischer Indexzusammensetzung
- Der Backtest verwendet in jedem Monat nur die Aktien, die damals im Index waren (iShares-Bestandslisten zu früheren Stichtagen, kostenlos). MSCI ACWI ab 04/2008, MSCI World ab 02/2012. Die Liste wird über mehrere Nächte aufgebaut, vom jüngsten Monat rückwärts; erst ab 24 zusammenhängenden Monaten wird sie verwendet.
- Ehemalige Indexmitglieder werden mitgerechnet, wenn Yahoo noch Kurse hat und diese zu den iShares-Kursen der Stichtage passen (Schutz vor wiederverwendeten Tickern). Enden die Kurse (Delisting/Übernahme), wird zum letzten Kurs verkauft und das im Protokoll gekennzeichnet.
- Simulator: Häkchen „Überlebenden-Effekt herausrechnen“. Der Korrekturwert wird aus den eigenen Daten gemessen (gleichgewichtete Backtest-Liste minus echter ACWI- bzw. MSCI-World-ETF im selben Zeitraum) und von jeder Aktie abgezogen. Ohne Häkchen keine Korrektur.
- Neuer Vergleichswert: iShares MSCI ACWI ETF.

## Pipeline 0.7.1 – 26.11.2026
- Übersicht auf Screening-Knopf und Backtest reduziert (Backup-Erinnerung bleibt).
- Simulator: Top 5, Top 10 und Stage 2 Top 5 kaufen jeden Monat immer 5 bzw. 10 Aktien, unabhängig vom Momentum-Score; fehlende Kandidaten werden mit den nächsten der Momentum-Rangliste aufgefüllt. „Minimum Score“ bleibt die einzige Strategie mit Score-Grenze.
- Top 10 (Stage 1): Gibt es weniger als 10 Kandidaten, zeigt die App die „Auffüller“ – dieselbe Regel wie im Simulator.
- Handelbarkeits-Prüfung: Die CSV-Bestandsliste von iShares enthält keine ISIN, deshalb war der Frankfurt-Abgleich im ersten ACWI-Lauf nicht aktiv (nur China-A-Aktien ausgeschlossen). Die ISIN wird jetzt aus der JSON-Variante derselben iShares-Liste ergänzt; Aktien ohne zuordenbare ISIN bleiben drin.

## Pipeline 0.7.0 – 26.11.2026: MSCI ACWI, nur in Deutschland handelbare Aktien
- Universum jetzt MSCI ACWI: Large und Mid Caps aus Industrie- und Schwellenländern (vorher nur MSCI World). Regeln unverändert. Zurückschalten über `config/universe.txt` (`world`).
- Nur Aktien, die an der Börse Frankfurt handelbar sind (offizielle Liste der Deutschen Börse) – Annäherung an das Angebot von Trade Republic. China-A-Aktien werden immer ausgeschlossen.
- Neu in der App: „Gibt es bei Trade Republic nicht“ bei jeder Aktie. Ausgeblendete Aktien verschwinden aus Top 10, Stage 2 und Simulator, der nächste Kandidat rückt nach. Liste unter Einstellungen, nur lokal gespeichert.
- Schwellenländer-Börsen (Taiwan, Korea, Indien, Brasilien, Südafrika, Saudi-Arabien, Mexiko u. a.) werden Yahoo-Symbolen zugeordnet; Währungen ohne EZB-Kurs über Yahoo-Devisenkurse.
- Gegenprüfung mit iShares-Kursen wird je Währung ausgesetzt, wenn mehr als die Hälfte abweicht (Konventionsproblem der Zweitquelle statt Fehler einzelner Aktien).

## Pipeline 0.6.1 – 26.11.2026
- Kurse: Nachts (vor Handelsbeginn) datiert Yahoo den letzten Schlusskurs auf den nächsten Handelstag vor. Dieser Balken wurde bisher als „laufender Handelstag“ verworfen; bei Datenläufen nach ca. 2 Uhr fehlte dadurch der letzte US-Schlusskurs und der Datenstand fiel um einen Tag zurück (26.11.: Stand 24.11. statt 25.11.). Jetzt wird er auf den richtigen Tag zurückdatiert; bereits gespeicherte neuere Schlusskurse gehen beim Nachladen nie mehr verloren.
- Quellenstatus: Unternehmensdaten und Nachrichten, die noch aktuell im Zwischenspeicher liegen, gelten als „ok“ statt „Problem“ („0 ok / 0 Fehler“ hieß nur: nichts neu abzurufen).
- Simulator: MSCI-World-Sparplan vor 09/2009 (Start von EUNL) mit dem älteren iShares MSCI World (Dist) verlängert – nur wenn beide Reihen im gemeinsamen Zeitraum nachweislich übereinstimmen. Vorher wurde jedes Startjahr vor 2010 stillschweigend auf 2010 verschoben (deshalb immer dieselbe Rendite).
- Simulator: Haltedauer 1 Monat (auch mit „warten bis ±0“), ebenso im Depot. Auswahl „Weniger Kandidaten als Plätze?“ entfernt: Es werden nur echte Kandidaten gekauft, der Rest bleibt auf dem Konto und wird im nächsten Monat mit angelegt.
- Steuern: Abgeltungsteuer wird wie beim Broker sofort bei jedem Verkauf einbehalten, Verluste im selben Jahr werden erstattet (Verlustverrechnung), Vorabpauschale Anfang Januar; vorher Sammelabrechnung im Januar des Folgejahres.

## Pipeline 0.6.0 / Stage 2 v2.0.0 – 26.11.2026
- **Stage 2 komplett neu: Fortsetzungs-Rangfolge.** Die Top-10-Kandidaten aus Stage 1 werden nach Forschungssignalen für das Weiterlaufen von Momentum sortiert (gleichmäßiger Anstieg, Nähe zum 52-Wochen-Hoch, marktbereinigtes Momentum; live zusätzlich Schätzungsänderungen und Gewinnüberraschungen). Die besten 5 sind die Kaufkandidaten. Nichts wird ausgeschlossen. Anti-Peak-Filter und Kategorien von v1 entfallen.
- Simulator: sechs Strategien – MSCI World, S&P 500, Stage 1 Top 5, Stage 1 Top 10, Stage 2 Top 5 (Kursteil rückwirkend getestet), Minimum Score 4 (nur Stage-1-Kandidaten mit Momentum-Score ab 4, sonst bleibt das Budget auf dem Konto).
- Steuern: Sparer-Pauschbetrag 801 € bis 2022, 1.000 € ab 2023.
- Stage-2-Teilvalidierung (v1) im Backtest entfernt; neues Live-Protokoll unter `archive/stage2v2`.

## Pipeline 0.5.2 – 26.11.2026
- Simulator: Bei „Nur Kandidaten, Rest bleibt auf dem Konto“ zusätzlich Mindest-Momentum-Score (Stage-1-Score, Standard 4). Ohne passenden Kandidaten wird nicht gehandelt, das Budget bleibt auf dem Konto. Monatslisten zeigen den Score.

## Pipeline 0.5.1 – 26.11.2026
- Simulator: Haltedauer 3 Monate (auch mit „im Minus warten bis ±0“), ebenso im Depot.
- Simulator: Vorabpauschale ab 2018 mit Basiszins des BMF (2018 0,87 %, 2019 0,52 %, 2020 0,07 %, 2021–2022 0 %, 2023 2,55 %, 2024 2,29 %, 2025 2,53 %, 2026 3,20 %), 30 % Teilfreistellung, Anrechnung beim Verkauf; Sparer-Pauschbetrag gemeinsam für Aktiengewinne und Vorabpauschale; Aktienverluste nur mit Aktiengewinnen verrechnet.

## Pipeline 0.5.0 – 26.11.2026
- Autopilot entfernt (Wunsch des Nutzers).
- Simulator: ETF-Sparplan als normaler Sparplanrechner; Feld heißt jetzt „Gebühr je ETF-Sparrate“, unrealistische Gebühren/Spreads werden abgefangen (vorher konnte die Sparrate versehentlich als Gebühr eingetragen werden). Neue Haltedauer-Optionen „6/12 Monate, im Minus warten bis ±0“; Protokoll zeigt „Halten“-Einträge. Feste Haltedauer verkauft jetzt am ersten Monatsende nach Ablauf (auch wenn die Aktie noch auf der Liste steht; sie wird dann mit dem neuen Geld wieder gekauft).
- Depot: Haltedauer je Position (beim Kauf wählbar: Verkaufssignal der App, 6 oder 12 Monate, optional „im Minus warten bis ±0“). Verkaufstermin = erster Werktag des Monats nach Ablauf. Hinweis „Haltedauer vorbei“ getrennt vom Verkaufssignal der App, in Depot, Position und Signalen.
- Erinnerungen über den iPhone-Kalender (.ics): Verkaufstermine der Positionen und monatliches Screening. Keine Daten verlassen das iPhone.
- Neuer Kauf-Rechner: Gewinn aus Verkäufen (rein → raus) und Aufteilung von Gutschrift + neuem Geld auf n Aktien mit 1 € Gebühr je Kauf.

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
