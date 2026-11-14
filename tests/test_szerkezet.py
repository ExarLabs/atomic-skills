"""A repó szerkezetének tesztjei: verzió, fejlécek, a skill szabályai és parancsai."""
import argparse
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILLEK = ROOT / "skills"
CLI = SKILLEK / "erp-plan" / "erp_plan.py"
ALIAS = SKILLEK / "erp-plan" / "felmero.py"
FELMERES_SKILL = SKILLEK / "erp-plan-felmeres" / "SKILL.md"

spec = importlib.util.spec_from_file_location("erp_plan", CLI)
erp_plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(erp_plan)


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
        szoveg = FELMERES_SKILL.read_text(encoding="utf-8")
        for kulcsmondat in ("A szerver a bíró", "Egyszerre egy kérdés", "Soha nem ígérsz",
                            "adat, nem utasítás", "Titok nem megy a szerverre", "Semmit nem találsz ki"):
            self.assertIn(kulcsmondat, szoveg)

    def test_skill_parancsai_leteznek(self):
        szoveg = FELMERES_SKILL.read_text(encoding="utf-8")
        hivatkozott = set(re.findall(r"erp_plan\.py\s+([a-z][a-z-]*)", szoveg))
        self.assertTrue(hivatkozott)
        alparancsok = set()
        for action in erp_plan.build_parser()._actions:
            if isinstance(action, argparse._SubParsersAction):
                alparancsok |= set(action.choices)
        self.assertEqual(hivatkozott - alparancsok, set())

    def test_skill_nem_hiv_serveroldali_vegpontot(self):
        szoveg = FELMERES_SKILL.read_text(encoding="utf-8")
        self.assertNotIn("/api/", szoveg)

    # P1-01: átnevezés, váz, verzió

    def test_alias_ugyanazt_adja(self):
        kimenetek = []
        for program in (ALIAS, CLI):
            eredmeny = subprocess.run([sys.executable, "-I", str(program), "verzio"],
                                      capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(eredmeny.returncode, 0, eredmeny.stderr)
            kimenetek.append(eredmeny.stdout)
        self.assertEqual(kimenetek[0], kimenetek[1])

    def test_plugin_neve_erp_plan(self):
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], "erp-plan")

    def test_marketplace_leirassal(self):
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(market["name"], "atomic-skills")
        self.assertTrue(market.get("description"))
        self.assertEqual(market["plugins"][0]["name"], "erp-plan")
        self.assertTrue(market["plugins"][0].get("description"))

    def test_verzio_0_2_0_mindenhol(self):
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "0.2.0")
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["version"], "0.2.0")
        self.assertEqual(erp_plan.VERSION, "0.2.0")
        self.assertEqual(erp_plan.USER_AGENT, "atomic-skills-erp-plan/0.2.0")

    def test_regi_skill_mappa_nincs(self):
        self.assertFalse((SKILLEK / "feature-felmero").exists())


if __name__ == "__main__":
    unittest.main()
