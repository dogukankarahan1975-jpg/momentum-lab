# Momentum Lab – Methodik

Stage 1 (Momentum-Screening) **v1.0.0** · Stage 2 (Fortsetzungsanalyse) **S2 v1.0.0** · Stand: 25.11.2026 · Parameter-Datei: `pipeline/config.py` · Jede Änderung erhöht die jeweilige Version und wird im `CHANGELOG.md` dokumentiert.

Abschnitte 1–7 beschreiben Stage 1, Abschnitt 8 Stage 2.

## 1. Ziel und Grundsätze

Momentum Lab wählt aus einem breiten Universum entwickelter Märkte höchstens zehn Aktien mit dem stärksten,
risikobereinigten Kursmomentum aus und bewertet bestehende Depotpositionen nach festen Regeln.

Grundsätze:

1. **Keine willkürlichen Scores.** Jede Regel stützt sich auf die MSCI-Momentum-Methodik oder auf veröffentlichte Forschung (Abschnitt 8).
2. **Vorab festgelegt.** Regeln und Backtest-Varianten wurden *vor* dem ersten Backtest mit echten Daten festgelegt. Ergebnisse des Backtests ändern die Regeln nicht automatisch (Schutz vor Data Mining).
3. **Lieber keine Empfehlung als eine falsche.** Fehlen geprüfte Daten oder erfüllt keine Aktie die Kriterien, empfiehlt die App nichts. Die Liste wird nie aufgefüllt.
4. **Gleiche Rechnung live und im Backtest.** `pipeline/core.py` wird für beides verwendet.

## 2. Universum

| Regel | Wert | Begründung |
|---|---|---|
| Quelle | Bestandteile des MSCI ACWI (iShares MSCI ACWI, tägliche Bestandsliste; Standard ab Pipeline 0.7.0). Umschaltbar auf MSCI World über `config/universe.txt`. Ab 0.9.8 zusätzlich ein zweites, getrenntes Screening der S&P-500-Mitglieder (Bestandsliste iShares Core S&P 500); Auswahl in der App, Abschalten mit `aus` in `config/screening_sp500.txt` | breite, regelbasierte Large-/Mid-Cap-Auswahl aus Industrie- und Schwellenländern; MSCI ACWI Momentum verwendet den Mutterindex als Universum |
| Handelbarkeit | nur Aktien, deren ISIN an der Börse Frankfurt handelbar ist (offizielle Liste der Deutschen Börse); China-A-Aktien (Shanghai/Shenzhen) immer ausgeschlossen | Annäherung an das Angebot von Trade Republic, das keine eigene Liste veröffentlicht; einzelne Abweichungen möglich, deshalb lokale Ausblende-Funktion in der App |
| Währungen | EZB-Referenzkurse; für Währungen ohne EZB-Kurs (TWD, SAR, AED, QAR, KWD, CLP, COP, PEN, EGP) Yahoo-Devisenkurse | Umrechnung in EUR |
| Fallback | zuletzt archivierte Liste, danach statisches Notfall-Universum | Ausfallsicherheit |
| Nur Aktien | Anlageklasse „Equity“ | Cash/Derivate ausgeschlossen |
| Mehrere Gattungen | je Unternehmen nur die liquideste Gattung | keine Doppelgewichtung (z. B. GOOGL/GOOG) |

**Survivorship Bias:** Die Liste enthält die *heutigen* Indexmitglieder. Ausgeschiedene, übernommene oder insolvente Firmen fehlen in den historischen Daten. Das betrifft vor allem den Backtest (Abschnitt 7). Ab dem ersten Lauf archiviert die Pipeline die Liste monatlich (`archive/universe/`), damit spätere Auswertungen eine zeitpunktgenaue Historie aufbauen.

## 3. Datenqualität (Ausschlussregeln)

Eine Aktie ist nur zulässig, wenn **alle** Prüfungen bestanden sind. Datenprobleme werden getrennt von Regelausschlüssen geführt.

