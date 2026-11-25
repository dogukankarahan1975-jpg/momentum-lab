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
- Steuern: Abgeltungsteuer 26,375 %, FIFO, Sparerpauschbetrag 1.000 €/Jahr, Verlustvortrag; ETF mit 30 % Teilfreistellung. Ergebnisse vor und nach Steuern (inkl. fiktiver Endbesteuerung).
- Vorab festgelegte Varianten (`config.BACKTEST_VARIANTS`): einfaches 12-1, 6+12 kombiniert, risikoadjustiert (MSCI-Stil) mit Top 10/5/1 und Scoregewichtung, App-Regeln (Puffer + Bestätigung) mit Top 10 und Top Pick, App-Regeln + 200-Tage-Filter, + Markt-Trendfilter, + MSCI-Volatilitätsschock-Regel, Halteband 10 %/30 % (Sensitivität), Sparpläne (Top Pick, Top 10, MSCI-World-ETF).
- Maßstäbe: gleichgewichtetes Universum (gleiche Verzerrung, daher fairster Vergleich), iShares Core MSCI World (EUNL), iShares MSCI World Momentum (IS3R), US-Momentum (MTUM). ETF-Daten enthalten Fondskosten und beginnen erst mit der Auflage.
- Kennzahlen: Rendite p. a., Gesamtrendite, Volatilität, maximaler Verlust, Sharpe (Zins 0 %), Anteil besserer Monate, Gewinn-Trades, Anzahl Trades, Umschlag, Cash-Anteil, Steuern, Kostenszenarien, Marktphasen (benannte Krisen, Bullen-/Bärenmonate).

**Bekannte, nicht behebbare Verzerrungen:**

1. **Survivorship Bias:** nur heutige Indexmitglieder. Verlierer, die aus dem Index fielen, fehlen. Delisting-Renditen fehlen ebenfalls (Shumway 1997). Die Ergebnisse sind daher wahrscheinlich zu gut.
2. **Look-ahead durch Universumsauswahl:** Die heutige Indexzugehörigkeit war damals nicht bekannt.
3. **Datenqualität:** Yahoo-Kurse sind inoffiziell; einzelne historische Fehler sind möglich.
4. **Mehrfachtests:** Es werden 13 Varianten verglichen. Die beste Variante ist auch zufällig die beste (Harvey, Liu & Zhu 2016). Unterschiede von wenigen Zehntelprozent sind nicht belastbar.


<a name="stage-2"></a>
## 8. Stage 2 – Fortsetzungsanalyse (S2 v1.0.0)

### 8.1 Ziel und Einordnung

Stage 1 bleibt unverändert und liefert höchstens zehn Kandidaten. Stage 2 prüft **jede dieser Aktien** zusätzlich und
beantwortet eine Frage: *Ist die bisherige Stärke durch mehrere unabhängige Faktoren gestützt, sodass eine Fortsetzung
nachvollziehbar ist, oder trägt sie vor allem ein kurzer Kursschub?* Ergebnis je Kandidat: ein Score von 0 bis 10,
Datenqualität, Risiko-Stufe (Anti-Peak), Outperformance-Einschätzung gegenüber dem MSCI World, Sparplan-Entscheidung und
Begründungen. Stage 2 wird automatisch im nächtlichen Datenlauf berechnet (`pipeline/stage2.py`). Es gibt keine
Garantie für eine Outperformance. Die Gewichte und Entscheidungsschwellen sind Vorgaben des Nutzers und **heuristisch**.
Sie sind nicht als Erfolgswahrscheinlichkeiten zu lesen (Abschnitt 8.9).

### 8.2 Skalierung: Perzentile gegen feste Vergleichsgruppen

Jede Kennzahl wird als Perzentil gegen ihre Vergleichsgruppe gemessen:
`p = (Anzahl schlechterer Werte + ½ · Anzahl gleicher Werte) / Anzahl Werte`. Bei Kennzahlen, bei denen weniger besser
ist (z. B. Verschuldung), wird das Vorzeichen umgedreht. Perzentile sind robust gegen Ausreißer. Keine einzelne extreme
Kennzahl kann eine Kategorie dominieren, und Aktien aus verschiedenen Märkten werden vergleichbar.

