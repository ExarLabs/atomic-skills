"""A parancsréteg tesztjei: az erp_plan.py valódi programként fut, és hamis (helyi) szerver ellen hívja a szervert."""
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from tests.hamis_szerver import CEG, FELHASZNALO, JELSZO, MAS_CEG, HamisSzerver

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "skills" / "erp-plan" / "erp_plan.py"
KILEP_MEGTAGADVA, KILEP_HALOZAT = 4, 5


class CliTeszt(unittest.TestCase):
    def setUp(self):
        self.szerver = HamisSzerver()
        self.tmp = tempfile.mkdtemp()
        self.konfig = os.path.join(self.tmp, "beallitas", "config.json")
        os.makedirs(os.path.dirname(self.konfig))
        with open(self.konfig, "w", encoding="utf-8") as f:
            json.dump({"url": self.szerver.url, "adapter": "proto", "user": FELHASZNALO, "jelszo": JELSZO,
                       "ceg": ""}, f)
        os.chmod(self.konfig, 0o600)
        self.env = dict(os.environ)
        self.env.pop("FELMERO_CONFIG", None)
        self.env["ERP_PLAN_CONFIG"] = self.konfig

    def tearDown(self):
        self.szerver.leallitas()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ep(self, *args):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=self.env, capture_output=True,
                              text=True, encoding="utf-8")

    def fajl(self, nev, tartalom):
        utvonal = os.path.join(self.tmp, nev)
        with open(utvonal, "w", encoding="utf-8") as f:
            f.write(tartalom)
        return utvonal

    def kimeno_sorai(self):
        utvonal = os.path.join(os.path.dirname(self.konfig), "kimeno", "FT-00001.jsonl")
        if not os.path.exists(utvonal):
            return []
        with open(utvonal, encoding="utf-8") as f:
            return [sor for sor in f if sor.strip()]

    def hiba_kod(self, eredmeny):
        return json.loads(eredmeny.stdout)["hiba"]["kod"]


