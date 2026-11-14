"""A munkák listája (munkak) és a következő lépés (kovetkezo) tesztjei: tiszta függvények és hamis szerver."""
import importlib.util
import json
import os
import pathlib
import socket
import stat
import unittest

from tests.hamis_szerver import CEG
from tests.test_parancsok import CliTeszt

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "skills" / "erp-plan" / "erp_plan.py"

spec = importlib.util.spec_from_file_location("erp_plan", CLI)
erp_plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(erp_plan)


def feature(name, allapot, projekt="FP-00001", modified="2026-11-10 10:00:00", **mezok):
    d = {"name": name, "cim": "Munka " + name, "projekt": projekt, "allapot": allapot,
         "teljesseg_szazalek": 0, "utolso_uzenet": None, "modified": modified}
    d.update(mezok)
    return d


def sor(name, allapot, modified="2026-11-10 10:00:00", projekt="FP-00001"):
    return erp_plan.munka_sor(feature(name, allapot, projekt=projekt, modified=modified),
                              {"name": projekt, "cim": "Projekt"})


def munka(**mezok):
    """Egy munka részletei, minden feltétel hiány nélkül. A tesztek ebből térnek el."""
    d = {"feature": "FT-00001", "cim": "Próba munka", "allapot": "Interjú", "kimeno_db": 0,
         "kliens_uzenet_db": 3, "osszefoglalo_db": 1, "ink07": False, "talalatok": [], "pontositando": [],
         "visszakuldes_indoka": None, "kihagyott": [], "frappe": None, "hianylista": {"hianyzik": []}}
    d.update(mezok)
    return d


def hianyzo(kod, kotelezo=True):
    return {"kod": kod, "cim": erp_plan.CIMEK[kod], "kotelezo": kotelezo, "allapot": "Hiányzik",
            "okok": ["nincs kitöltve"], "mit_kell_tudni": erp_plan.MIT_KELL_TUDNI[kod]}


def talalat(szabaly, suly, elfogadva=False):
    return {"szabaly": szabaly, "suly": suly, "elemek": [], "leiras": "", "kerdes": "", "ujjlenyomat": "x0",
            "elfogadva": elfogadva}


class MunkaSor(unittest.TestCase):
    def test_munka_sor_csoport_es_kinel(self):
        esetek = {"Vázlat": ("nyitott", "nalad"), "Interjú": ("nyitott", "nalad"),
                  "Visszaküldve": ("nyitott", "nalad"), "Bírálatra vár": ("nyitott", "mernoknel"),
                  "Elfogadva": ("lezart", "lezarva"), "Lezárva": ("lezart", "lezarva")}
        for allapot, varhato in esetek.items():
            s = sor("FT-00001", allapot)
            self.assertEqual((s["csoport"], s["kinel"]), varhato, allapot)
            self.assertEqual(s["allapot"], allapot)

    def test_projekt_cime_es_azonosito_bekerul(self):
        s = erp_plan.munka_sor(feature("FT-00007", "Vázlat", projekt="FP-00009"), {"name": "FP-00009", "cim": "Két projekt"})
        self.assertEqual((s["feature"], s["projekt"], s["projekt_cim"]), ("FT-00007", "FP-00009", "Két projekt"))


class Rendezes(unittest.TestCase):
    def setUp(self):
        self.sorok = [
            sor("FT-00004", "Elfogadva", "2026-11-01 09:00:00"),
            sor("FT-00003", "Bírálatra vár", "2026-11-12 09:00:00"),
            sor("FT-00001", "Interjú", "2026-11-10 09:00:00"),
            sor("FT-00005", "Vázlat", "2026-11-11 09:00:00"),
            sor("FT-00006", "Visszaküldve", "2026-11-13 09:00:00"),
        ]

    def test_rendezes_nalad_elol(self):
        nevek = [s["feature"] for s in erp_plan.munkak_rendez(self.sorok, "mind")]
        self.assertEqual(nevek, ["FT-00006", "FT-00005", "FT-00001", "FT-00003", "FT-00004"])

    def test_szuro_nyitott_lezart_mind(self):
        nyitott = [s["feature"] for s in erp_plan.munkak_rendez(self.sorok, "nyitott")]
        lezart = [s["feature"] for s in erp_plan.munkak_rendez(self.sorok, "lezart")]
        self.assertEqual(nyitott, ["FT-00006", "FT-00005", "FT-00001", "FT-00003"])
        self.assertEqual(lezart, ["FT-00004"])
        self.assertEqual(erp_plan.munkak_db(self.sorok), {"nyitott": 4, "lezart": 1, "mind": 5})


