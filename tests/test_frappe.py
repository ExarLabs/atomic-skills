"""A Frappe-kérdésbank (frappe-kerdesek), a Frappe-lap (frappe-lap) és a CONTEXT-vázlat (context-vazlat) tesztjei.

Tiszta függvények (kérdésbank, context_md) és hamis szerver ellen futó parancsok.
"""
import importlib.util
import json
import os
import pathlib
import stat
import unittest

from tests.hamis_szerver import FELHASZNALO, JELSZO
from tests.test_parancsok import CliTeszt

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "skills" / "erp-plan" / "erp_plan.py"

spec = importlib.util.spec_from_file_location("erp_plan", CLI)
erp_plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(erp_plan)

IDEZET = "Havonta egyszer kézzel számolom újra a készletet."
ERTEK_ADAT = "Raktári tételek: cikkszám, mennyiség, hely."


def lap_adat(**temak):
    """Egy Frappe-lap: a megadott témák, a többi Hiányzik."""
    return {"verzio": 1, "kihagyva": False, "temak": temak}


def tema(allapot="Kész", ertek="Raktári tételek: cikkszám, mennyiség.", idezet=IDEZET, sorszam=1):
    return {"allapot": allapot, "ertek": ertek,
            "idezetek": [{"idezet": idezet, "uzenet": "UZ-00001", "uzenet_sorszam": sorszam}],
            "modositva": "2026-11-14T10:00:00"}


def kontext(**mezok):
    d = {"name": "FT-00001", "cim": "Készletszámlálás", "projekt": "FP-00001", "projekt_cim": "Raktár",
         "allapot": "Interjú",
         "elemek": [
             {"kod": "B1", "ertek": IDEZET, "datum": None, "szam": None, "kiegeszites": "", "allapot": "Kész",
              "hiany_ok": ""},
             {"kod": "D4", "ertek": "30 nap, a raktárvezető méri", "datum": None, "szam": 30, "kiegeszites": "",
              "allapot": "Kész", "hiany_ok": ""},
         ],
         "bizonyitekok": [{"elem": "B1", "idezet": IDEZET, "uzenet": "UZ-00001", "uzenet_sorszam": 1, "ervenyes": 1}],
         "hianylista": {"hianyzik": [{"kod": "B2", "cim": "A megoldás", "kotelezo": True, "allapot": "Hiányzik",
                                      "okok": ["nincs kitöltve"],
                                      "mit_kell_tudni": "Mit automatizálunk, mi lesz a kimenet, ki használja."}]},
         "talalatok": []}
    d.update(mezok)
    return d


SZAKASZOK = ["## Jira / Ticket", "## Business Requirements", "## Intent", "## Data model (DocTypes and fields)",
             "## Permissions", "## Workflow", "## Validation and calculations", "## Notifications",
             "## Reports and print", "## Integrations", "## Data migration", "## UX / Design Decisions",
             "## Technical Decisions", "## Light way", "## Acceptance tests", "## Exclusions", "## Open questions",
             "## Timeline (client's wish, not a commitment)", "## Rigor"]


class Bank(unittest.TestCase):
    def test_bank_12_tema_harom_kotelezo(self):
        self.assertEqual(len(erp_plan.FRAPPE_TEMAK), 12)
        kotelezo = [t["kod"] for t in erp_plan.FRAPPE_TEMAK if t["kotelezo"]]
        self.assertEqual(kotelezo, ["FR-ADAT", "FR-JOG", "FR-PROBA"])

    def test_bank_szovegei_nem_tartalmaznak_belso_szot(self):
        tiltott = ("doctype", "hook", "permlevel", "controller", "server script", "custom field")
        for t in erp_plan.FRAPPE_TEMAK:
            self.assertGreaterEqual(len(t["kerdesek"]), 2, t["kod"])
            for szoveg in [t["cim"], t["mit_kell_tudni"]] + t["kerdesek"]:
                for szo in tiltott:
                    self.assertNotIn(szo, szoveg.casefold(), t["kod"])


