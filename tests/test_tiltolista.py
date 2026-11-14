"""A kiadási tiltólista-ellenőrző (scripts/tiltolista.py) tesztjei.

A tesztek nem függnek a helyi (karbantartói) tiltólistától: ideiglenes mintafájlokat
hoznak létre. A tiltott szavakat nem literálisan írjuk le, hanem futásidőben fűzzük össze.
Egyetlen teszt ellenőrzi a valódi repót az éles általános listával.
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SZKRIPT = ROOT / "scripts" / "tiltolista.py"

KAPU = "kapu" + "_itelet"
AZ_ERTEK = "ertek" + "becsles"
AZ_ERTEK_EKEZET = "".join([chr(0xe9), "rt", chr(0xe9), "kbecsl", chr(0xe9), "s"])
KULSO_CIM = "valaki" + "@exar" + ".ro"
ENGEDETT_CIM = "contact" + "@exar" + ".ro"
JELSZO_SOR = "pass" + "word=abc"
IP_CIM = "10." + "20." + "30." + "40"


class Tiltolista(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.listak = tempfile.mkdtemp()
        self.general = pathlib.Path(self.listak, "altalanos.txt")
        self.general.write_text(
            "!" + ENGEDETT_CIM + "\n"
            "!127.0.0.1\n"
            "[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)*\\.[a-z]{2,}\n"
            "password\\s*[=:]\\s*[^\\s<]\n"
            "\\b(\\d{1,3}\\.){3}\\d{1,3}\\b\n",
            encoding="utf-8")
        self.helyi = pathlib.Path(self.listak, "helyi.txt")
        self.helyi.write_text(
            KAPU + "\n"
            + AZ_ERTEK + "|" + AZ_ERTEK_EKEZET + "\n",
            encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.listak, ignore_errors=True)

    def repo(self, fajlok):
        for nev, tartalom in fajlok.items():
            utvonal = pathlib.Path(self.tmp) / nev
            utvonal.parent.mkdir(parents=True, exist_ok=True)
            utvonal.write_text(tartalom, encoding="utf-8")
        subprocess.run(["git", "-C", self.tmp, "init", "-q"], check=True)
        subprocess.run(["git", "-C", self.tmp, "add", "-A"], check=True)

    def futtat(self, helyi=""):
        return subprocess.run([sys.executable, str(SZKRIPT), "--repo", self.tmp,
                               "--lista", str(self.general), "--helyi", helyi],
                              capture_output=True, text=True, encoding="utf-8")

    def test_tiszta_mappan_nulla(self):
        self.repo({"README.md": "Semleges szöveg.\n"})
        eredmeny = self.futtat()
        self.assertEqual(eredmeny.returncode, 0, eredmeny.stdout + eredmeny.stderr)

    def test_helyi_lista_megfogja_az_elultetett_szot(self):
        self.repo({"docs/jegyzet.md": "Ez a sor tartalmaz egy " + KAPU + " szót.\n"})
        eredmeny = self.futtat(helyi=str(self.helyi))
        self.assertEqual(eredmeny.returncode, 1)
        self.assertIn("docs/jegyzet.md", eredmeny.stdout)
        self.assertIn(":1:", eredmeny.stdout)

    def test_engedett_kivetel(self):
        self.repo({"docs/a.md": "Írj ide: " + ENGEDETT_CIM + "\n"})
        self.assertEqual(self.futtat().returncode, 0)

    def test_nem_engedett_cim_talalat(self):
        self.repo({"docs/b.md": "Írj ide: " + KULSO_CIM + "\n"})
        self.assertEqual(self.futtat().returncode, 1)

    def test_ekezet_nelkuli_alak_is_talalat(self):
        self.repo({"docs/c.md": "Szöveg: " + AZ_ERTEK + "\n"})
        self.assertEqual(self.futtat(helyi=str(self.helyi)).returncode, 1)

    def test_ekezetes_alak_is_talalat(self):
        self.repo({"docs/d.md": "Szöveg: " + AZ_ERTEK_EKEZET + "\n"})
        self.assertEqual(self.futtat(helyi=str(self.helyi)).returncode, 1)

    def test_jelszo_ip_talalat(self):
        self.repo({"docs/e.md": JELSZO_SOR + "\n", "docs/f.md": "Cím: " + IP_CIM + "\n"})
        eredmeny = self.futtat()
        self.assertEqual(eredmeny.returncode, 1)
        self.assertIn("docs/e.md", eredmeny.stdout)
        self.assertIn("docs/f.md", eredmeny.stdout)

    def test_localhost_engedett(self):
        self.repo({"docs/g.md": "Helyi: http://127.0.0.1:8000\n"})
        self.assertEqual(self.futtat().returncode, 0)

    def test_hianyzo_helyi_lista_nem_bukik(self):
        self.repo({"README.md": "Semleges szöveg.\n"})
        eredmeny = self.futtat(helyi=str(pathlib.Path(self.listak, "nincs.txt")))
        self.assertEqual(eredmeny.returncode, 0, eredmeny.stdout + eredmeny.stderr)
        self.assertIn("figyelem", eredmeny.stderr)

    def test_valos_repo_zold(self):
        eredmeny = subprocess.run([sys.executable, str(SZKRIPT), "--repo", str(ROOT)],
                                  capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(eredmeny.returncode, 0, eredmeny.stdout + eredmeny.stderr)


if __name__ == "__main__":
    unittest.main()
