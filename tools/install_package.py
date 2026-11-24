"""Installiert ein hochgeladenes Code-Paket (momentum-lab*.zip) ins Repository.

Wird vom Workflow aufgerufen: python3 <entpackt>/tools/install_package.py <entpackter-ordner> <zip> [<zip> ...]
- ersetzt den Code, behält .git, .github (Workflow), archive/ (Historie) und eigene Dateien in config/
- entfernt die ZIP-Dateien und committet/pusht die Änderung
"""
import os
import shutil
import subprocess
import sys

KEEP = {".git", ".github", "archive", "config"}


def sync(src: str, dst: str = ".") -> None:
    for n in os.listdir(dst):
        if n in KEEP or (n.startswith("momentum-lab") and n.endswith(".zip")):
            continue
        p = os.path.join(dst, n)
        shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)
    for n in os.listdir(src):
        s = os.path.join(src, n)
        if n in (".git", ".github", "archive"):
            continue
        if n == "config":
            os.makedirs(os.path.join(dst, "config"), exist_ok=True)
            for f in os.listdir(s):
                target = os.path.join(dst, "config", f)
                if not os.path.exists(target):
                    shutil.copy2(os.path.join(s, f), target)
        elif os.path.isdir(s):
            shutil.copytree(s, os.path.join(dst, n))
        else:
            shutil.copy2(s, os.path.join(dst, n))


def git(*args: str) -> None:
    subprocess.run(["git", *args], check=True)


def main() -> None:
    src, zips = sys.argv[1], sys.argv[2:]
    sync(src)
    for z in zips:
        subprocess.run(["git", "rm", "-q", "--cached", z], check=False)
        if os.path.exists(z):
            os.remove(z)
    git("config", "user.name", "momentum-lab-bot")
    git("config", "user.email", "momentum-lab-bot@users.noreply.github.com")
    git("add", "-A")
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
        git("commit", "-q", "-m", f"Code-Paket {', '.join(zips)} installiert")
        git("push", "-q")
    print(f"Installiert aus {', '.join(zips)}")


if __name__ == "__main__":
    main()
