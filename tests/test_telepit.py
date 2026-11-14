"""A kézi telepítő (scripts/telepit.py) tesztjei. Minden futás ideiglenes HOME-mal fut: a valódi ~/.claude érintetlen."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TELEPIT = ROOT / "scripts" / "telepit.py"
HET_SKILL = ["erp-plan", "erp-plan-munkak", "erp-plan-felmeres", "erp-plan-ellenorzes",
             "erp-plan-frappe", "erp-plan-kapcsolat", "erp-plan-paros"]


def futtat(args, home=None):
    env = dict(os.environ)
    if home is not None:
        env["HOME"] = str(home)
    return subprocess.run([sys.executable, "-I", str(TELEPIT), *args], capture_output=True,
                          text=True, encoding="utf-8", env=env)


def valodi_skill_lista():
    mappa = pathlib.Path.home() / ".claude" / "skills"
    return sorted(p.name for p in mappa.iterdir()) if mappa.is_dir() else None


class Telepito(unittest.TestCase):
    def test_telepit_ideiglenes_home_ba(self):
        elotte = valodi_skill_lista()
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            eredmeny = futtat([], home)
            self.assertEqual(eredmeny.returncode, 0, eredmeny.stderr)
            cel = home / ".claude" / "skills"
            for nev in HET_SKILL:
                self.assertTrue((cel / nev / "SKILL.md").is_file(), nev)
            cli = cel / "erp-plan" / "erp_plan.py"
            verzio = subprocess.run([sys.executable, "-I", str(cli), "verzio"], capture_output=True,
                                    text=True, encoding="utf-8", env=dict(os.environ, HOME=tmp))
            self.assertEqual(verzio.returncode, 0, verzio.stderr)
            self.assertEqual(json.loads(verzio.stdout)["cli"], "0.2.0")
        self.assertEqual(valodi_skill_lista(), elotte)

    def test_telepit_cel_kapcsolo(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp) / "otthon"
            home.mkdir()
            cel = pathlib.Path(tmp) / "masik-helyre"
            eredmeny = futtat(["--cel", str(cel)], home)
            self.assertEqual(eredmeny.returncode, 0, eredmeny.stderr)
            for nev in HET_SKILL:
                self.assertTrue((cel / nev / "SKILL.md").is_file(), nev)
            self.assertFalse((home / ".claude").exists())
            adat = json.loads(eredmeny.stdout)
            self.assertEqual(sorted(x["nev"] for x in adat["masolva"]), sorted(HET_SKILL))

    def test_telepit_felulirja_a_meglevot(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            regi = home / ".claude" / "skills" / "erp-plan"
            regi.mkdir(parents=True)
            (regi / "regi-fajl.txt").write_text("régi", encoding="utf-8")
            eredmeny = futtat([], home)
            self.assertEqual(eredmeny.returncode, 0, eredmeny.stderr)
            self.assertFalse((regi / "regi-fajl.txt").exists())
            self.assertTrue((regi / "SKILL.md").is_file())
            self.assertIn("erp-plan", json.loads(eredmeny.stdout)["felulirva"])

    def test_regi_mappa_csak_kapcsoloval_torlodik(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            regi = home / ".claude" / "skills" / "feature-felmero"
            regi.mkdir(parents=True)
            (regi / "SKILL.md").write_text("régi skill", encoding="utf-8")

            eredmeny = futtat([], home)
            self.assertEqual(eredmeny.returncode, 0, eredmeny.stderr)
            self.assertTrue(regi.is_dir(), "kapcsoló nélkül nem törölhet")
            self.assertTrue(json.loads(eredmeny.stdout)["figyelmeztetes"])

            eredmeny = futtat(["--torol-regi"], home)
            self.assertEqual(eredmeny.returncode, 0, eredmeny.stderr)
            self.assertFalse(regi.exists())

    def test_dokumentumok_emlitik_a_ket_utat(self):
        telepites = (ROOT / "docs" / "telepites.md").read_text(encoding="utf-8")
        self.assertIn("/plugin install erp-plan@atomic-skills", telepites)
        self.assertIn("scripts/telepit.py", telepites)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("scripts/telepit.py", readme)
        self.assertIn("docs/kiprobalas.md", readme)

    def test_kiprobalas_van_es_a_konfig_valtozo(self):
        kiprobalas = (ROOT / "docs" / "kiprobalas.md").read_text(encoding="utf-8")
        self.assertIn("ERP_PLAN_CONFIG", kiprobalas)
        self.assertIn("claude --plugin-dir", kiprobalas)


if __name__ == "__main__":
    unittest.main()
