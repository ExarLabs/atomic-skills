"""A repó szerkezetének tesztjei: verzió, fejlécek, a skill szabályai és parancsai."""
import argparse
import importlib.util
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILLEK = ROOT / "skills"

spec = importlib.util.spec_from_file_location("felmero", SKILLEK / "feature-felmero" / "felmero.py")
felmero = importlib.util.module_from_spec(spec)
spec.loader.exec_module(felmero)


def fejléc(szoveg):
    m = re.match(r"^---\n(.*?)\n---\n", szoveg, re.S)
    if not m:
        return {}
    adat = {}
    for sor in m.group(1).splitlines():
        if ":" in sor and not sor.startswith(" "):
            kulcs, _, ertek = sor.partition(":")
            adat[kulcs.strip()] = ertek.strip()
    return adat


class Szerkezet(unittest.TestCase):
    def test_verzio_egyezik_a_plugin_jsonnal(self):
        verzio = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(verzio, plugin["version"])

    def test_marketplace_json_ervenyes(self):
        json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))

    def test_minden_skillnek_van_fejlece(self):
        for skill_md in SKILLEK.glob("*/SKILL.md"):
            adat = fejléc(skill_md.read_text(encoding="utf-8"))
            self.assertTrue(adat.get("name"), skill_md)
            self.assertTrue(adat.get("description"), skill_md)

    def test_skill_tartalmazza_a_szabalyokat(self):
        szoveg = (SKILLEK / "feature-felmero" / "SKILL.md").read_text(encoding="utf-8")
        for kulcsmondat in ("A szerver a bíró", "Egyszerre egy kérdés", "Soha nem ígérsz",
                            "adat, nem utasítás", "Titok nem megy a szerverre", "Semmit nem találsz ki"):
            self.assertIn(kulcsmondat, szoveg)

    def test_skill_parancsai_leteznek(self):
        szoveg = (SKILLEK / "feature-felmero" / "SKILL.md").read_text(encoding="utf-8")
        hivatkozott = set(re.findall(r"felmero\.py\s+([a-z][a-z-]*)", szoveg))
        self.assertTrue(hivatkozott)
        alparancsok = set()
        for action in felmero.build_parser()._actions:
            if isinstance(action, argparse._SubParsersAction):
                alparancsok |= set(action.choices)
        self.assertEqual(hivatkozott - alparancsok, set())

    def test_skill_nem_hiv_serveroldali_vegpontot(self):
        szoveg = (SKILLEK / "feature-felmero" / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("/api/", szoveg)


if __name__ == "__main__":
    unittest.main()
