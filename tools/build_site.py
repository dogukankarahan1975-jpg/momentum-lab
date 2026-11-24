"""Baut den veröffentlichten Ordner: app/ -> site/ (ohne site/data), setzt Build-Kennung und Dateiliste.

Aufruf: python tools/build_site.py --out site [--build abc123]
"""
import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site")
    ap.add_argument("--build", default=None)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    src = ROOT / "app"
    for item in src.iterdir():
        dst = out / item.name
        if item.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(item, dst)
        else:
            shutil.copy2(item, dst)
    build = a.build or datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    files = ["./"] + sorted(
        str(p.relative_to(out)).replace("\\", "/") for p in out.rglob("*")
        if p.is_file() and not str(p.relative_to(out)).startswith("data/") and p.name not in ("sw.js", "package.json", "robots.txt")
    )
    sw = (out / "sw.js").read_text(encoding="utf-8")
    sw = sw.replace("'__BUILD__'", json.dumps(build)).replace("__FILES__", json.dumps(files))
    (out / "sw.js").write_text(sw, encoding="utf-8")
    idx = (out / "index.html").read_text(encoding="utf-8")
    idx = idx.replace('<meta name="theme-color"', f'<meta name="ml-build" content="{build}">\n<meta name="theme-color"', 1)
    (out / "index.html").write_text(idx, encoding="utf-8")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Site gebaut: {len(files)} App-Dateien, Build {build}")


if __name__ == "__main__":
    main()
