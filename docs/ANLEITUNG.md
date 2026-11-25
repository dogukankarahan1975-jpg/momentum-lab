# Einrichtung auf dem iPhone (einmalig, ca. 20 Minuten)

Du brauchst: Safari, die Datei `momentum-lab.zip` (in „Dateien“ gespeichert) und ein kostenloses GitHub-Konto.

## 1. Projekt anlegen
1. Safari: **github.com/new** öffnen (angemeldet).
2. Repository name: `momentum-lab`
3. **Public** auswählen.
4. Haken bei **Add a README file** setzen.
5. **Create repository** antippen.

## 2. Code hochladen
1. In Safari links in der Adressleiste **aA** antippen → **Desktop-Website anfordern**.
2. Im Projekt: **Add file** → **Upload files** → **choose your files** → **Datei auswählen** → `momentum-lab.zip`.
3. Unten **Commit changes** antippen.

## 3. Website einschalten
1. Im Projekt oben **Settings** → links **Pages**.
2. Bei **Build and deployment → Source** die Option **GitHub Actions** wählen.

## 4. Datenlauf einrichten
1. Zurück zu **Code** → **Add file** → **Create new file**.
2. Als Dateiname eintippen: `.github/workflows/momentum-lab.yml`
3. Den Workflow-Text einfügen (aus dem Chat oder `docs/workflow/momentum-lab.yml`).
4. **Commit changes…** → **Commit changes**.

Der erste Lauf startet sofort (Reiter **Actions**). Er dauert 20–40 Minuten, weil alle Kurse seit 2000 geladen und der Backtest gerechnet wird. Ein grüner Haken bedeutet fertig.

## 5. App installieren
1. Safari: `https://DEIN-BENUTZERNAME.github.io/momentum-lab/`
2. **Teilen** → **Zum Home-Bildschirm** → **Hinzufügen**.
3. Die App **nur über das neue Symbol** öffnen (Safari und App haben getrennte Speicher).
4. In der App: Zahnrad → **Dauerhaften Speicher anfordern**.

## Alltag
- **Haltedauer:** Beim Erfassen eines Kaufs wählst du „Wie lange willst du halten?“ (Verkaufssignal der App, 6 oder 12 Monate) und ob im Minus bis ±0 gewartet wird. Depot → „Verkaufstermine in den Kalender“ legt Kalender-Erinnerungen an. Am Termin zeigt das Depot „Verkaufen“ oder „Halten bis ±0“.
- **Kauf-Rechner** (Depot → Kauf-Rechner): Einstand und Gutschrift der Verkäufe eintragen, dazu neues Geld. Der Rechner zeigt den Gewinn und den Betrag je neuer Aktie nach 1 € Gebühr.
- **Monats-Screening-Erinnerung:** Einstellungen → Erinnerungen.
- **Backtest → Simulator:** Strategien antippen, Budget, Dynamik, Gebühren, Spread und Haltedauer einstellen. Darunter steht, was aus dem Geld geworden wäre (vor und nach Steuern), Jahr für Jahr mit Bestand, und welche Aktien in jedem Monat auf der Liste standen.
- **SCREENING STARTEN** prüft den neuesten Datenstand (werktags nachts aktualisiert), zeigt Stage 1 und Stage 2 und bewertet dein Depot.
- **Top 10 → Finale Rangfolge**: die Stage-1-Kandidaten, neu sortiert nach dem Stage-2-Score (0 bis 10), mit Entscheidung, Risiko-Stufe, Datenqualität und Outperformance-Einschätzung. **Top 10 → Stage 1** zeigt die ursprüngliche Momentum-Liste. Die App merkt sich die zuletzt gewählte Ansicht.
- **Aktie antippen**: Stage-2-Details mit aufklappbaren Abschnitten (Momentum, Gewinne, Trend, Fundamentaldaten, Bewertung und Risiko), Begründungen und Quellen.
- **Erste Tage nach dem Stage-2-Update**: Der Datenlauf baut die Vergleichsdaten für rund 1.200 Aktien schrittweise auf (1 bis 3 Nächte). Bis dahin zeigt Stage 2 „INSUFFICIENT DATA“ statt einer Freigabe. Das ist gewollt.
- **Backup**: Zahnrad → **Backup exportieren** → **In Dateien sichern** (iCloud Drive). Die App erinnert dich.
- **Wiederherstellen**: Zahnrad → **Backup importieren**.

## Updates
Neue Version = neue `momentum-lab.zip` wie in Schritt 2 hochladen. Der Datenlauf installiert sie automatisch und veröffentlicht die App neu. Deine Depotdaten bleiben unberührt, denn sie liegen nur auf dem iPhone.

## Wenn etwas nicht klappt
- **Actions zeigt ein rotes ×:** Lauf antippen → fehlgeschlagenen Schritt öffnen → Screenshot an Claude schicken.
- **App zeigt „Datenlauf fehlgeschlagen“:** Die App zeigt die letzten gültigen Daten mit Warnung. Meist erledigt sich das beim nächsten Lauf. Manuell starten: Actions → Momentum Lab → **Run workflow**.
- **Zeitplan pausiert (60 Tage ohne Aktivität):** Actions → Momentum Lab → **Enable workflow**.
- **Aktie im Depot ohne Kurs:** Sie ist nicht im MSCI World. Trage ihr Yahoo-Symbol in `config/watchlist.txt` ein (Projekt → Datei → Stift-Symbol) oder pflege den Kurs manuell in der App.