| Prüfung | Grenze | Art |
|---|---|---|
| Kursdaten vorhanden | – | Datenproblem |
| Kurs aktuell | letzter Kurs höchstens 5 Kalendertage vor dem Datenstand | Datenproblem |
| Lücken | mindestens 225 Kurse in den letzten 365 Tagen | Datenproblem |
| Unplausibler Sprung | kein Tagesfaktor > 2,5 bzw. < 1/2,5 in 400 Tagen | Datenproblem |
| Anpassungsfehler | Verhältnis bereinigter/unbereinigter Kurs springt nicht um > 25 % | Datenproblem |
| Gegenprüfung | Abweichung zum iShares-Schlusskurs **desselben Handelstags** ≤ 3 % (Stichtag der Liste oder Vortag, falls verfügbar) | Datenproblem |
| Währung | muss in EZB-Referenzkursen vorkommen | Datenproblem |
| Historie | mindestens 2 Jahre | Regel |
| Liquidität | Median-Tagesumsatz ≥ 1 Mio. € (ca. 3 Monate) | Regel |
| Handel | höchstens 20 % Tage ohne Umsatz | Regel |
| Mindestkurs | ≥ 1 € | Regel (Penny Stocks) |

## 4. Momentum-Score (Kern, orientiert an MSCI)

Nach der MSCI Momentum Indexes Methodology (Juli 2025):

- **6-Monats-Momentum:** `P(T−1) / P(T−7) − 1`
- **12-Monats-Momentum:** `P(T−1) / P(T−13) − 1`
  `P(T−k)` = Kurs k Monate vor dem Stichtag. Der jüngste Monat wird ausgeschlossen, weil sehr kurzfristige Gewinner häufig wieder nachgeben (Kurzfrist-Reversal, Jegadeesh & Titman 1993).
- **Risikoanpassung:** beide Werte geteilt durch die annualisierte Standardabweichung der Wochenrenditen über 3 Jahre (mindestens 104 Wochen). MSCI begründet dies mit geringerem Risiko und dem Ziel, Momentum-Crashs abzumildern. Barroso & Santa-Clara (2015) zeigen, dass volatilitätsbereinigtes Momentum Crashs deutlich reduziert.
- **Standardisierung:** z-Scores über alle zulässigen Aktien, 6M und 12M je 50 % gewichtet und erneut standardisiert (wie MSCI).

**Bewusste Abweichungen von MSCI (dokumentiert):**

| MSCI | Momentum Lab | Grund |
|---|---|---|
| Kursrendite minus lokalem risikofreiem Zins | Total-Return-Kurse (dividendenbereinigt), ohne Zinsabzug | Kostenlose, verlässliche Tageszinsen für 23 Märkte fehlen; Wirkung auf die Rangfolge ist klein im Verhältnis zur Streuung der Momentum-Werte. Dividendenbereinigung verhindert, dass Dividendenzahler durch den Abschlag benachteiligt werden. |
| z-Scores bei ±3 gekappt | Mittelwert und Streuung aus ±3σ-winsorisierten Werten, Werte selbst ungekappt | Für eine Auswahl von nur 10 Aktien würden gekappte Werte an der Spitze Gleichstände erzeugen. MSCI selbst wählt nach dem ungekappten Score aus. |
| ca. 350 Titel, Gewichtung Score × Marktkapitalisierung | höchstens 10 Titel, gleichgewichtet | Ziel des Nutzers: fokussierte Auswahl. Gleichgewichtung ist robust (DeMiguel et al. 2009). |
| Quartalsweise Überprüfung + Ad-hoc-Regel bei Volatilitätsschock | tägliche Daten, Signale auf Monatsbasis; Volatilitätsschock nur als Hinweis und Backtest-Variante | Die Wirkung der MSCI-Regel wird erst im Backtest geprüft. |

## 5. Auswahl (Top 10 und Top Pick)

**Kandidat** wird eine zulässige Aktie, wenn