| Vergleichsgruppe | Frage | verwendet für |
|---|---|---|
| alle zulässigen MSCI-World-Aktien (Stage-1-Datenprüfung bestanden) | Ist die Aktie besser als der Markt? | A, B, C, D |
| Aktien desselben GICS-Sektors (mindestens 15 Werte, sonst alle) | Branchen fair vergleichen (Banken ≠ Software) | E, Bewertungsblock von F |
| Momentum-Vergleichsgruppe = Stage-1-Kandidatengruppe (bestes Zehntel, 6M und 12M positiv; unter 30 Aktien: beste 20 %) | Ist sie überhitzter als *andere* Momentum-Aktien? | Überhitzungsblock von F |

Die Überhitzung wird bewusst nur gegen andere Momentum-Aktien gemessen. Gegen das ganze Universum wäre jede
Momentum-Aktie „überhitzt“, und starkes Momentum würde allein wegen der Performance bestraft.

**Kategorie-Score** = 10 × Mittel der verfügbaren Perzentile. A und F bestehen aus zwei gleich gewichteten Blöcken
(A: Niveau und Konsistenz; F: Bewertung und Überhitzung). Innerhalb einer Kategorie bzw. eines Blocks sind alle
Kennzahlen gleich gewichtet. Das ist die am wenigsten willkürliche Wahl ohne validierte Gewichte.

**Gesamtscore** = gewichtetes Mittel der Kategorien: A 20 %, B 20 %, C 20 %, D 15 %, E 10 %, F 15 %. Er wird nur
berechnet, wenn Kategorien mit mindestens 80 % des Gewichts verfügbar sind. Fehlt eine Kategorie, werden die übrigen
neu gewichtet. Das steht dann sichtbar beim Score, die Datenqualität sinkt auf LOW, und es gibt keine
Sparplanfreigabe.

**Aktivierung einer Kennzahl:** Sie zählt nur, wenn in ihrer Vergleichsgruppe mindestens 60 % der Aktien einen Wert
haben (und mindestens 30 Werte). Sonst ist sie für **alle** Aktien ausgesetzt, damit für alle dieselben Regeln gelten.
Ausgesetzte Kennzahlen werden angezeigt.

### 8.3 Kennzahlen je Kategorie

Alle Kursdaten sind dividendenbereinigt. Momentum in Landeswährung wie in Stage 1, Vergleiche mit dem MSCI World in Euro.
Der MSCI World ist der iShares Core MSCI World UCITS ETF (EUNL, inklusive Fondskosten).

**A Momentum-Persistenz (20 %)**: Block *Niveau*: 12-1-, 6-1-, 3-1- und 12-2-Monats-Momentum (Jegadeesh & Titman 1993;
die Lücke zum jüngsten Monat meidet das Kurzfrist-Reversal). Block *Konsistenz*: Anteil positiver Monate im 12-1-Fenster
(Grinblatt & Moskowitz 2004) und die Sprunghaftigkeit der Kursgewinne nach Da, Gurun & Warachka (2014):
`ID = Vorzeichen(12-1-Rendite) × (Anteil Minus-Tage − Anteil Plus-Tage)`. Kontinuierliche Gewinne (niedriger ID) setzen
sich häufiger fort als Gewinne aus wenigen Sprüngen. Damit wird nicht automatisch die höchste 12-Monats-Rendite bevorzugt.