class ContextMd(unittest.TestCase):
    def test_context_md_minden_szakasz_megvan(self):
        szoveg = erp_plan.context_md(kontext(), lap_adat(), erp_plan.datetime.date(2026, 11, 14))
        helyek = [szoveg.index(s) for s in SZAKASZOK]
        self.assertEqual(helyek, sorted(helyek))
        self.assertTrue(szoveg.startswith("# Készletszámlálás: Context (DRAFT)"))
        self.assertIn("2026-11-14", szoveg)

    def test_context_md_determinisztikus(self):
        ma = erp_plan.datetime.date(2026, 11, 14)
        self.assertEqual(erp_plan.context_md(kontext(), lap_adat(), ma),
                         erp_plan.context_md(kontext(), lap_adat(), ma))

    def test_context_md_idezeteket_hoz(self):
        szoveg = erp_plan.context_md(kontext(), lap_adat(**{"FR-ADAT": tema()}), erp_plan.datetime.date(2026, 11, 14))
        self.assertIn("> „" + IDEZET + "” (üzenet #1)", szoveg)

    def test_context_md_nyitott_kerdesek(self):
        szoveg = erp_plan.context_md(kontext(), lap_adat(), erp_plan.datetime.date(2026, 11, 14))
        reszlet = szoveg[szoveg.index("## Open questions"):szoveg.index("## Timeline")]
        self.assertIn("Nyilvántartott adatok", reszlet)
        self.assertIn("A megoldás", reszlet)
        self.assertIn("Mit automatizálunk", reszlet)

    def test_context_md_nem_relevans_jelol(self):
        szoveg = erp_plan.context_md(kontext(), lap_adat(**{"FR-MEGLEVO": tema("Nem releváns")}),
                                     erp_plan.datetime.date(2026, 11, 14))
        self.assertIn("Not relevant (client):", szoveg)

    def test_context_md_nincs_ar_es_belso_mezo(self):
        k = kontext()
        k["elemek"][0]["rejtett_mezo"] = "NEM-KERUL-BELE-4411"
        szoveg = erp_plan.context_md(k, lap_adat(), erp_plan.datetime.date(2026, 11, 14))
        self.assertNotIn("NEM-KERUL-BELE-4411", szoveg)
        self.assertNotIn("rejtett_mezo", szoveg)