1. ihr Score im besten Zehntel des Universums liegt,
2. 6-Monats- **und** 12-Monats-Momentum positiv sind (absolutes Momentum, vgl. Moskowitz, Ooi & Pedersen 2012).

Davon die höchstens zehn mit dem höchsten Score. Gibt es nur drei, werden drei angezeigt.

**Top Pick** ist der beste Kandidat, der zusätzlich alle Robustheitsregeln erfüllt:

- beide Teilscores (6M und 12M) ≥ 1, damit der Score nicht von einem einzigen Zeitraum getragen wird,
- Volatilität nicht im obersten Zehntel des Universums (sehr volatile „Lotterie-Aktien“ hatten historisch schwächere Folgerenditen: Ang et al. 2006, Bali, Cakici & Whitelaw 2011),
- Kurs von der Zweitquelle bestätigt.

Erfüllt keiner das, gibt es **keinen** Top Pick.

## 6. Halte- und Verkaufsregeln (Portfolio Intelligence)

Vor dem Backtest festgelegt. Grundidee: **Kaufen nur die Besten, halten solange noch gut** (Puffer). MSCI nutzt einen Puffer von 50 % der Zielanzahl. Novy-Marx & Velikov (2016) zeigen, dass solche Kauf-/Halte-Spannen den Umschlag und die Kosten stark senken.

| Signal | Bedingung |
|---|---|
| **VERKAUF** | Verkaufsbedingung H am aktuellen **und** am vorherigen Monatsende, oder „schwer“ |
| **VERKAUF PRÜFEN** | H erstmals erfüllt (Bestätigung abwarten) oder Datenproblem |
| **NACHKAUFEN** | in den aktuellen Top 10, Depotanteil unter Grenze (Standard 20 %), Kurs über 200-Tage-Linie |
| **HALTEN** | sonst |
| **SPARPLAN FORTSETZEN** | Aktie unter den besten 5 %, 12M-Momentum positiv, über 200-Tage-Linie |
| **SPARPLAN STOPPEN** | sonst, oder Position hat Verkaufs-/Prüfsignal; Wechselkandidat = Top Pick |
| KEINE BEWERTUNG | keine Kursdaten, veraltete Daten oder fehlgeschlagener Datenlauf |

- **H (Verkaufsbedingung):** Rang außerhalb der besten 20 % **oder** 12-Monats-Momentum ≤ 0 **oder** kein gültiger Score.
- **Schwer:** Rang unterhalb des Medians (> 50 %) oder 12-Monats-Momentum ≤ −10 %.
- Ein schlechterer Rang **allein** ist nie ein Verkaufsgrund, solange die Aktie im Halteband bleibt.
- **Ersatz durch bessere Kandidaten** erfolgt über neues Geld (Sparplan, Verkaufserlöse), nicht durch Verkauf funktionierender Positionen. Das spart Gebühren und vermeidet steuerlich ineffiziente Verkäufe.
- Datenprobleme lösen nie automatisch VERKAUF aus, weil ein Datenfehler kein Verkaufsgrund ist. Ein echtes Ereignis wie eine Übernahme muss der Nutzer prüfen.
- Die **200-Tage-Linie** ist in v1.0 nur ein Hinweis. Ob sie als Filter hilft, prüft der Backtest (Variante `app_top10_ma200`). Eine Übernahme in die Regeln wäre eine neue Methodik-Version.

## 7. Backtest