**B Gewinn- und Revisionsmomentum (20 %)**: Revisionsbreite (Erhöhungen minus Senkungen der Gewinnschätzungen in 30 Tagen
je Analyst, Mittel aus laufendem und nächstem Geschäftsjahr), Änderung der Gewinnschätzung gegenüber vor 30 und 90 Tagen
(Chan, Jegadeesh & Lakonishok 1996: Gewinnrevisionen erklären einen Teil des Kursmomentums), durchschnittliche
Gewinnüberraschung der letzten vier Quartale (Bernard & Thomas 1989), Umsatz- und Gewinnwachstum je Aktie (Quartal ggü.
Vorjahr), Veränderung der operativen Marge (Geschäftsjahr) und Änderung der Umsatzschätzung gegenüber vor ca. 90 Tagen.
Die letzte Kennzahl stammt aus der **eigenen** Wochen-Historie der App (gleiches Geschäftsjahr). Sie wird automatisch
aktiv, sobald genug Historie vorliegt (ab etwa drei Monaten nach Einführung). Mindestens drei Kennzahlen, davon eine aus
Revisionen oder Überraschungen. Die Unternehmensprognose (Guidance) gibt es nicht kostenlos in strukturierter Form; sie
fließt nicht ein.

**C Relative Stärke und Outperformance (20 %)**: marktbereinigtes Momentum (Monatsrenditen der letzten 36 Monate gegen
den MSCI World regressiert; Summe von `Rendite − Beta × MSCI World` in den Monaten t−12 bis t−2, geteilt durch die
Restschwankung). Es misst den Teil der Stärke, den der steigende Gesamtmarkt nicht erklärt (verwandt mit dem
idiosynkratischen Momentum bei Gutierrez & Prinsky 2007 und Blitz, Huij & Martens 2011). Dazu: Anteil der letzten
12 Monate, in denen die Aktie den MSCI World schlug, relative Stärke zum eigenen Sektor über 6-1 Monate
(Branchen-Momentum: Moskowitz & Grinblatt 1999) und zum Heimatmarkt (Land mit mindestens 20 zulässigen Aktien, sonst
MSCI-Region). Sektor- und Heimatmarktvergleich: gleichgewichteter Durchschnitt der zulässigen Aktien der Gruppe. Offizielle
MSCI-Sektorindizes sind nicht kostenlos.

**D Trendqualität und Kursstärke (15 %)**: Nähe zum 52-Wochen-Hoch (George & Hwang 2004: Aktien nahe ihrem Hoch setzen
den Trend eher fort), Abstand der 50- zur 200-Tage-Linie, Trendstabilität (R² des logarithmierten Kurses über 6 Monate
mit dem Vorzeichen der Steigung, damit ein stabiler Abwärtstrend nicht als Qualität zählt), maximaler Rückgang über
12 Monate, durchschnittliche Überrendite in den Monaten mit fallendem MSCI World (36 Monate, mindestens 6 solche Monate)
sowie der Anteil der Monate mit höherem Hoch **und** höherem Tief (12 Monate, Monatshochs und -tiefs aus Schlusskursen).

**E Unternehmensqualität und Fundamentaldaten (10 %)**: Eigenkapitalrendite, Kapitalrendite ROIC vor Steuern
(EBIT ÷ investiertes Kapital, wie bei Greenblatts Kapitalrendite; ohne frei gewählten Steuersatz), operative Marge,
Free-Cashflow-Marge, Verschuldung (Finanzschulden ÷ Eigenkapital, niedriger besser), Zinsdeckung (EBIT ÷ Zinsaufwand)
und Veränderung der Aktienanzahl (Verwässerung, niedriger besser; Pontiff & Woodgate 2008). Profitabilität und
Qualität: Novy-Marx (2013), Asness, Frazzini & Pedersen (2019). **Banken und Versicherer** (Sektor Finanzen) haben einen
eigenen Satz: Eigenkapitalrendite, Gesamtkapitalrendite, Nettomarge und Verwässerung. Free Cashflow, Margen und
Verschuldung sind für sie nicht sinnvoll. Alle Perzentile werden innerhalb des Sektors gebildet. Wettbewerbsposition,
Marktposition und Geschäftsmodell lassen sich ohne subjektive Urteile nicht automatisch bewerten. Sie fließen nicht ein;
die App verlinkt die Quellen.