class KovetkezoGlobalis(unittest.TestCase):
    def adat(self, **mezok):
        d = {"kapcsolodas": None, "feature": None, "aktiv_projekt_db": 1, "mernoknel_db": 0, "munka": None,
             "tovabbi_nyitott": 0}
        d.update(mezok)
        return d

    def test_kovetkezo_globalis_sorai(self):
        # G1: nincs beállítás vagy hálózati hiba
        r = erp_plan.kovetkezo_lepes(self.adat(kapcsolodas="halozat"))
        self.assertEqual((r["lepes"], r["skill"], r["reszletek"]["ok"]), ("KAPCSOLODAS", "erp-plan-kapcsolat", "halozat"))
        # G2: nincs aktív projekt
        r = erp_plan.kovetkezo_lepes(self.adat(aktiv_projekt_db=0))
        self.assertEqual((r["lepes"], r["skill"]), ("UJ_PROJEKT", "erp-plan-munkak"))
        # G3: van nalad munka: a munka lépése, a többi nyitott száma
        r = erp_plan.kovetkezo_lepes(self.adat(munka=munka(allapot="Lezárva"), tovabbi_nyitott=2))
        self.assertEqual((r["lepes"], r["feature"], r["reszletek"]["tovabbi_nyitott"]), ("LEZART", "FT-00001", 2))
        # G4: csak mernoknel munka van
        r = erp_plan.kovetkezo_lepes(self.adat(mernoknel_db=2))
        self.assertEqual((r["lepes"], r["skill"]), ("VARAKOZAS", "erp-plan"))
        self.assertIn("2 munkád a mérnöknél van", r["szoveg"])
        # G5: nincs nyitott munka
        r = erp_plan.kovetkezo_lepes(self.adat())
        self.assertEqual((r["lepes"], r["skill"]), ("UJ_MUNKA", "erp-plan-munkak"))