class FrappeParancsok(CliTeszt):
    def setUp(self):
        super().setUp()
        self.f = self.szerver.rekord("Felmero Feature", "FT-00001")
        self.f["frappe_lap"] = None  # a mező létezik a szerveren, üres

    def lap(self):
        return json.loads(self.f["frappe_lap"])

    def irasok_ft1(self):
        return [n for n in self.szerver.irasok() if n[1].endswith("/Felmero Feature/FT-00001") and n[0] == "PUT"]

    def irasok_mind(self):
        return self.szerver.irasok()

    def test_kerdesbank_feature_nelkul(self):
        r = self.ep("frappe-kerdesek")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(json.loads(r.stdout)["temak"]), 12)

    def test_kerdesek_feature_lappal(self):
        r = self.ep("frappe-kerdesek", "FT-00001")
        self.assertEqual(r.returncode, 0, r.stderr)
        k = json.loads(r.stdout)
        self.assertTrue(k["elerheto"])
        self.assertEqual((k["kesz_db"], k["ossz_db"]), (0, 12))

    def test_lap_iras_idezettel(self):
        ertek = self.fajl("ertek.txt", ERTEK_ADAT)
        r = self.ep("frappe-lap", "FT-00001", "--tema", "FR-ADAT", "--ertek-fajl", ertek, "--idezet", IDEZET)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["allapot"], "Kész")
        self.assertEqual(self.lap()["temak"]["FR-ADAT"]["allapot"], "Kész")
        self.assertEqual(self.lap()["temak"]["FR-ADAT"]["idezetek"][0]["uzenet_sorszam"], 1)

    def test_lap_hamis_idezettel_nem_ment(self):
        ertek = self.fajl("ertek.txt", ERTEK_ADAT)
        r = self.ep("frappe-lap", "FT-00001", "--tema", "FR-ADAT", "--ertek-fajl", ertek,
                    "--idezet", "Ez a mondat sehol sincs meg itt.")
        self.assertEqual(r.returncode, 4)
        self.assertEqual(self.hiba_kod(r), "FELMERO_IDEZET_NINCS")
        self.assertEqual(self.irasok_mind(), [])

    def test_nem_relevans_is_idezetet_ker(self):
        r = self.ep("frappe-lap", "FT-00001", "--tema", "FR-MEGLEVO", "--nem-relevans")
        self.assertEqual(r.returncode, 4)
        self.assertEqual(self.hiba_kod(r), "FELMERO_IDEZET_NINCS")
        self.assertEqual(self.irasok_mind(), [])
        r = self.ep("frappe-lap", "FT-00001", "--tema", "FR-MEGLEVO", "--nem-relevans", "--idezet", IDEZET)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.lap()["temak"]["FR-MEGLEVO"]["allapot"], "Nem releváns")

    def test_kihagy_es_folytat(self):
        r = self.ep("frappe-lap", "FT-00001", "--kihagy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.lap()["kihagyva"])
        r = self.ep("frappe-kerdesek", "FT-00001")
        self.assertTrue(json.loads(r.stdout)["kihagyva"])
        r = self.ep("frappe-lap", "FT-00001", "--folytat")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.lap()["kihagyva"])

    def test_hianyzo_mezo_nem_elerheto(self):
        self.f.pop("frappe_lap", None)
        r = self.ep("frappe-kerdesek", "FT-00001")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(json.loads(r.stdout)["elerheto"])
        ertek = self.fajl("ertek.txt", ERTEK_ADAT)
        r = self.ep("frappe-lap", "FT-00001", "--tema", "FR-ADAT", "--ertek-fajl", ertek, "--idezet", IDEZET)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.hiba_kod(r), "FELMERO_NEM_ELERHETO")
        self.assertEqual(self.irasok_mind(), [])

    def test_ismeretlen_tema(self):
        ertek = self.fajl("ertek.txt", ERTEK_ADAT)
        r = self.ep("frappe-lap", "FT-00001", "--tema", "FR-NINCS", "--ertek-fajl", ertek, "--idezet", IDEZET)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.hiba_kod(r), "FELMERO_ISMERETLEN_ELEM")

    def test_context_feltolt(self):
        ki = os.path.join(self.tmp, "vazlat", "CONTEXT.md")
        r = self.ep("context-vazlat", "FT-00001", "--ki", ki, "--feltolt")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        kimenet = json.loads(r.stdout)
        self.assertTrue(kimenet["fajl"].startswith("FA-"))
        self.assertTrue(os.path.exists(ki))
        self.assertEqual(stat.S_IMODE(os.stat(ki).st_mode), 0o600)
        fajlok = [s for s in self.szerver.rekordok("Felmero Fajl") if s.get("fajl_nev") == "CONTEXT-vazlat.md"]
        self.assertEqual(len(fajlok), 1)
        self.assertEqual(fajlok[0]["feature"], "FT-00001")

    def test_context_ki_feltoltes_nelkul(self):
        ki = os.path.join(self.tmp, "CONTEXT.md")
        r = self.ep("context-vazlat", "FT-00001", "--ki", ki)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsNone(json.loads(r.stdout)["fajl"])
        with open(ki, encoding="utf-8") as fh:
            self.assertIn("## Intent", fh.read())

    def test_context_md_determinisztikus_cli(self):
        a = os.path.join(self.tmp, "a.md")
        b = os.path.join(self.tmp, "b.md")
        self.assertEqual(self.ep("context-vazlat", "FT-00001", "--ki", a).returncode, 0)
        self.assertEqual(self.ep("context-vazlat", "FT-00001", "--ki", b).returncode, 0)
        with open(a, "rb") as fa, open(b, "rb") as fb:
            self.assertEqual(fa.read(), fb.read())

    def test_kovetkezo_9_frappe_adatbol(self):
        self.f["frappe_lap"] = json.dumps(lap_adat())
        cfg = {"url": self.szerver.url, "adapter": "proto", "user": FELHASZNALO, "jelszo": JELSZO, "ceg": ""}
        p = erp_plan.Proto(cfg)
        f = p.feature("FT-00001")
        m = erp_plan.munka_reszlet(p, f)
        self.assertTrue(m["frappe"]["elerheto"])
        self.assertEqual(sum(1 for t in m["frappe"]["temak"] if t["allapot"] == "Hiányzik"), 12)
        m.update(hianylista={"hianyzik": []}, talalatok=[], osszefoglalo_db=1, ink07=False, kimeno_db=0)
        self.assertEqual(erp_plan.kovetkezo_lepes({"feature": "FT-00001", "munka": m})["lepes"], "FRAPPE")


if __name__ == "__main__":
    unittest.main()