**F Bewertung, Volatilität und Überhitzung (15 %)**: Block *Bewertung* (innerhalb des Sektors): Gewinnrendite forward
und für 12 Monate (Kehrwert des KGV; Verluste ergeben eine negative Gewinnrendite und damit einen schlechten Rang),
EBITDA ÷ Unternehmenswert und Umsatz ÷ Börsenwert (nicht für Finanzwerte), Buchwert ÷ Börsenwert (nur Finanzwerte) und
PEG (Forward-KGV ÷ erwartetes Gewinnwachstum des nächsten Jahres, nur bei positivem Wachstum). Gewinnrenditen statt KGV,
weil sie Verluste sinnvoll einordnen (Fama & French 1992; Asness, Moskowitz & Pedersen 2013). Block *Überhitzung*
(gegen die Momentum-Gruppe): Abstand zur 50- und 200-Tage-Linie in Standardabweichungen
(`(Kurs ÷ Linie − 1) ÷ (σ_täglich × √Tage)`), Kursbewegung des letzten Monats in Standardabweichungen und Volatilität
über 3 Monate (Ang et al. 2006). Die Nähe zum 52-Wochen-Hoch zählt bewusst **nicht** als Risiko (siehe D).

**Kontrolle widersprüchlicher Daten:** Die Gewinnrendite wird aus Gewinn je Aktie und Kurs in derselben Währung berechnet
(EZB-Kurse; Pence werden in Pfund umgerechnet). Weicht sie um mehr als den Faktor 3 vom KGV des Datenanbieters ab,
deutet das auf einen Währungs- oder Einheitenfehler hin. Der Wert wird dann nicht verwendet und als widersprüchlich
markiert.

### 8.4 Datenqualität

| Stufe | Regel |
|---|---|
| HIGH | alle sechs Kategorien berechenbar, mindestens 90 % der anwendbaren Kennzahlen vorhanden, Kennzahlen höchstens 7 Tage alt |
| MEDIUM | alle sechs Kategorien berechenbar, Kennzahlen höchstens 21 Tage alt |
| LOW | Score berechenbar (≥ 80 % Gewicht), aber eine Kategorie fehlt oder ältere Daten → **keine Sparplanfreigabe** |
| INSUFFICIENT | kein Score möglich oder Datenproblem aus Stage 1 → keine Entscheidung |

Fehlende Werte werden nie geschätzt oder aufgefüllt. Ein fehlender Wert ist kein negatives Signal. Er wird ausgelassen
und als fehlend aufgelistet. Ein negativer Wert (z. B. sinkende Gewinnschätzung) ist dagegen ein echtes Signal.
Kennzahlen, die älter als 21 Tage sind, gelten als fehlend. Mindestanforderungen je Kategorie: A je Block 2 bzw.
1 Kennzahl, B 3 (davon eine aus Revisionen/Überraschungen), C 2, D 3, E die Hälfte der anwendbaren, F je Block 1 bzw. 2.

### 8.5 Anti-Peak- und Anti-Chasing-Modul

Es gibt keine pauschale Regel gegen Aktien nahe ihrem Hoch. Geprüft wird eine Kombination. Je Konzept zählt höchstens
**ein** Warnsignal, damit korrelierte Werte nicht doppelt zählen:

| Signal | Auslöser (Grenze) |
|---|---|
| technisch: weit über dem Trend | Abstand zur 50- **oder** 200-Tage-Linie im obersten Zehntel der Momentum-Gruppe |
| technisch: Kursbeschleunigung | Rendite des letzten Monats > 2 Standardabweichungen (extrem: > 3) |
| technisch: Volatilität | 3-Monats-Volatilität im obersten Zehntel der Momentum-Gruppe |
| technisch, ergänzend: RSI | RSI(14) ≥ 80; zählt nur zusammen mit einem anderen technischen Signal |
| Trend | Trendstatus „schwächer werdend“ oder „Trendbruch“ |
| fundamental: Erwartungen sinken | Gewinnschätzung niedriger als vor 90 Tagen **oder** mehr Senkungen als Erhöhungen (Divergenz, wenn der Kurs gleichzeitig steigt) |
| fundamental: verfehlt | letzte Quartalszahlen unter der Erwartung |
| Bewertung | Forward-Gewinnrendite im teuersten Zehntel des Sektors **oder** erwarteter Verlust |
| Ereignis (nur Hinweis) | Quartalszahlen in den nächsten 14 Tagen |

