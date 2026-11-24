# Momentum Lab

Persönliche, kostenlose Momentum-Investing-App fürs iPhone (Web-App für den Home-Bildschirm).

- **Screening:** rund 1.300 Aktien des MSCI World, risikoadjustiertes 6- und 12-Monats-Momentum (MSCI-Stil), strenge Datenprüfung, höchstens 10 Kandidaten und ein Top Pick nur bei voller Erfüllung aller Regeln.
- **Mein Depot:** Kauftranchen, Teilverkäufe, Dividenden, Splits, Sparpläne, FIFO-Gewinne, Fremdwährungen. Die Daten liegen **nur auf deinem iPhone** und lassen sich als Backup-Datei sichern.
- **Portfolio Intelligence:** HALTEN, NACHKAUFEN, SPARPLAN FORTSETZEN/STOPPEN, VERKAUF PRÜFEN, VERKAUF, jeweils mit Begründung, Kriterien, Dringlichkeit und nächster Prüfung.
- **Backtesting:** vorab festgelegte Varianten mit Kosten, deutschen Steuern, Marktphasen und klar ausgewiesenen Verzerrungen.

## Aufbau
```
app/        Web-App (HTML/CSS/JavaScript, ohne Fremdbibliotheken, offline-fähig)
pipeline/   Täglicher Datenlauf (Python): Universum, Kurse, Qualität, Momentum, Details, Backtest
tests/      Python- und JavaScript-Tests (laufen vor jeder Veröffentlichung)
tools/      Site-Build, Symbole
docs/       Methodik, Datenquellen, Anleitung, Workflow-Vorlage
config/     watchlist.txt – zusätzliche Symbole (z. B. Aktien außerhalb des MSCI World)
archive/    vom Datenlauf gepflegt: Monats-Screenings, Universums-Historie, Laufprotokoll
```

## Ablauf
GitHub Actions (öffentliches Repository, kostenlos) startet werktags nach US-Börsenschluss den Datenlauf, testet den Code und veröffentlicht App und Daten auf GitHub Pages. Die App lädt nur Dateien vom eigenen Server.

## Lokal testen
```
pip install -r pipeline/requirements.txt pytest
python -m pytest -q tests && node tests/js/run.mjs
python tools/build_site.py --out site
python -m pipeline.run --mode demo --out site/data      # synthetische DEMO-Daten
python -m http.server -d site 8000
```

Dokumentation: [Methodik](docs/METHODIK.md) · [Datenquellen](docs/DATENQUELLEN.md) · [Anleitung](docs/ANLEITUNG.md)

*Privates Analysewerkzeug, keine Anlageberatung.*