- Monatliche Signale am letzten Handelstag, Handel zum Schlusskurs des **nächsten** Handelstags (kein Look-ahead).
- Kosten: 1 € je Order + 0,20 % Spread (Szenarien: 0 % und 0,50 %).
- Steuern: Abgeltungsteuer 26,375 %, FIFO, Sparer-Pauschbetrag 801 €/Jahr bis 2022, 1.000 € ab 2023, Verlustvortrag; ETF mit 30 % Teilfreistellung. Ergebnisse vor und nach Steuern (inkl. fiktiver Endbesteuerung).
- Vorab festgelegte Varianten (`config.BACKTEST_VARIANTS`): einfaches 12-1, 6+12 kombiniert, risikoadjustiert (MSCI-Stil) mit Top 10/5/1 und Scoregewichtung, App-Regeln (Puffer + Bestätigung) mit Top 10 und Top Pick, App-Regeln + 200-Tage-Filter, + Markt-Trendfilter, + MSCI-Volatilitätsschock-Regel, Halteband 10 %/30 % (Sensitivität), Sparpläne (Top Pick, Top 10, MSCI-World-ETF).
- Maßstäbe: gleichgewichtetes Universum (gleiche Verzerrung, daher fairster Vergleich), iShares Core MSCI World (EUNL), iShares MSCI World Momentum (IS3R), US-Momentum (MTUM). ETF-Daten enthalten Fondskosten und beginnen erst mit der Auflage.
- Kennzahlen: Rendite p. a., Gesamtrendite, Volatilität, maximaler Verlust, Sharpe (Zins 0 %), Anteil besserer Monate, Gewinn-Trades, Anzahl Trades, Umschlag, Cash-Anteil, Steuern, Kostenszenarien, Marktphasen (benannte Krisen, Bullen-/Bärenmonate).

**Bekannte, nicht behebbare Verzerrungen:**

1. **Survivorship Bias:** nur heutige Indexmitglieder. Verlierer, die aus dem Index fielen, fehlen. Delisting-Renditen fehlen ebenfalls (Shumway 1997). Die Ergebnisse sind daher wahrscheinlich zu gut.
2. **Look-ahead durch Universumsauswahl:** Die heutige Indexzugehörigkeit war damals nicht bekannt.
3. **Datenqualität:** Yahoo-Kurse sind inoffiziell; einzelne historische Fehler sind möglich.
4. **Mehrfachtests:** Es werden 13 Varianten verglichen. Die beste Variante ist auch zufällig die beste (Harvey, Liu & Zhu 2016). Unterschiede von wenigen Zehntelprozent sind nicht belastbar.


<a name="stage-2"></a>
### 7a. Simulator (App, Reiter Backtest)
Die Pipeline stellt für jedes Monatsende seit Beginn der Kurshistorie das Stage-1-Screening nur mit damals verfügbaren Kursen nach und exportiert Rangliste, Kandidaten mit Momentum-Score, Halteregel-Status, die Stage-2-Rangfolge der Top 10 (nur Kursteil, §8) und Ausführungskurse in EUR (Schluss des nächsten Handelstags). Die App rechnet daraus Sparpläne mit sechs Strategien: MSCI-World- und S&P-500-ETF-Sparplan (thesaurierend, nie verkauft), Stage 1 Top 5, Stage 1 Top 10, Stage 2 Top 5 und „Minimum Score“ (nur Stage-1-Kandidaten mit Momentum-Score ab dem Mindestwert, Standard 4; gibt es keinen, wird nicht gehandelt und das Budget bleibt auf dem Konto). Budget (mit Dynamik) plus wahlweise Verkaufserlöse werden zu gleichen Teilen verteilt. Verkauf nach App-Halteregel oder fester Haltedauer (3/6/12 Monate, jeweils optional „im Minus warten bis ±0“).