Die Grenzen sind Konventionen: das oberste Zehntel und 2 bzw. 3 Standardabweichungen, statistische Ausnahme-Grenzen.
Für RSI gilt in starken Trends die Konvention 80 statt 70.

| Stufe | Regel |
|---|---|
| CRITICAL | fundamentales Signal **und** (mindestens 2 technische Signale **oder** Bewertungssignal **oder** Trendbruch) |
| HIGH | extreme Beschleunigung, erhöhte Volatilität oder mindestens 2 Warnsignale |
| ELEVATED | genau ein Warnsignal |
| NORMAL | keines |

Die Kennzahlen der Überhitzung stecken außerdem im Score (Kategorie F). Die Stufen wirken zusätzlich auf die Entscheidung
(8.6). Zu jeder Warnung zeigt die App die auslösenden Kennzahlen und Grenzen.

### 8.6 Sparplan-Entscheidung

Die Schwellen gelten für den angezeigten Score (eine Nachkommastelle): ab 9,0 **EXCEPTIONAL**, ab 8,5 **STRONG BUY
CANDIDATE** (beide: Sparplanstart grundsätzlich möglich), ab 7,5 **WATCHLIST**, ab 6,0 **NO ENTRY**, darunter **REJECT**.
Deckel (sie heben nie an):

- Risiko CRITICAL → **HARD RISK**, keine Freigabe unabhängig vom Score.
- Risiko HIGH → höchstens WATCHLIST, bei mindestens 3 Warnsignalen höchstens NO ENTRY („je nach Ausprägung“).
- Datenqualität LOW → höchstens WATCHLIST. INSUFFICIENT → INSUFFICIENT DATA.
- Kurs nicht von der Zweitquelle (iShares) bestätigt → höchstens WATCHLIST, wie beim Top Pick.
- Veraltete Daten (App-Aktualitätsregeln) → keine Entscheidung.

Die App muss keine Aktie freigeben. „Keine Freigabe“ ist ein gültiges Ergebnis. Die bestehenden Depot-Signale
(Sparplan fortsetzen/stoppen) folgen weiter den Regeln aus Abschnitt 6. Stage 2 betrifft den **Start** neuer Sparpläne.

### 8.7 Outperformance-Einschätzung gegenüber dem MSCI World

Sechs Säulen mit natürlichen Schwellen (meist 0), gezählt wie beim F-Score von Piotroski (2000):
(1) stärker als der MSCI World über 3, 6 **und** 12 Monate; (2) in mindestens 7 der letzten 12 Monate besser (Mehrheit);
(3) Gewinnerwartungen steigen; (4) Umsatz und Gewinn wachsen; (5) risikobereinigt besser (12-Monats-Rendite je
Schwankungseinheit höher als beim MSCI World); (6) keine Bewertungswarnung und Risiko höchstens ELEVATED.
Ab 5 von 6 erfüllten Säulen **HIGH**, ab 4 **MODERATE**, ab 3 **MARKET-LIKE**, darunter **LOW**. Weniger als 5 prüfbare
Säulen ergeben **INSUFFICIENT DATA**. Bei CRITICAL immer LOW, bei HIGH höchstens MODERATE. Das sind relative
Research-Einschätzungen und **keine** Wahrscheinlichkeiten, solange kein validiertes Prognosemodell mit
Out-of-Sample-Ergebnissen vorliegt.

### 8.8 Trendstatus

Trendbruch: Kurs unter der 200-Tage-Linie. Schwächer werdend: Kurs unter der fallenden 50-Tage-Linie oder das letzte
Quartal liegt mehr als 2 Standardabweichungen unter dem Tempo der drei Quartale davor. Aufwärtstrend: 50- über
200-Tage-Linie und 200-Tage-Linie steigend. Beschleunigend: zusätzlich Kurs über der 50-Tage-Linie und das letzte
Quartal mehr als 2 Standardabweichungen über dem Tempo davor. Sonst: Seitwärtsbewegung.

### 8.9 Validierung: was getestet ist und was nicht

