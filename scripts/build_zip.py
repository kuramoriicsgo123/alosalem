"""Build the distributable from a strict allowlist; never package live credentials or orders."""
from pathlib import Path
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "main.py", "requirements.txt", "requirements.lock", "config.example.json", ".env.example", ".gitignore",
    "products.json", "prices.json", "structure.json", "INSTALLER_WINDOWS.bat", "DEMARRER_WINDOWS.bat",
    "README.md", "README_FR.md", "RECHERCHE_PRIX_FR.md",
)


def build():
    selected = [ROOT / name for name in FILES if (ROOT / name).is_file()]
    selected += sorted((ROOT / "shop").glob("*.py"))
    selected += sorted((ROOT / "tests").glob("*.py"))
    selected += sorted((ROOT / "docs").glob("*.md"))
    selected += sorted((ROOT / "scripts").glob("*.py"))
    selected += sorted((ROOT / "scripts").glob("*.sh"))
    destination = ROOT / "dist" / "ASA-Shop-Discord-Windows.zip"
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in selected:
            archive.write(path, "ASA-Shop/" + path.relative_to(ROOT).as_posix())
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".zip.sha256").write_text(f"{digest}  {destination.name}\n", encoding="ascii")
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Archive integrity failed")
        forbidden = {".env", "config.json", "shop.sqlite3"}
        if any(Path(name).name in forbidden or "/data/" in name or "/.venv/" in name for name in archive.namelist()):
            raise RuntimeError("Private data must never enter the ZIP")
    print(f"Archive vérifiée : {destination} ({len(selected)} fichiers, {destination.stat().st_size} octets)")
    return destination


if __name__ == "__main__":
    build()
