#!/usr/bin/env python3
"""ERP Plan kézi telepítő: a skills/erp-plan* mappákat a Claude Code skill-mappájába másolja.

Használat:
  python3 -I scripts/telepit.py [--cel MAPPA] [--torol-regi]

Alap cél: ~/.claude/skills. Ha ott már van azonos nevű mappa, felülíródik. A régi feature-felmero
mappát csak a --torol-regi kapcsolóval törli; különben figyelmeztet. A kimenet JSON.
Standard könyvtár, Python 3.9+.
"""
import argparse
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILLEK = ROOT / "skills"
REGI_NEV = "feature-felmero"


def skill_nevek():
    return sorted(p.name for p in SKILLEK.iterdir() if p.is_dir() and p.name.startswith("erp-plan"))


def telepit(cel, torol_regi):
    cel.mkdir(parents=True, exist_ok=True)
    masolva, felulirva, figyelmeztetes = [], [], []
    for nev in skill_nevek():
        forras = SKILLEK / nev
        hova = cel / nev
        if hova.exists():
            shutil.rmtree(hova)
            felulirva.append(nev)
        shutil.copytree(forras, hova, ignore=shutil.ignore_patterns("__pycache__"))
        masolva.append({"nev": nev, "hova": str(hova)})

    regi = cel / REGI_NEV
    if regi.exists():
        if torol_regi:
            shutil.rmtree(regi)
            regi_allapot = "torolve"
        else:
            regi_allapot = "megmaradt"
            figyelmeztetes.append("A régi %s mappa megmaradt. Törléséhez add a --torol-regi kapcsolót." % REGI_NEV)
    else:
        regi_allapot = "nincs"

    return {"cel": str(cel), "masolva": masolva, "felulirva": felulirva,
            "regi": {"nev": REGI_NEV, "allapot": regi_allapot}, "figyelmeztetes": figyelmeztetes}


def main(argv=None):
    ap = argparse.ArgumentParser(description="ERP Plan kézi telepítése a Claude Code skill-mappájába.")
    ap.add_argument("--cel", help="a célmappa (alap: ~/.claude/skills)")
    ap.add_argument("--torol-regi", action="store_true", help="a régi feature-felmero mappa törlése")
    args = ap.parse_args(argv)
    cel = pathlib.Path(args.cel).expanduser() if args.cel else pathlib.Path.home() / ".claude" / "skills"
    adat = telepit(cel.resolve(), args.torol_regi)
    print(json.dumps(adat, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