Steuern (Privatanleger, ohne Kirchensteuer): 26,375 % Abgeltungsteuer + Soli. Aktiengewinne und -verluste je Jahr; Aktienverluste nur mit Aktiengewinnen verrechenbar und werden vorgetragen (Aktienverlusttopf). ETF: 30 % Teilfreistellung; Vorabpauschale ab 2018 = Wert am Jahresanfang × Basiszins (BMF) × 0,7, Käufe im Jahr anteilig (je voller Monat vor dem Kauf ein Zwölftel weniger), höchstens der Wertzuwachs; versteuert im Januar des Folgejahres, beim Verkauf angerechnet. ETF-Verluste (allgemeiner Topf) dürfen Aktiengewinne mindern. Sparer-Pauschbetrag 801 € bis 2022, 1.000 € ab 2023, gemeinsam für alles, je Strategie eigenständig. Steuer wird wie beim Broker sofort bei jedem Verkauf einbehalten; Verluste im selben Jahr führen zur Erstattung; nicht verrechnete Aktienverluste werden vorgetragen. Endwert nach Steuern = gedachter Verkauf am letzten Kurstag. Vereinfachungen: Dividenden der Aktien und Ausschüttungen der ETF werden über bereinigte Kurse wieder angelegt und nicht jährlich besteuert; vor 2018 (altes Investmentsteuerrecht) keine jährliche Besteuerung thesaurierter ETF-Erträge. Beides lässt die Ergebnisse leicht zu günstig aussehen.

Historische Indexzusammensetzung (ab 0.8.0): In jedem Monat zählen nur die damaligen Indexmitglieder laut iShares-Bestandsliste zum jeweiligen Monatsende (ACWI ab 04/2008, World ab 02/2012). Ehemalige Mitglieder nur, wenn Yahoo-Kurse vorhanden sind und das Verhältnis Yahoo/iShares-Kurs über die Stichtage stabil ist (≥ 70 % der Monatsschritte mit < 8 % Abweichung; Sprünge nur bei Splits). Ehemalige Mitglieder ohne Kurse fehlen weiterhin (Rest-Verzerrung). Optionale Korrektur im Simulator: gemessener Vorsprung der gleichgewichteten Liste (ohne Kosten, monatlich neu gewichtet) vor dem echten Index-ETF im selben Zeitraum, als gleichmäßiger Abschlag p. a. auf alle Aktienkurse; nie negativ.

Backtest-Aktienlisten mit damaliger Zusammensetzung (ab 0.9.0, Stand 0.9.2): S&P 500 aus dem Datensatz github.com/fja05680/sp500 (Zusammensetzung an jedem Änderungstag seit 1996, MIT-Lizenz), danach Aufnahmen laut aktueller Wikipedia-Liste. DAX-Familie aus dem offiziellen STOXX-PDF „Historical Index Compositions“. MSCI ACWI aus den vierteljährlichen SEC-Meldungen (N-PORT) des iShares MSCI ACWI ETF ab 10/2019. Ein Monat zählt, wenn mindestens 85 % der damaligen Mitglieder Kurse haben; beim ACWI gemessen am damaligen Indexgewicht (Positionswerte der Meldung), weil dort viele sehr kleine Schwellenländer-Werte keine Yahoo-Kurse haben. Der Backtest beginnt beim ersten Monat, ab dem das ohne Unterbrechung bis heute gilt.

MSCI-World-Sparplan: iShares Core MSCI World (EUNL) ab 09/2009; davor verlängert mit dem älteren iShares MSCI World UCITS ETF (Dist, Ausschüttungen wieder angelegt), nur wenn beide Reihen im gemeinsamen Zeitraum übereinstimmen (mind. 24 Monate, Korrelation der Monatsrenditen ≥ 0,97, Abweichung ≤ 1,5 Prozentpunkte p. a., kein Monat > 3 Prozentpunkte). S&P 500: Total-Return-Index ab 1988 abzüglich 0,07 % ETF-Kosten p. a.

## 8. Stage 2 – Fortsetzungs-Rangfolge (S2 v2.0.0)

### 8.1 Ziel
Stage 1 beantwortet: *Welche Aktien sind am stärksten gestiegen (risikobereinigt)?* Stage 2 beantwortet: *Bei welchen dieser Top-10-Kandidaten läuft das Momentum am ehesten weiter?* Stage 2 schließt keine Aktie aus und vergibt keine Kauf- oder Verbotsurteile. Es sortiert die Top-10-Kandidaten neu; die **ersten 5 sind die Kaufkandidaten**.