class KovetkezoMunka(unittest.TestCase):
    def test_1_lezart(self):
        r = erp_plan.kovetkezo_lepes(_m(munka(allapot="Elfogadva")))
        self.assertEqual((r["lepes"], r["skill"]), ("LEZART", "erp-plan-munkak"))

    def test_2_mernoknel(self):
        r = erp_plan.kovetkezo_lepes({"feature": "FT-00001", "kapcsolodas": None, "munka": munka(allapot="Bírálatra vár")})
        self.assertEqual((r["lepes"], r["skill"]), ("VARAKOZAS", "erp-plan"))

    def test_3_kimeno(self):
        r = erp_plan.kovetkezo_lepes(_m(munka(kimeno_db=2)))
        self.assertEqual((r["lepes"], r["parancs"]), ("KIMENO", "kimeno FT-00001"))
        self.assertIn("2 üzeneted még nincs fent", r["szoveg"])

    def test_4_ellentmondas(self):
        r = erp_plan.kovetkezo_lepes(_m(munka(talalatok=[talalat("INK-03", "hiba")])))
        self.assertEqual((r["lepes"], r["skill"]), ("ELLENTMONDAS", "erp-plan-ellenorzes"))

    def test_5_szabad_mese(self):
        r = erp_plan.kovetkezo_lepes(_m(munka(kliens_uzenet_db=0)))
        self.assertEqual((r["lepes"], r["skill"]), ("SZABAD_MESE", "erp-plan-felmeres"))

    def test_6_pontositas(self):
        r = erp_plan.kovetkezo_lepes(_m(munka(
            allapot="Visszaküldve", visszakuldes_indoka="Hiányzik a határidő.",
            pontositando=[{"kod": "C2", "cim": "Ideális határidő", "megjegyzes": "Melyik hét?"}])))
        self.assertEqual((r["lepes"], r["skill"]), ("PONTOSITAS", "erp-plan-felmeres"))
        self.assertEqual(r["reszletek"]["kod"], "C2")
        self.assertEqual(r["reszletek"]["visszakuldes_indoka"], "Hiányzik a határidő.")

    def test_7_kerdes_kotelezo(self):
        r = erp_plan.kovetkezo_lepes(_m(munka(hianylista={"hianyzik": [hianyzo("B1"), hianyzo("UX", False)]})))
        self.assertEqual((r["lepes"], r["skill"]), ("KERDES", "erp-plan-felmeres"))
        self.assertEqual(r["reszletek"]["kod"], "B1")
        self.assertEqual(r["szoveg"], "A következő kérdés: A probléma ma.")

    def test_8_kerdes_nem_kotelezo(self):
        r = erp_plan.kovetkezo_lepes(_m(munka(hianylista={"hianyzik": [hianyzo("UX", False)]})))
        self.assertEqual((r["lepes"], r["skill"]), ("KERDES_NEM_KOTELEZO", "erp-plan-felmeres"))
        self.assertIn("Kihagyható.", r["szoveg"])

    def test_9_frappe(self):
        frappe = {"elerheto": True, "kihagyva": False,
                  "temak": [{"kod": "FR-ADAT", "cim": "Nyilvántartott adatok", "allapot": "Hiányzik"}]}
        r = erp_plan.kovetkezo_lepes(_m(munka(frappe=frappe)))
        self.assertEqual((r["lepes"], r["skill"]), ("FRAPPE", "erp-plan-frappe"))
        self.assertIn("Nyilvántartott adatok", r["szoveg"])

    def test_10_figyelem(self):
        r = erp_plan.kovetkezo_lepes(_m(munka(talalatok=[talalat("INK-02", "figyelem")])))
        self.assertEqual((r["lepes"], r["skill"]), ("FIGYELEM", "erp-plan-ellenorzes"))

    def test_11_osszefoglalo(self):
        r = erp_plan.kovetkezo_lepes(_m(munka(osszefoglalo_db=0)))
        self.assertEqual((r["lepes"], r["skill"]), ("OSSZEFOGLALO", "erp-plan-felmeres"))
        r = erp_plan.kovetkezo_lepes(_m(munka(ink07=True)))
        self.assertEqual(r["lepes"], "OSSZEFOGLALO")

    def test_12_bekuldes(self):
        r = erp_plan.kovetkezo_lepes(_m(munka()))
        self.assertEqual((r["lepes"], r["skill"]), ("BEKULDES", "erp-plan-felmeres"))

    def test_sorrend_az_alacsonyabb_sorszam_nyer(self):
        # 3 (kimeno) a 6. (pontosítás) előtt, 4 (ellentmondás) az 5. (szabad mese) előtt, 9 a 10. előtt.
        r = erp_plan.kovetkezo_lepes(_m(munka(kimeno_db=1, allapot="Visszaküldve",
                                              pontositando=[{"kod": "UZ", "cim": "Üzleti", "megjegyzes": ""}])))
        self.assertEqual(r["lepes"], "KIMENO")
        r = erp_plan.kovetkezo_lepes(_m(munka(talalatok=[talalat("INK-03", "hiba")], kliens_uzenet_db=0)))
        self.assertEqual(r["lepes"], "ELLENTMONDAS")
        frappe = {"elerheto": True, "kihagyva": False,
                  "temak": [{"kod": "FR-ADAT", "cim": "Nyilvántartott adatok", "allapot": "Hiányzik"}]}
        r = erp_plan.kovetkezo_lepes(_m(munka(frappe=frappe, talalatok=[talalat("INK-02", "figyelem")])))
        self.assertEqual(r["lepes"], "FRAPPE")

    def test_kihagyott_elem_nem_jon_ujra(self):
        r = erp_plan.kovetkezo_lepes(_m(munka(kihagyott=["UX"],
                                              hianylista={"hianyzik": [hianyzo("UX", False), hianyzo("TD", False)]})))
        self.assertEqual((r["lepes"], r["reszletek"]["kod"]), ("KERDES_NEM_KOTELEZO", "TD"))


def _m(m):
    return {"feature": m["feature"], "kapcsolodas": None, "munka": m}


