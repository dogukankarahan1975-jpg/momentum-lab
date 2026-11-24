# Momentum Lab – Methodik v1.0.0

Stand: 24.11.2026 · Parameter-Datei: `pipeline/config.py` · Jede Änderung erhöht die Version und wird im `CHANGELOG.md` dokumentiert.

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
| Quelle | Bestandteile des MSCI World (iShares MSCI World ETF, URTH, tägliche Bestandsliste) | breite, regelbasierte Large-/Mid-Cap-Auswahl aus 23 entwickelten Märkten; MSCI Momentum verwendet den Mutterindex als Universum |
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
| Gegenprüfung | Abweichung zum iShares-Schlusskurs ≤ 3 % (falls verfügbar) | Datenproblem |
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
- Steuern: Abgeltungsteuer 26,375 %, FIFO, Sparerpauschbetrag 1.000 €/Jahr, Verlustvortrag; ETF mit 30 % Teilfreistellung. Ergebnisse vor und nach Steuern (inkl. fiktiver Endbesteuerung).
- Vorab festgelegte Varianten (`config.BACKTEST_VARIANTS`): einfaches 12-1, 6+12 kombiniert, risikoadjustiert (MSCI-Stil) mit Top 10/5/1 und Scoregewichtung, App-Regeln (Puffer + Bestätigung) mit Top 10 und Top Pick, App-Regeln + 200-Tage-Filter, + Markt-Trendfilter, + MSCI-Volatilitätsschock-Regel, Halteband 10 %/30 % (Sensitivität), Sparpläne (Top Pick, Top 10, MSCI-World-ETF).
- Maßstäbe: gleichgewichtetes Universum (gleiche Verzerrung, daher fairster Vergleich), iShares Core MSCI World (EUNL), iShares MSCI World Momentum (IS3R), US-Momentum (MTUM). ETF-Daten enthalten Fondskosten und beginnen erst mit der Auflage.
- Kennzahlen: Rendite p. a., Gesamtrendite, Volatilität, maximaler Verlust, Sharpe (Zins 0 %), Anteil besserer Monate, Gewinn-Trades, Anzahl Trades, Umschlag, Cash-Anteil, Steuern, Kostenszenarien, Marktphasen (benannte Krisen, Bullen-/Bärenmonate).

**Bekannte, nicht behebbare Verzerrungen:**

1. **Survivorship Bias:** nur heutige Indexmitglieder. Verlierer, die aus dem Index fielen, fehlen. Delisting-Renditen fehlen ebenfalls (Shumway 1997). Die Ergebnisse sind daher wahrscheinlich zu gut.
2. **Look-ahead durch Universumsauswahl:** Die heutige Indexzugehörigkeit war damals nicht bekannt.
3. **Datenqualität:** Yahoo-Kurse sind inoffiziell; einzelne historische Fehler sind möglich.
4. **Mehrfachtests:** Es werden 13 Varianten verglichen. Die beste Variante ist auch zufällig die beste (Harvey, Liu & Zhu 2016). Unterschiede von wenigen Zehntelprozent sind nicht belastbar.

## 8. Quellen

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

*Momentum Lab ist ein privates Analysewerkzeug und keine Anlageberatung.*