Version 1 (Anti-Peak-Filter, Bewertungs- und Qualitätskategorien) wurde ersetzt: Ihre Filter schlossen gerade die stärksten Gewinner aus, im Simulator lag sie dadurch unter „Stage 1 Top 5“.

### 8.2 Signale
Nur Signale, für die es veröffentlichte Forschung zur *Fortsetzung* von Momentum gibt:

| Signal | Teil | Richtung | Studie |
|---|---|---|---|
| Gleichmäßiger Anstieg (Information Discreteness: Vorzeichen der 12-1-Rendite × (Anteil negativer − Anteil positiver Tage)) | Kurs | niedriger besser | Da, Gurun & Warachka (2014) |
| Nähe zum 52-Wochen-Hoch (Kurs / 52-Wochen-Hoch) | Kurs | höher besser | George & Hwang (2004) |
| Marktbereinigtes Momentum (Residuum ggü. MSCI World, 12-1 Monate, durch Residuen-Volatilität) | Kurs | höher besser | Blitz, Huij & Martens (2011) |
| Änderung der Gewinnschätzung (EPS laufendes Jahr, 90 Tage) | Gewinn | höher besser | Chan, Jegadeesh & Lakonishok (1996) |
| Anhebungen minus Senkungen der Schätzungen (30 Tage, Anteil an Analysten) | Gewinn | höher besser | Chan, Jegadeesh & Lakonishok (1996) |
| Gewinnüberraschung (Ø der letzten 4 Quartale) | Gewinn | höher besser | Bernard & Thomas (1989) |

### 8.3 Berechnung
- Jedes Signal wird als Perzentil gegen die **Momentum-Vergleichsgruppe** gemessen: alle zulässigen Aktien im besten Zehntel des Momentum-Scores mit positivem Momentum (Kandidaten-Pool von Stage 1; zu wenige → beste 20 %).
- Kursteil = Mittel der Kurs-Perzentile (mindestens 2 von 3 vorhanden), Gewinnteil = Mittel der Gewinn-Perzentile (mindestens 1 vorhanden).
- **Score = 10 × (½ Kursteil + ½ Gewinnteil)**. Fehlen Analystendaten, gilt 10 × Kursteil; die Aktie wird als „nur Kursteil“ gekennzeichnet. Fehlende Werte werden nie geschätzt.
- Die Gewichte (½/½, gleiche Gewichte innerhalb eines Teils) sind eine vorab festgelegte, dokumentierte Regel und **nicht optimiert** – Optimierung auf dieselben Daten würde die Backtest-Ergebnisse schönen.
- Hinweise ohne Einfluss auf den Rang: Trendbruch (Kurs unter 200-Tage-Linie), Quartalszahlen in den nächsten 14 Tagen.

### 8.4 Daten
Kurse wie Stage 1. Analystendaten (Schätzungsänderungen, Überraschungen) aus Yahoo Finance (inoffizielle, kostenlose Schnittstelle, keine Garantie). Wöchentlicher Schnappschuss im Archiv, damit sich ab jetzt eine eigene Historie aufbaut.

### 8.5 Was getestet ist und was nicht
- **Kursteil:** rückwirkend testbar. Der Simulator rechnet für jedes Monatsende die Stage-2-Rangfolge der damaligen Top 10 nur mit damals verfügbaren Kursen (Strategie „Stage 2 Top 5“).
- **Gewinnteil:** historische Analystenschätzungen gibt es nicht kostenlos. Er fließt nur live ein und ist nicht rückwirkend getestet. Seine Wirkung zeigt erst das Live-Protokoll (Archiv `stage2v2`, Vergleich Top 5 vs. Platz 6–10).
- Survivorship Bias wie bei Stage 1 (heutige Indexmitglieder).

## 9. Quellen

