"""Browser-Rauchtest (optional, lokal): python tests/e2e/smoke.py http://localhost:8765/ /tmp/shots
Benötigt Playwright + Chrome. Prüft alle Ansichten im iPhone-Format auf JavaScript-Fehler und erstellt Screenshots."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8765/"
SHOTS = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/shots")
SHOTS.mkdir(parents=True, exist_ok=True)
errors = []

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                              locale="de-DE", timezone_id="Europe/Berlin")
    page = ctx.new_page()
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type in ("error",) else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

    def shot(name, full=True):
        page.wait_for_timeout(500)
        page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=full)

    page.goto(BASE + "#/")
    page.wait_for_selector("text=Übersicht")
    shot("01-dashboard")
    # Position erfassen (Kauf) über die Suche
    page.goto(BASE + "#/depot")
    page.wait_for_selector("#add")
    page.click("#add")
    page.fill("#q", "DMO021")
    page.wait_for_selector("#res button")
    page.click("#res button")
    page.fill("#date", "2024-03-15")
    page.fill("#qty", "10")
    page.fill("#price", "45,50")
    page.select_option("#cur", "USD")
    page.wait_for_timeout(200)
    page.fill("#fees", "1")
    shot("02-form-buy", full=False)
    page.click("#save")
    page.wait_for_selector("text=Transaktionen")
    shot("03-position")
    # zweite Tranche, Teilverkauf, Dividende
    page.click("button[data-t=BUY]")
    page.fill("#date", "2025-01-10"); page.fill("#qty", "5"); page.fill("#price", "60"); page.click("#save")
    page.wait_for_timeout(400)
    page.click("button[data-t=SELL]")
    page.fill("#date", "2025-06-10"); page.fill("#qty", "3"); page.fill("#price", "70"); page.click("#save")
    page.wait_for_timeout(400)
    page.click("button[data-t=DIV]")
    page.fill("#date", "2025-07-01"); page.fill("#div", "12,34"); page.click("#save")
    page.wait_for_timeout(400)
    # Verkauf über Bestand muss abgelehnt werden
    page.click("button[data-t=SELL]")
    page.fill("#date", "2025-08-10"); page.fill("#qty", "999"); page.fill("#price", "70"); page.click("#save")
    page.wait_for_selector("#err:not([hidden])")
    assert "Bestand" in page.inner_text("#err"), page.inner_text("#err")
    page.click("[data-close]")
    # Sparplan
    page.click("#newplan")
    page.fill("#amt", "100"); page.fill("#start", "2025-09-01"); page.fill("#day", "1"); page.click("#save")
    page.wait_for_timeout(500)
    shot("04-position-full")
    # zweite Position (nicht im Universum, manuell)
    page.goto(BASE + "#/depot"); page.wait_for_selector("#add"); page.click("#add")
    page.click("#manual-d summary"); page.fill("#m-name", "Testfirma ohne Daten"); page.fill("#m-sym", "XYZ.DE")
    page.fill("#qty", "2"); page.fill("#price", "100"); page.click("#save")
    page.wait_for_timeout(600)
    # dritte Position aus Universum (Kandidat 2)
    page.goto(BASE + "#/depot"); page.wait_for_selector("#add"); page.click("#add")
    page.fill("#q", "DMO028"); page.wait_for_selector("#res button"); page.click("#res button")
    page.fill("#qty", "20"); page.fill("#price", "30"); page.click("#save")
    page.wait_for_timeout(600)
    # schwache Aktie im Depot (unterer Rang) -> Verkaufssignal erwartet
    page.goto(BASE + "#/depot"); page.wait_for_selector("#add"); page.click("#add")
    page.fill("#q", "DMO008"); page.wait_for_selector("#res button"); page.click("#res button")
    page.fill("#qty", "5"); page.fill("#price", "20"); page.click("#save")
    page.wait_for_timeout(600)
    # Screening
    page.goto(BASE + "#/screening")
    page.wait_for_selector("#run")
    page.click("#run")
    page.wait_for_selector("text=Top 10 ansehen", timeout=30000)
    shot("05-screening")
    page.goto(BASE + "#/top10"); page.wait_for_selector("h1:has-text('Top 10')"); shot("06-top10")
    page.goto(BASE + "#/aktie/DMO021"); page.wait_for_selector("text=Kursentwicklung"); shot("07-stock")
    page.goto(BASE + "#/aktie/DMO008"); page.wait_for_selector("text=Warum nicht"); shot("07b-stock-excluded")
    page.goto(BASE + "#/depot"); page.wait_for_selector("text=Positionen"); page.wait_for_timeout(800); shot("08-depot")
    page.goto(BASE + "#/signale"); page.wait_for_selector("h1"); shot("09-signals")
    page.goto(BASE + "#/backtest"); page.wait_for_selector("text=Kennzahlen"); page.wait_for_timeout(800); shot("10-backtest")
    page.goto(BASE + "#/einstellungen"); page.wait_for_selector("text=Datenstatus"); shot("11-settings")
    page.goto(BASE + "#/"); page.wait_for_selector("text=Übersicht"); shot("12-dashboard-after")
    # Backup-Export (Download-Fallback in Chrome)
    page.goto(BASE + "#/einstellungen"); page.wait_for_selector("#exp")
    with page.expect_download() as dl:
        page.click("#exp")
    path = dl.value.path()
    data = Path(path).read_text()
    assert '"app": "momentum-lab"' in data, data[:200]
    SHOTS.joinpath("backup.json").write_text(data)
    # Alles löschen und Backup importieren
    page.click("#wipe"); page.fill("[data-req]", "LÖSCHEN"); page.click("[data-yes]")
    page.wait_for_timeout(600)
    page.goto(BASE + "#/depot"); page.wait_for_selector("text=Noch keine Positionen")
    page.goto(BASE + "#/einstellungen"); page.wait_for_selector("#imp")
    page.set_input_files("#file", str(SHOTS / "backup.json"))
    page.wait_for_selector("#rep"); page.click("#rep"); page.click("[data-yes]")
    page.wait_for_timeout(800)
    page.goto(BASE + "#/depot"); page.wait_for_selector("text=Positionen")
    restored = page.inner_text("main")
    assert "Testfirma ohne Daten" in restored and "Demo" in restored, restored[:500]
    shot("13-depot-restored")
    browser.close()

print("FEHLER:" if errors else "Keine JavaScript-Fehler.")
for e in errors:
    print(" ", e)
sys.exit(1 if errors else 0)