class Parancsok(CliTeszt):
    def test_elem_hamis_idezettel_nem_ment(self):
        ertek = self.fajl("ertek.txt", "Havonta fut a folyamat.")
        eredmeny = self.ep("elem", "FT-00001", "--kod", "B1", "--ertek-fajl", ertek,
                           "--idezet", "ez a mondat nincs meg sehol")
        self.assertEqual(eredmeny.returncode, KILEP_MEGTAGADVA, eredmeny.stdout + eredmeny.stderr)
        self.assertEqual(self.hiba_kod(eredmeny), "FELMERO_IDEZET_NINCS")
        self.assertEqual(self.szerver.irasok(), [])

    def test_par_ket_uzenetet_kuld(self):
        kerdes = self.fajl("kerdes.txt", "Mit csinálsz most?")
        valasz = self.fajl("valasz.txt", "Havonta egyszer kézzel számolom újra a készletet.")
        eredmeny = self.ep("par", "FT-00001", "--kerdes-fajl", kerdes, "--valasz-fajl", valasz)
        self.assertEqual(eredmeny.returncode, 0, eredmeny.stdout + eredmeny.stderr)
        uzenetek = [j for m, u, t in self.szerver.irasok() if u.endswith("Felmero Uzenet")
                    for j in [json.loads(t)]]
        self.assertEqual(sorted(u["szerep"] for u in uzenetek), ["asszisztens", "kliens"])

    def test_par_halozati_hibanal_a_sorban_marad(self):
        kerdes = self.fajl("kerdes.txt", "Mit csinálsz most?")
        valasz = self.fajl("valasz.txt", "Havonta egyszer kézzel számolom újra a készletet.")
        self.szerver.hiba("POST", "/api/resource/Felmero Uzenet", "drop")
        eredmeny = self.ep("par", "FT-00001", "--kerdes-fajl", kerdes, "--valasz-fajl", valasz)
        self.assertEqual(eredmeny.returncode, KILEP_HALOZAT, eredmeny.stdout + eredmeny.stderr)
        self.assertEqual(len(self.kimeno_sorai()), 2)
        self.szerver.hiba_torol()
        ujra = self.ep("kimeno", "FT-00001")
        self.assertEqual(ujra.returncode, 0, ujra.stdout + ujra.stderr)
        self.assertEqual(self.kimeno_sorai(), [])

    def test_kimeno_ujrakuld_ugyanazzal_az_azonositoval(self):
        valasz = self.fajl("valasz.txt", "Ezt a kimenő sort most teszteljük.")
        self.szerver.hiba("POST", "/api/resource/Felmero Uzenet", "store_drop")
        elso = self.ep("uzenet", "FT-00001", "--szerep", "kliens", "--fajl", valasz)
        self.assertEqual(elso.returncode, KILEP_HALOZAT, elso.stdout + elso.stderr)
        self.szerver.hiba_torol()
        ujra = self.ep("kimeno", "FT-00001")
        self.assertEqual(ujra.returncode, 0, ujra.stdout + ujra.stderr)
        self.assertTrue(json.loads(ujra.stdout)["kuldott"][0]["mar_volt"])
        with open(valasz, encoding="utf-8") as f:
            szoveg = f.read()
        azonos = [r for r in self.szerver.rekordok("Felmero Uzenet") if r.get("szoveg") == szoveg]
        self.assertEqual(len(azonos), 1)

    def test_bekuld_hianyosan_megtagadva(self):
        eredmeny = self.ep("bekuld", "FT-00001", "--osszefoglalo-verzio", "1")
        self.assertEqual(eredmeny.returncode, KILEP_MEGTAGADVA, eredmeny.stdout + eredmeny.stderr)
        self.assertEqual(self.hiba_kod(eredmeny), "FELMERO_HIANYOS")
        self.assertEqual(self.szerver.irasok(), [])

    def test_403_nem_adja_tovabb_a_szerver_szoveget(self):
        eredmeny = self.ep("feature", "FT-00002")
        self.assertEqual(eredmeny.returncode, KILEP_MEGTAGADVA, eredmeny.stdout + eredmeny.stderr)
        self.assertEqual(self.hiba_kod(eredmeny), "FELMERO_TILTOTT")
        self.assertIn("Ehhez nincs hozzáférésed, vagy nem létezik.", eredmeny.stdout)
        self.assertNotIn(MAS_CEG, eredmeny.stdout + eredmeny.stderr)

    def test_letolt_600_as_fajlt_ir(self):
        ki = os.path.join(self.tmp, "letoltott.md")
        eredmeny = self.ep("letolt", "FA-00001", "--ki", ki)
        self.assertEqual(eredmeny.returncode, 0, eredmeny.stdout + eredmeny.stderr)
        self.assertEqual(stat.S_IMODE(os.stat(ki).st_mode), 0o600)
        with open(ki, "rb") as f:
            self.assertEqual(f.read(), b"# Minta\n\nHavonta fut a folyamat.\n")

    def test_md_fajl_md_txt_neven_megy_fel_es_eredeti_neven_jon_vissza(self):
        md = self.fajl("jegyzet.md", "# Jegyzet\n\nHavonta fut a folyamat.\n")
        feltolt = self.ep("feltolt", "--projekt", "FP-00001", "--feature", "FT-00001", md)
        self.assertEqual(feltolt.returncode, 0, feltolt.stdout + feltolt.stderr)
        self.assertEqual(json.loads(feltolt.stdout)[0]["fajl_nev"], "jegyzet.md")
        feltoltott = [r for r in self.szerver.rekordok("File") if r.get("file_name", "").startswith("jegyzet")]
        self.assertEqual([r["file_name"] for r in feltoltott], ["jegyzet.md.txt"])
        fa = [r for r in self.szerver.rekordok("Felmero Fajl") if r.get("fajl_nev") == "jegyzet.md"][0]
        ki = os.path.join(self.tmp, "vissza.md")
        letolt = self.ep("letolt", fa["name"], "--ki", ki)
        self.assertEqual(letolt.returncode, 0, letolt.stdout + letolt.stderr)
        self.assertEqual(json.loads(letolt.stdout)["fajl_nev"], "jegyzet.md")
        with open(ki, encoding="utf-8") as f:
            self.assertEqual(f.read(), "# Jegyzet\n\nHavonta fut a folyamat.\n")


if __name__ == "__main__":
    unittest.main()
