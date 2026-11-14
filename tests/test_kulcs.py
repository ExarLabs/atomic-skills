"""A kulcs-igenyles (4.6) tesztjei az atomi adapteren, hamis szerver ellen (5.2 három vendég-végpontja).

A titkos értékek (eszközkód, kulcs, titok) soha nem jelenhetnek meg a kimenetben vagy a hibaüzenetben.
"""
import json
import os
import stat
import unittest

from tests.hamis_szerver import CEG, FELHASZNALO, JELSZO
from tests.test_parancsok import CliTeszt

KULCS = "hamis-kulcs-7731"
TITOK = "hamis-titok-9d2c8e41f0"
EMAIL = "proba" + "@" + "pelda" + ".hu"


class KulcsIgenyles(CliTeszt):
    def setUp(self):
        super().setUp()
        self.szerver.szolgaltatas_el = True
        self.szerver.kulcsok = {}
        self.szerver.eszkoz_mod = "var"
        self.szerver.jovahagyas = (KULCS, TITOK, FELHASZNALO, [CEG])
        self.mappa = os.path.join(self.tmp, "beallitas-atomi")
        self.konfig = os.path.join(self.mappa, "config.json")
        self.eszkoz = os.path.join(self.mappa, "eszkoz.json")
        self.env["ERP_PLAN_CONFIG"] = self.konfig

    def indit(self, *extra):
        return self.ep("kulcs-igenyles", "--indit", "--url", self.szerver.url, "--email", EMAIL, *extra)

    def eszkoz_adat(self):
        with open(self.eszkoz, encoding="utf-8") as f:
            return json.load(f)

    def proto_konfig(self):
        os.makedirs(self.mappa, exist_ok=True)
        with open(self.konfig, "w", encoding="utf-8") as f:
            json.dump({"url": self.szerver.url, "adapter": "proto", "user": FELHASZNALO, "jelszo": JELSZO}, f)
        os.chmod(self.konfig, 0o600)

    def test_indit_nem_irja_ki_az_eszkozkodot(self):
        r = self.indit()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        kod = self.szerver.kerelem["eszkoz_kod"]
        self.assertNotIn(kod, r.stdout)
        self.assertNotIn(kod, r.stderr)
        kimenet = json.loads(r.stdout)
        self.assertEqual(kimenet["felhasznaloi_kod"], "BCDF-GHJK")
        self.assertIn("ellenorzo_url", kimenet)
        self.assertEqual(kimenet["lejar_mp"], 600)

    def test_eszkoz_json_600(self):
        self.assertEqual(self.indit().returncode, 0)
        self.assertEqual(stat.S_IMODE(os.stat(self.eszkoz).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.mappa).st_mode), 0o700)
        self.assertEqual(self.eszkoz_adat()["eszkoz_kod"], self.szerver.kerelem["eszkoz_kod"])

    def test_befejez_var(self):
        self.indit()
        r = self.ep("kulcs-igenyles", "--befejez")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout), {"allapot": "var"})
        self.assertTrue(os.path.exists(self.eszkoz))

    def test_befejez_jovahagyva_konfigot_ir_es_nem_irja_ki_a_titkot(self):
        self.indit()
        self.szerver.eszkoz_mod = "jovahagyva"
        r = self.ep("kulcs-igenyles", "--befejez")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        kimenet = json.loads(r.stdout)
        self.assertEqual(kimenet["allapot"], "jovahagyva")
        self.assertEqual(kimenet["kulcs_vege"], KULCS[-4:])
        self.assertNotIn(TITOK, r.stdout + r.stderr)
        self.assertNotIn(KULCS, r.stdout + r.stderr)
        with open(self.konfig, encoding="utf-8") as f:
            konfig = json.load(f)
        self.assertEqual(konfig["adapter"], "atomi")
        self.assertEqual((konfig["api_key"], konfig["api_secret"]), (KULCS, TITOK))
        self.assertEqual(stat.S_IMODE(os.stat(self.konfig).st_mode), 0o600)
        self.assertFalse(os.path.exists(self.eszkoz))

    def test_befejez_elutasitva_4(self):
        self.indit()
        self.szerver.eszkoz_mod = "elutasitva"
        r = self.ep("kulcs-igenyles", "--befejez")
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertEqual(self.hiba_kod(r), "FELMERO_ESZKOZ_ELUTASITVA")
        self.assertFalse(os.path.exists(self.eszkoz))

    def test_befejez_lejart_5(self):
        self.indit()
        self.szerver.eszkoz_mod = "lejart"
        r = self.ep("kulcs-igenyles", "--befejez")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertEqual(self.hiba_kod(r), "FELMERO_ESZKOZ_LEJART")
        self.assertFalse(os.path.exists(self.eszkoz))

    def test_befejez_indit_nelkul_2(self):
        r = self.ep("kulcs-igenyles", "--befejez")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.hiba_kod(r), "FELMERO_ESZKOZ_NINCS")

    def test_proto_adapteren_nem_elerheto(self):
        self.proto_konfig()
        r = self.indit()
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.hiba_kod(r), "FELMERO_NEM_ELERHETO")
        self.assertEqual(self.szerver.irasok(), [])

    def test_szolgaltatas_nelkul_nem_elerheto(self):
        self.szerver.szolgaltatas_el = False
        r = self.indit()
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.hiba_kod(r), "FELMERO_NEM_ELERHETO")
        self.assertFalse(os.path.exists(self.eszkoz))

    def test_eszkoz_nev_hosszu_hibas(self):
        r = self.indit("--eszkoz-nev", "x" * 61)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.hiba_kod(r), "FELMERO_HOSSZ")
        self.assertEqual(self.szerver.irasok(), [])

    def test_kapcsolo_nelkul_jovahagyas_utan_konfig(self):
        self.szerver.eszkoz_mod = "jovahagyva"
        r = self.ep("kulcs-igenyles", "--url", self.szerver.url, "--email", EMAIL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("BCDF-GHJK", r.stderr)
        self.assertNotIn(self.szerver.kerelem["eszkoz_kod"], r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["kulcs_vege"], KULCS[-4:])
        self.assertFalse(os.path.exists(self.eszkoz))

    def test_kivagyok_token_fejleccel(self):
        self.indit()
        self.szerver.eszkoz_mod = "jovahagyva"
        self.assertEqual(self.ep("kulcs-igenyles", "--befejez").returncode, 0)
        r = self.ep("kivagyok")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.szerver.utolso_auth, "token %s:%s" % (KULCS, TITOK))
        self.assertIn(KULCS[-4:], r.stdout)
        self.assertNotIn(KULCS, r.stdout + r.stderr)
        self.assertNotIn(TITOK, r.stdout + r.stderr)

    def test_mas_parancs_atomin_nem_elerheto(self):
        self.indit()
        self.szerver.eszkoz_mod = "jovahagyva"
        self.ep("kulcs-igenyles", "--befejez")
        r = self.ep("feature", "FT-00001")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.hiba_kod(r), "FELMERO_NEM_ELERHETO")


if __name__ == "__main__":
    unittest.main()
