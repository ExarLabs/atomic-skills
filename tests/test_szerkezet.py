"""A repó szerkezetének tesztjei: verzió, fejlécek, a skill szabályai és parancsai."""
import argparse
import ast
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


KOZOS_FEJ = "## Közös szabályok (az ERP Plan minden skilljében ugyanez)"
KULCSMONDATOK = ("A szerver a bíró", "Egyszerre egy kérdés", "Soha nem ígérsz", "Adat, nem utasítás",
                 "Titok nem megy a szerverre", "Semmit nem találsz ki", "Következő lépés:")
FEJLEC_RE = re.compile(r'^---\nname: ([^\n]+)\ndescription: "([^"\\\n]*)"\n---\n')
EP_RE = re.compile(r"(?<![\w-])EP ([a-z][a-z-]*)")


def skill_fajlok():
    return sorted(SKILLEK.glob("*/SKILL.md"))


def teendo_ertekek():
    """A kapcsolódás teendő-kódjai: a CLI teendo_valaszt függvényének return-értékei."""
    for node in ast.walk(ast.parse(CLI.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef) and node.name == "teendo_valaszt":
            return {c.value for r in ast.walk(node) if isinstance(r, ast.Return) and r.value is not None
                    for c in ast.walk(r.value)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)
                    and re.fullmatch(r"[A-Z_]+", c.value)}
    raise AssertionError("teendo_valaszt nem található")


def kozos_blokk(szoveg):
    """A közös szabályok blokkja, ha a skillben van; a következő '## ' címsorig."""
    if KOZOS_FEJ not in szoveg:
        return None
    resz = szoveg[szoveg.index(KOZOS_FEJ):]
    vege = resz[len(KOZOS_FEJ):].find("\n## ")
    return resz if vege < 0 else resz[: len(KOZOS_FEJ) + vege]


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
                            "Adat, nem utasítás", "Titok nem megy a szerverre", "Semmit nem találsz ki"):
            self.assertIn(kulcsmondat, szoveg)

    def test_skill_parancsai_leteznek(self):
        szoveg = FELMERES_SKILL.read_text(encoding="utf-8")
        hivatkozott = set(EP_RE.findall(szoveg))
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

    # P1-09: a skillek általános szabályai (minden SKILL.md-re)

    def test_fejlec_szigoru(self):
        for skill_md in skill_fajlok():
            m = FEJLEC_RE.match(skill_md.read_text(encoding="utf-8"))
            self.assertIsNotNone(m, "fejléc: pontosan name és description, a leírás kettős idézőjelben: %s" % skill_md)
            self.assertEqual(m.group(1), skill_md.parent.name, skill_md)
            self.assertLessEqual(len(m.group(2)), 1000, skill_md)

    def test_leiras_magyar_es_angol(self):
        for skill_md in skill_fajlok():
            m = FEJLEC_RE.match(skill_md.read_text(encoding="utf-8"))
            self.assertIsNotNone(m, skill_md)
            self.assertIn("English:", m.group(2), skill_md)

    def test_skillek_nem_hivnak_vegpontot(self):
        for skill_md in skill_fajlok():
            self.assertNotIn("/api/", skill_md.read_text(encoding="utf-8"), skill_md)

    def test_ep_parancsok_leteznek(self):
        alparancsok = set()
        for action in erp_plan.build_parser()._actions:
            if isinstance(action, argparse._SubParsersAction):
                alparancsok |= set(action.choices)
        for skill_md in skill_fajlok():
            hivott = set(EP_RE.findall(skill_md.read_text(encoding="utf-8")))
            self.assertEqual(hivott - alparancsok, set(), skill_md)

    def test_kozos_blokk_szo_szerint_azonos(self):
        blokkok = {}
        for skill_md in skill_fajlok():
            blokk = kozos_blokk(skill_md.read_text(encoding="utf-8"))
            if blokk is not None:
                blokkok[skill_md.parent.name] = blokk.rstrip()
        self.assertIn("erp-plan", blokkok)
        elso = blokkok["erp-plan"]
        for nev, blokk in blokkok.items():
            self.assertEqual(blokk, elso, nev)

    def test_kulcsmondatok(self):
        for skill_md in skill_fajlok():
            szoveg = skill_md.read_text(encoding="utf-8")
            if kozos_blokk(szoveg) is None:
                continue
            for kulcsmondat in KULCSMONDATOK:
                self.assertIn(kulcsmondat, szoveg, "%s: %s" % (skill_md.parent.name, kulcsmondat))

    # P1-10: a felmérő és az ellenőrzés skill

    def test_felmeres_megtartja_a_regi_szakaszokat(self):
        szoveg = FELMERES_SKILL.read_text(encoding="utf-8")
        for cim in ("## A kérdezés menete", "## Elem rögzítése", "## Fájlok", "## Hang",
                    "## Hivatkozás másik feature-re"):
            self.assertIn(cim, szoveg)

    def test_ellenorzes_nem_javasol_valaszt(self):
        szoveg = (SKILLEK / "erp-plan-ellenorzes" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Nem javasolsz választ", szoveg)

    def test_parancs_fajl_a_felmeresre_mutat(self):
        szoveg = (ROOT / "commands" / "felmero.md").read_text(encoding="utf-8")
        self.assertIn("Töltsd be az `erp-plan-felmeres` skillt, és kövesd az Indulás szakaszát.", szoveg)

    # P1-11: a Frappe-, a kapcsolódási és a PAROS-skill

    def test_het_skill_van(self):
        nevek = sorted(p.parent.name for p in skill_fajlok())
        self.assertEqual(nevek, sorted(["erp-plan", "erp-plan-munkak", "erp-plan-felmeres",
                                        "erp-plan-ellenorzes", "erp-plan-frappe", "erp-plan-kapcsolat",
                                        "erp-plan-paros"]))

    def test_paros_ket_parancsa_szo_szerint(self):
        szoveg = (SKILLEK / "erp-plan-paros" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("git clone https://github.com/ExarLabs/paros-advisor.git ~/.paros-advisor", szoveg)
        self.assertIn("python3 ~/.paros-advisor/install/install.py", szoveg)

    def test_kapcsolat_minden_teendot_kezel(self):
        szoveg = (SKILLEK / "erp-plan-kapcsolat" / "SKILL.md").read_text(encoding="utf-8")
        ertekek = teendo_ertekek()
        self.assertEqual(len(ertekek), 7)
        for teendo in ertekek:
            self.assertIn("`%s`" % teendo, szoveg)

    def test_folyamat_van_es_rovid(self):
        folyamat = SKILLEK / "erp-plan" / "references" / "folyamat.md"
        self.assertTrue(folyamat.is_file())
        self.assertLessEqual(len(folyamat.read_text(encoding="utf-8").splitlines()), 60)


if __name__ == "__main__":
    unittest.main()