- MSCI Inc. (2025): *MSCI Momentum Indexes Methodology*, Juli 2025. https://www.msci.com/indexes/documents/methodology/2_MSCI_Momentum_Indexes_Methodology_20250725.pdf
- Jegadeesh, N., Titman, S. (1993): Returns to Buying Winners and Selling Losers. *Journal of Finance* 48(1).
- Carhart, M. (1997): On Persistence in Mutual Fund Performance. *Journal of Finance* 52(1).
- Moskowitz, T., Grinblatt, M. (1999): Do Industries Explain Momentum? *Journal of Finance* 54(4).
- George, T., Hwang, C.-Y. (2004): The 52-Week High and Momentum Investing. *Journal of Finance* 59(5).
- Ang, A., Hodrick, R., Xing, Y., Zhang, X. (2006): The Cross-Section of Volatility and Expected Returns. *Journal of Finance* 61(1).
- Faber, M. (2007): A Quantitative Approach to Tactical Asset Allocation. *Journal of Wealth Management* 9(4).
- DeMiguel, V., Garlappi, L., Uppal, R. (2009): Optimal Versus Naive Diversification. *Review of Financial Studies* 22(5).
- Bali, T., Cakici, N., Whitelaw, R. (2011): Maxing Out: Stocks as Lotteries. *Journal of Financial Economics* 99(2).
- Moskowitz, T., Ooi, Y. H., Pedersen, L. (2012): Time Series Momentum. *Journal of Financial Economics* 104(2).
- Asness, C., Moskowitz, T., Pedersen, L. (2013): Value and Momentum Everywhere. *Journal of Finance* 68(3).
- Barroso, P., Santa-Clara, P. (2015): Momentum Has Its Moments. *Journal of Financial Economics* 116(1).
- Daniel, K., Moskowitz, T. (2016): Momentum Crashes. *Journal of Financial Economics* 122(2).
- Novy-Marx, R., Velikov, M. (2016): A Taxonomy of Anomalies and Their Trading Costs. *Review of Financial Studies* 29(1).
- Harvey, C., Liu, Y., Zhu, H. (2016): … and the Cross-Section of Expected Returns. *Review of Financial Studies* 29(1).
- Shumway, T. (1997): The Delisting Bias in CRSP Data. *Journal of Finance* 52(1).

Zusätzlich für Stage 2:

- Bernard, V., Thomas, J. (1989): Post-Earnings-Announcement Drift: Delayed Price Response or Risk Premium? *Journal of Accounting Research* 27.
- Fama, E., French, K. (1992): The Cross-Section of Expected Stock Returns. *Journal of Finance* 47(2).
- Chan, L., Jegadeesh, N., Lakonishok, J. (1996): Momentum Strategies. *Journal of Finance* 51(5).
- Piotroski, J. (2000): Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers. *Journal of Accounting Research* 38.
- Grinblatt, M., Moskowitz, T. (2004): Predicting Stock Price Movements from Past Returns: The Role of Consistency and Tax-Loss Selling. *Journal of Financial Economics* 71(3).
- Gutierrez, R., Prinsky, C. (2007): Momentum, Reversal, and the Trading Behaviors of Institutions. *Journal of Financial Markets* 10(1).
- Pontiff, J., Woodgate, A. (2008): Share Issuance and Cross-sectional Returns. *Journal of Finance* 63(2).
- Blitz, D., Huij, J., Martens, M. (2011): Residual Momentum. *Journal of Empirical Finance* 18(3).
- Novy-Marx, R. (2012): Is Momentum Really Momentum? *Journal of Financial Economics* 103(3).
- Novy-Marx, R. (2013): The Other Side of Value: The Gross Profitability Premium. *Journal of Financial Economics* 108(1).
- Da, Z., Gurun, U., Warachka, M. (2014): Frog in the Pan: Continuous Information and Momentum. *Review of Financial Studies* 27(7).
- Asness, C., Frazzini, A., Pedersen, L. (2019): Quality Minus Junk. *Review of Accounting Studies* 24.
- Newey, W., West, K. (1987): A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix. *Econometrica* 55(3).

*Momentum Lab ist ein privates Analysewerkzeug und keine Anlageberatung.*