class KovetkezoCli(CliTeszt):
    def setUp(self):
        super().setUp()
        self.szerver.rekord("Felmero Feature", "FT-00001")["modified"] = "2026-11-11 10:00:00"

    def tobb_munka(self):
        """Két projekt, négy munka a saját szervezeten belül (és egy idegen, ami nem látszik)."""
        self.szerver.tarol("Felmero Projekt", {"name": "FP-00003", "cim": "Második projekt",
                                               "crm_organization": CEG, "allapot": "Aktív"})
        self.szerver.tarol("Felmero Feature", {"name": "FT-00003", "cim": "Mernöknél", "projekt": "FP-00003",
                                               "crm_organization": CEG, "allapot": "Bírálatra vár",
                                               "modified": "2026-11-09 10:00:00", "elemek": [], "bizonyitekok": []})
        self.szerver.tarol("Felmero Feature", {"name": "FT-00004", "cim": "Lezárt", "projekt": "FP-00003",
                                               "crm_organization": CEG, "allapot": "Elfogadva",
                                               "modified": "2026-11-01 10:00:00", "elemek": [], "bizonyitekok": []})
        self.szerver.tarol("Felmero Feature", {"name": "FT-00005", "cim": "Vázlat", "projekt": "FP-00001",
                                               "crm_organization": CEG, "allapot": "Vázlat",
                                               "modified": "2026-11-12 10:00:00", "elemek": [], "bizonyitekok": []})

    def test_konfig_nelkul_nem_3_as_kod(self):
        self.env["ERP_PLAN_CONFIG"] = os.path.join(self.tmp, "nincs", "config.json")
        eredmeny = self.ep("kovetkezo")
        self.assertEqual(eredmeny.returncode, 0, eredmeny.stdout + eredmeny.stderr)
        adat = json.loads(eredmeny.stdout)
        self.assertEqual((adat["lepes"], adat["reszletek"]["ok"]), ("KAPCSOLODAS", "nincs_beallitas"))

    def test_halozati_hiba_nem_5_os_kod(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            szabad_port = s.getsockname()[1]
        with open(self.konfig, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["url"] = "http://127.0.0.1:%d" % szabad_port
        with open(self.konfig, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        eredmeny = self.ep("kovetkezo")
        self.assertEqual(eredmeny.returncode, 0, eredmeny.stdout + eredmeny.stderr)
        self.assertEqual(json.loads(eredmeny.stdout)["reszletek"]["ok"], "halozat")

    def test_kovetkezo_munkara_a_szerver_adatbol(self):
        eredmeny = self.ep("kovetkezo", "FT-00001")
        self.assertEqual(eredmeny.returncode, 0, eredmeny.stdout + eredmeny.stderr)
        adat = json.loads(eredmeny.stdout)
        self.assertEqual((adat["feature"], adat["lepes"], adat["skill"]), ("FT-00001", "KERDES", "erp-plan-felmeres"))
        self.assertEqual(adat["reszletek"]["kod"], "B1")

    def test_globalis_a_legfrissebb_nalad_munkat_veszi(self):
        self.tobb_munka()
        eredmeny = self.ep("kovetkezo")
        self.assertEqual(eredmeny.returncode, 0, eredmeny.stdout + eredmeny.stderr)
        adat = json.loads(eredmeny.stdout)
        self.assertEqual(adat["feature"], "FT-00005")
        self.assertEqual(adat["lepes"], "SZABAD_MESE")
        self.assertEqual(adat["reszletek"]["tovabbi_nyitott"], 1)

    def test_kihagy_csak_nem_kotelezore(self):
        eredmeny = self.ep("kovetkezo", "FT-00001", "--kihagy", "B1")
        self.assertEqual(eredmeny.returncode, 2, eredmeny.stdout + eredmeny.stderr)
        self.assertEqual(json.loads(eredmeny.stdout)["hiba"]["kod"], "FELMERO_ELEM_ADAT")
        eredmeny = self.ep("kovetkezo", "FT-00001", "--kihagy", "UX")
        self.assertEqual(eredmeny.returncode, 0, eredmeny.stdout + eredmeny.stderr)
        helyi = os.path.join(os.path.dirname(self.konfig), "helyi", "FT-00001.json")
        self.assertEqual(stat.S_IMODE(os.stat(helyi).st_mode), 0o600)
        with open(helyi, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["kihagyott"], ["UX"])

    def test_munkak_hamis_szerverrel(self):
        self.tobb_munka()
        eredmeny = self.ep("munkak", "--allapot", "mind")
        self.assertEqual(eredmeny.returncode, 0, eredmeny.stdout + eredmeny.stderr)
        adat = json.loads(eredmeny.stdout)
        self.assertEqual(adat["db"], {"nyitott": 3, "lezart": 1, "mind": 4})
        self.assertEqual([m["feature"] for m in adat["munkak"]], ["FT-00005", "FT-00001", "FT-00003", "FT-00004"])
        self.assertEqual([m["kinel"] for m in adat["munkak"]], ["nalad", "nalad", "mernoknel", "lezarva"])
        nyitott = json.loads(self.ep("munkak").stdout)
        self.assertEqual(nyitott["allapot_szuro"], "nyitott")
        self.assertEqual(len(nyitott["munkak"]), 3)


if __name__ == "__main__":
    unittest.main()