- **Teil-Backtest** (`pipeline/stage2_backtest.py`, monatlich im Datenlauf): Nur die kursbasierten Bausteine (A, C, D,
  Überhitzungsblock von F) lassen sich zeitpunktgenau rekonstruieren. Sie werden mit denselben Funktionen wie live
  berechnet. Vorab festgelegte Varianten: Stage 1 Top 10 und Top 5, Stage 1+2 beste 5 der Top 10, Stage 1+2 Top 10 bzw.
  beste 5 nach Score gewichtet. Haltedauer 1, 3, 6 und 12 Monate (überlappende Tranchen nach Jegadeesh & Titman 1993).
  Kosten wie im Haupt-Backtest, Kostenszenarien. Kennzahlen: Rendite p. a., Gesamtrendite, Mehrrendite gegenüber dem
  MSCI World, Sharpe, Volatilität, maximaler Verlust, Trefferquote der einzelnen Auswahlentscheidungen gegenüber dem
  MSCI World, durchschnittliche Rendite der Gewinner und Verlierer, Zahl der Entscheidungen, Umschlag. Dazu kommt die
  **Prognosegüte**: monatliche Rang-Korrelation (IC) zwischen Score und späterer Rendite innerhalb der
  Stage-1-Kandidatengruppe mit t-Wert nach Newey-West. Zeitraum: ab 36 Monaten MSCI-World-Daten in EUR (ETF seit
  09/2009), also ohne Finanzkrise und ohne den Momentum-Crash 2009.
- **Nicht testbar und bewusst nicht ersetzt:** B, E und die Bewertung in F, außerdem die Schwellen und Regeln der
  Datenqualität. Für Analystenrevisionen, Überraschungen und Kennzahlen gibt es keine kostenlosen zeitpunktgenauen
  Historien. Heutige Werte rückwirkend zu verwenden wäre Look-ahead.
- **Eigene Point-in-Time-Historie:** Ab Pipeline 0.2.0 archiviert der Datenlauf wöchentlich die Kennzahlen aller Aktien
  (`archive/fundamentals/`) und monatlich die Stage-2-Entscheidungen (`archive/stage2/`).
- **Live-Protokoll:** Die App wertet ihre eigenen früheren Entscheidungen aus (Rendite bis heute gegenüber dem MSCI World
  je Entscheidungsgruppe). Das ist die einzige echte Out-of-Sample-Prüfung. Für belastbare Aussagen braucht sie Jahre.
- **Für eine wissenschaftliche Validierung nötig:** (1) 2 bis 3 Jahre eigene Point-in-Time-Daten, dann ein Backtest aller
  Kategorien über diese Zeit; (2) zeitpunktgenaue Indexmitgliedschaften gegen den Survivorship Bias; (3) Vergleich mit
  Stage 1 allein bei gleicher Aktienzahl; (4) Prüfung der Schwellen nur auf Daten, die bei der Festlegung unbekannt waren;
  (5) Korrektur für Mehrfachtests (Harvey, Liu & Zhu 2016). Änderungen an Gewichten oder Schwellen erfolgen nur als neue,
  dokumentierte Version.

### 8.10 Bekannte Grenzen von Stage 2

1. **Datenquelle:** Kennzahlen und Analystenschätzungen kommen von Yahoo Finance (inoffiziell, kostenlos, ohne Vertrag).
   Außerhalb der USA ist die Analystenabdeckung lückenhafter. Fehlt sie, fehlt Kategorie B.
2. **Guidance und qualitative Faktoren** fließen nicht ein (Abschnitt 8.3).
3. **Gewichte und Schwellen** sind Vorgaben des Nutzers und nicht validiert.
4. **Teil-Backtest:** nur Kursbausteine, Survivorship Bias, Zeitraum ab 2012, Mehrfachtests.
5. **Aufbauphase:** In den ersten Läufen werden die Vergleichsdaten aufgebaut. Bis mindestens 60 % des Universums
   Kennzahlen haben, sind die fundamentalen Kategorien ausgesetzt, und Stage 2 gibt keine Freigabe.

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
