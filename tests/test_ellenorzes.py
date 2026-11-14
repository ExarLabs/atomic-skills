"""Az ellenorzes szabálymotorának tesztjei: szabályonként egy találat-eset és egy tiszta eset."""
import importlib.util
import json
import os
import pathlib
import stat
import unittest
from datetime import date

from tests.test_parancsok import CliTeszt

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "skills" / "erp-plan" / "erp_plan.py"

spec = importlib.util.spec_from_file_location("erp_plan", CLI)
erp_plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(erp_plan)

MA = date(2026, 11, 14)
ALAP_UZENET = "Havonta sokszor javítok hibát, kézzel."


def el(kod, ertek, allapot="Kész", **mezok):
    d = {"kod": kod, "ertek": ertek, "datum": None, "szam": None, "kiegeszites": "", "forras": "kliens",
         "allapot": allapot, "mernok_allapot": "", "mernok_megjegyzes": ""}
    d.update(mezok)
    return d


def bz(elem, idezet, uzenet="U-1", ervenyes=1):
    return {"elem": elem, "idezet": idezet, "uzenet": uzenet, "uzenet_sorszam": 1, "ervenyes": ervenyes}


def ko(elemek=(), biz=(), uzenetek=None, **mezok):
    uz = uzenetek if uzenetek is not None else [{"name": "U-1", "sorszam": 1, "szoveg": ALAP_UZENET}]
    k = {"name": "FT-00001", "cim": "Próba munka", "allapot": "Interjú", "elemek": list(elemek),
         "bizonyitekok": list(biz), "uzenetek": uz, "osszefoglalo": None, "hivatkozasok": [],
         "frappe_idezetek": [], "tarolt_szazalek": None}
    k.update(mezok)
    return k


def fut(k, tv=(), kimeno=0):
    return erp_plan.ellenoriz(k, list(tv), kimeno, MA)


def szabalyok(talalatok):
    return {t["szabaly"] for t in talalatok}


class Szabalyok(unittest.TestCase):
    def test_ink01_hit(self):
        k = ko(elemek=[el("B1", "Kézi számolás.")], biz=[bz("B1", "nincs ilyen mondat", ervenyes=0)])
        self.assertIn("INK-01", szabalyok(fut(k)))

    def test_ink01_tiszta(self):
        k = ko(elemek=[el("B1", "Kézi számolás.")], biz=[bz("B1", "Havonta sokszor javítok hibát")])
        self.assertNotIn("INK-01", szabalyok(fut(k)))

    def test_ink02_hit(self):
        k = ko(elemek=[el("B1", "Havonta 40 db hibát javítok.")], biz=[bz("B1", ALAP_UZENET)])
        self.assertIn("INK-02", szabalyok(fut(k)))

    def test_ink02_tiszta(self):
        szoveg = "Havonta 40 db hibát javítok, kézzel."
        k = ko(elemek=[el("B1", szoveg)], biz=[bz("B1", szoveg)],
               uzenetek=[{"name": "U-1", "sorszam": 1, "szoveg": szoveg}])
        self.assertNotIn("INK-02", szabalyok(fut(k)))

    def test_ink03_hit(self):
        k = ko(elemek=[el("C1", "Jövő hét.", datum="2027-01-11"), el("C2", "Január vége.", datum="2027-01-10")])
        self.assertIn("INK-03", szabalyok(fut(k)))

    def test_ink03_tiszta(self):
        k = ko(elemek=[el("C1", "Jövő hét.", datum="2027-01-10"), el("C2", "Január vége.", datum="2027-01-20")])
        self.assertNotIn("INK-03", szabalyok(fut(k)))

    def test_ink04_hit(self):
        k = ko(elemek=[el("C1", "Jövő hét.", datum="2027-01-10"), el("C2", "Március.", datum="2027-03-01")])
        self.assertIn("INK-04", szabalyok(fut(k)))

    def test_ink04_tiszta(self):
        k = ko(elemek=[el("C1", "Jövő hét.", datum="2027-01-10"), el("C2", "Január vége.", datum="2027-01-20")])
        self.assertNotIn("INK-04", szabalyok(fut(k)))

    def test_ink05_hit(self):
        k = ko(elemek=[el("C1", "Múlt hét.", datum="2026-11-01"), el("C2", "Január.", datum="2027-01-20")])
        self.assertIn("INK-05", szabalyok(fut(k)))

    def test_ink05_tiszta(self):
        k = ko(elemek=[el("C1", "Jövő hét.", datum="2027-01-10"), el("C2", "Január.", datum="2027-01-20")])
        self.assertNotIn("INK-05", szabalyok(fut(k)))

    def test_ink06_hit(self):
        k = ko(elemek=[el("D4", "Két hónap.", szam=45)])
        self.assertIn("INK-06", szabalyok(fut(k)))

    def test_ink06_tiszta(self):
        k = ko(elemek=[el("D4", "Két hónap.", szam=60)])
        self.assertNotIn("INK-06", szabalyok(fut(k)))

    def test_ink07_hit(self):
        uz = [{"name": "U-1", "sorszam": 1, "szoveg": ALAP_UZENET}, {"name": "U-2", "sorszam": 2, "szoveg": "Még egy."}]
        k = ko(uzenetek=uz, osszefoglalo={"verzio": 1, "uzenet_sorszamig": 1})
        self.assertIn("INK-07", szabalyok(fut(k)))

    def test_ink07_tiszta(self):
        uz = [{"name": "U-1", "sorszam": 1, "szoveg": ALAP_UZENET}, {"name": "U-2", "sorszam": 2, "szoveg": "Még egy."}]
        k = ko(uzenetek=uz, osszefoglalo={"verzio": 1, "uzenet_sorszamig": 2})
        self.assertNotIn("INK-07", szabalyok(fut(k)))

    def test_ink08_hit(self):
        k = ko(hivatkozasok=[{"cel": "FT-00002", "cel_cim": "Régi munka", "allapot": "Lezárva"}])
        self.assertIn("INK-08", szabalyok(fut(k)))

    def test_ink08_tiszta(self):
        k = ko(hivatkozasok=[{"cel": "FT-00002", "cel_cim": "Régi munka", "allapot": "Interjú"}])
        self.assertNotIn("INK-08", szabalyok(fut(k)))

    def test_ink09_hit(self):
        k = ko(elemek=[el("B1", "Havonta 40 db hibát javítok."), el("D2", "Ma 60 db van.")])
        self.assertIn("INK-09", szabalyok(fut(k)))

    def test_ink09_tiszta(self):
        k = ko(elemek=[el("B1", "Havonta 40 db hibát javítok."), el("D2", "Ma 40 db van.")])
        self.assertNotIn("INK-09", szabalyok(fut(k)))

    def test_ink10_hit(self):
        k = ko(elemek=[el("B3", "Kézi számolás minden nap, havonta"),
                       el("B2", "Ez a folyamat: kézi számolás minden nap, havonta, ami sok.")])
        self.assertIn("INK-10", szabalyok(fut(k)))

    def test_ink10_tiszta(self):
        k = ko(elemek=[el("B3", "Kézi számolás minden nap, havonta"), el("B2", "Automatikus riport készül.")])
        self.assertNotIn("INK-10", szabalyok(fut(k)))

    def test_ink11_hit(self):
        self.assertIn("INK-11", szabalyok(fut(ko(elemek=[el("D1", "Gyors és könnyű legyen.")]))))

    def test_ink11_tiszta(self):
        k = ko(elemek=[el("D1", "A riport 30 napon belül legalább 95%-ban pontos legyen.")])
        self.assertNotIn("INK-11", szabalyok(fut(k)))

    def test_ink12_hit(self):
        self.assertIn("INK-12", szabalyok(fut(ko(elemek=[el("D2", "Most kézzel csináljuk.")]))))

    def test_ink12_tiszta(self):
        k = ko(elemek=[el("D2", "Ma 40 db van.", kiegeszites="Excel, 2026.11.01 állapot")])
        self.assertNotIn("INK-12", szabalyok(fut(k)))

    def test_ink13_hit(self):
        self.assertIn("INK-13", szabalyok(fut(ko(elemek=[el("D3", "Kevesebb hiba legyen.")]))))

    def test_ink13_tiszta(self):
        self.assertNotIn("INK-13", szabalyok(fut(ko(elemek=[el("D3", "Legalább 20 db-ral kevesebb hiba.")]))))

    def test_ink14_hit(self):
        k = ko(elemek=[el("B1", "x"), el("B2", "y"), el("UZ", "z")],
               biz=[bz("B1", ALAP_UZENET), bz("B2", ALAP_UZENET), bz("UZ", ALAP_UZENET)])
        self.assertIn("INK-14", szabalyok(fut(k)))

    def test_ink14_tiszta(self):
        uz = [{"name": "U-1", "sorszam": 1, "szoveg": "Első mondat itt áll."},
              {"name": "U-2", "sorszam": 2, "szoveg": "Második mondat is van."},
              {"name": "U-3", "sorszam": 3, "szoveg": "Harmadik mondat is."}]
        k = ko(elemek=[el("B1", "x"), el("B2", "y"), el("UZ", "z")],
               biz=[bz("B1", "Első mondat itt áll.", "U-1"), bz("B2", "Második mondat is van.", "U-2"),
                    bz("UZ", "Harmadik mondat is.", "U-3")], uzenetek=uz)
        self.assertNotIn("INK-14", szabalyok(fut(k)))

    def test_ink15_hit(self):
        tv = [{"name": "FT-00009", "cim": "riport  KÉSZÍTÉS", "allapot": "Vázlat", "elemek": []}]
        k = ko(cim="Riport készítés")
        self.assertIn("INK-15", szabalyok(fut(k, tv)))

    def test_ink15_tiszta(self):
        tv = [{"name": "FT-00009", "cim": "Másik munka", "allapot": "Vázlat", "elemek": []}]
        self.assertNotIn("INK-15", szabalyok(fut(ko(cim="Riport készítés"), tv)))

    def test_ink16_hit(self):
        k = ko(elemek=[el("B3", "Kézi számolás minden nap, havonta")])
        tv = [{"name": "FT-00009", "cim": "x", "allapot": "Vázlat",
               "elemek": [el("B2", "Ez a folyamat: kézi számolás minden nap, havonta, ami sok.")]}]
        self.assertIn("INK-16", szabalyok(fut(k, tv)))

    def test_ink16_tiszta(self):
        k = ko(elemek=[el("B3", "Kézi számolás minden nap, havonta")])
        tv = [{"name": "FT-00009", "cim": "x", "allapot": "Vázlat", "elemek": [el("B2", "Automatikus riport.")]}]
        self.assertNotIn("INK-16", szabalyok(fut(k, tv)))

    def test_ink17_hit(self):
        k = ko(frappe_idezetek=[{"tema": "FR-ADAT", "cim": "Nyilvántartott adatok",
                                 "idezet": "Ez a mondat nincs meg sehol."}])
        self.assertIn("INK-17", szabalyok(fut(k)))

    def test_ink17_tiszta(self):
        k = ko(frappe_idezetek=[{"tema": "FR-ADAT", "cim": "Nyilvántartott adatok", "idezet": ALAP_UZENET}])
        self.assertNotIn("INK-17", szabalyok(fut(k)))

    def test_ink18_hit(self):
        self.assertIn("INK-18", szabalyok(fut(ko(), kimeno=2)))

    def test_ink18_tiszta(self):
        self.assertNotIn("INK-18", szabalyok(fut(ko(), kimeno=0)))

    def test_ink19_hit(self):
        self.assertIn("INK-19", szabalyok(fut(ko(tarolt_szazalek=50))))

    def test_ink19_tiszta(self):
        self.assertNotIn("INK-19", szabalyok(fut(ko(tarolt_szazalek=0))))


class Rendezes(unittest.TestCase):
    def test_sorrend_hiba_elol(self):
        k = ko(elemek=[el("D2", "Most kézzel csináljuk."), el("C1", "Jövő hét.", datum="2027-01-11"),
                       el("C2", "Január.", datum="2027-01-10")], kimeno=0)
        talalatok = fut(k)
        sulyok = [t["suly"] for t in talalatok]
        self.assertEqual(sulyok, sorted(sulyok, key=lambda s: 0 if s == "hiba" else 1))
        self.assertEqual(talalatok[0]["suly"], "hiba")

    def test_ujjlenyomat_valtozik_ha_az_ertek_valtozik(self):
        egy = fut(ko(elemek=[el("D4", "Egy hónap.", szam=45)]))
        ketto = fut(ko(elemek=[el("D4", "Egy hónap, most.", szam=45)]))
        ismet = fut(ko(elemek=[el("D4", "Egy hónap.", szam=45)]))
        self.assertNotEqual(egy[0]["ujjlenyomat"], ketto[0]["ujjlenyomat"])
        self.assertEqual(egy[0]["ujjlenyomat"], ismet[0]["ujjlenyomat"])
        self.assertEqual(len(egy[0]["ujjlenyomat"]), 10)


class CliEllenorzes(CliTeszt):
    def elemek_beallitas(self, elemek):
        self.szerver.rekord("Felmero Feature", "FT-00001")["elemek"] = elemek

    def hiba_elemek(self):
        return [{"kod": "C1", "ertek": "Jövő hét.", "datum": "2027-01-11", "szam": None, "kiegeszites": "",
                 "forras": "kliens"},
                {"kod": "C2", "ertek": "Január.", "datum": "2027-01-10", "szam": None, "kiegeszites": "",
                 "forras": "kliens"}]

    def figyelem_elemek(self):
        return [{"kod": "D2", "ertek": "Most kézzel csináljuk.", "datum": None, "szam": None, "kiegeszites": "",
                 "forras": "kliens"}]

    def test_kilepes_6_ha_van_hiba(self):
        self.elemek_beallitas(self.hiba_elemek())
        eredmeny = self.ep("ellenorzes", "FT-00001")
        self.assertEqual(eredmeny.returncode, 6, eredmeny.stdout + eredmeny.stderr)
        adat = json.loads(eredmeny.stdout)
        self.assertEqual(adat["hiba_db"], 1)
        self.assertEqual(adat["talalatok"][0]["szabaly"], "INK-03")

    def test_elfogadas_csak_figyelemre(self):
        self.elemek_beallitas(self.hiba_elemek())
        hiba = json.loads(self.ep("ellenorzes", "FT-00001").stdout)["talalatok"][0]
        eredmeny = self.ep("ellenorzes", "FT-00001", "--elfogad", hiba["ujjlenyomat"])
        self.assertEqual(eredmeny.returncode, 2, eredmeny.stdout + eredmeny.stderr)
        self.assertEqual(json.loads(eredmeny.stdout)["hiba"]["kod"], "FELMERO_ELEM_ADAT")

    def test_elfogadott_nem_jon_ujra_de_mind_mutatja(self):
        self.elemek_beallitas(self.figyelem_elemek())
        elso = json.loads(self.ep("ellenorzes", "FT-00001").stdout)
        self.assertEqual(elso["figyelem_db"], 1)
        ujj = elso["talalatok"][0]["ujjlenyomat"]
        self.assertEqual(self.ep("ellenorzes", "FT-00001", "--elfogad", ujj).returncode, 0)
        masodik = json.loads(self.ep("ellenorzes", "FT-00001").stdout)
        self.assertEqual(masodik["talalatok"], [])
        self.assertEqual((masodik["figyelem_db"], masodik["elfogadott_db"]), (0, 1))
        mind = json.loads(self.ep("ellenorzes", "FT-00001", "--mind").stdout)
        self.assertTrue(mind["talalatok"][0]["elfogadva"])

    def test_helyi_fajl_600(self):
        self.elemek_beallitas(self.figyelem_elemek())
        ujj = json.loads(self.ep("ellenorzes", "FT-00001").stdout)["talalatok"][0]["ujjlenyomat"]
        self.ep("ellenorzes", "FT-00001", "--elfogad", ujj)
        helyi = os.path.join(os.path.dirname(self.konfig), "helyi", "FT-00001.json")
        self.assertEqual(stat.S_IMODE(os.stat(helyi).st_mode), 0o600)
        with open(helyi, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["elfogadott"], [ujj])


class P1K(unittest.TestCase):
    """P1-K javítás: reszletek, INK-02 dátum-zaj, INK-04 negatív köz."""

    def reszlet(self, talalatok, kod):
        talalat = [t for t in talalatok if t["szabaly"] == kod]
        self.assertTrue(talalat, kod)
        return talalat[0]["reszletek"]

    def test_reszletek_minden_szabalyban_kitoltott(self):
        esetek = {
            "INK-01": ko(elemek=[el("B1", "Kézi számolás.")], biz=[bz("B1", "nincs ilyen mondat", ervenyes=0)]),
            "INK-02": ko(elemek=[el("B1", "Havonta 40 db hibát javítok.")], biz=[bz("B1", ALAP_UZENET)]),
            "INK-03": ko(elemek=[el("C1", "Jövő hét.", datum="2027-01-11"), el("C2", "Január vége.", datum="2027-01-10")]),
            "INK-04": ko(elemek=[el("C1", "Jövő hét.", datum="2027-01-10"), el("C2", "Március.", datum="2027-03-01")]),
            "INK-05": ko(elemek=[el("C1", "Múlt hét.", datum="2026-11-01"), el("C2", "Január.", datum="2027-01-20")]),
            "INK-06": ko(elemek=[el("D4", "Két hónap.", szam=45)]),
            "INK-07": ko(uzenetek=[{"name": "U-1", "sorszam": 1, "szoveg": ALAP_UZENET},
                                   {"name": "U-2", "sorszam": 2, "szoveg": "Még egy."}],
                         osszefoglalo={"verzio": 1, "uzenet_sorszamig": 1}),
            "INK-08": ko(hivatkozasok=[{"cel": "FT-00002", "cel_cim": "Régi munka", "allapot": "Lezárva"}]),
            "INK-09": ko(elemek=[el("B1", "Havonta 40 db hibát javítok."), el("D2", "Ma 60 db van.")]),
            "INK-10": ko(elemek=[el("B3", "Kézi számolás minden nap, havonta"),
                                 el("B2", "Ez a folyamat: kézi számolás minden nap, havonta, ami sok.")]),
            "INK-11": ko(elemek=[el("D1", "Gyors és könnyű legyen.")]),
            "INK-12": ko(elemek=[el("D2", "Most kézzel csináljuk.")]),
            "INK-13": ko(elemek=[el("D3", "Kevesebb hiba legyen.")]),
            "INK-14": ko(elemek=[el("B1", "x"), el("B2", "y"), el("UZ", "z")],
                         biz=[bz("B1", ALAP_UZENET), bz("B2", ALAP_UZENET), bz("UZ", ALAP_UZENET)]),
            "INK-15": ko(cim="Riport készítés"),
            "INK-16": ko(elemek=[el("B3", "Kézi számolás minden nap, havonta")]),
            "INK-17": ko(frappe_idezetek=[{"tema": "FR-ADAT", "cim": "Nyilvántartott adatok",
                                           "idezet": "Ez a mondat nincs meg sehol."}]),
            "INK-18": ko(),
            "INK-19": ko(tarolt_szazalek=50),
        }
        tv = {"INK-15": [{"name": "FT-00009", "cim": "riport  KÉSZÍTÉS", "allapot": "Vázlat", "elemek": []}],
              "INK-16": [{"name": "FT-00009", "cim": "x", "allapot": "Vázlat",
                          "elemek": [el("B2", "Ez a folyamat: kézi számolás minden nap, havonta, ami sok.")]}]}
        kimeno = {"INK-18": 2}
        for kod, k in esetek.items():
            with self.subTest(szabaly=kod):
                talalatok = erp_plan.ellenoriz(k, tv.get(kod, []), kimeno.get(kod, 0), MA)
                reszlet = self.reszlet(talalatok, kod)
                self.assertIsInstance(reszlet, dict)
                self.assertTrue(reszlet, "reszletek üres: %s" % kod)

    def test_reszletek_tartalmazza_a_ket_allitast(self):
        k = ko(elemek=[el("C1", "Jövő hét.", datum="2027-01-11"), el("C2", "Január vége.", datum="2027-01-10")])
        reszlet = self.reszlet(fut(k), "INK-03")
        self.assertEqual((reszlet["c1"], reszlet["c2"]), ("2027-01-11", "2027-01-10"))

    def test_ink02_datum_nem_ad_zajt(self):
        k = ko(elemek=[el("C1", "2027. január 11.")],
               biz=[bz("C1", "Január 11-ig kész legyen.")],
               uzenetek=[{"name": "U-1", "sorszam": 1, "szoveg": "Január 11-ig kész legyen."}])
        self.assertNotIn("INK-02", szabalyok(fut(k)))

    def test_ink02_datum_evszam_iso_alak_sem_ad_zajt(self):
        k = ko(elemek=[el("C2", "2027-01-11 körül")],
               biz=[bz("C2", "Január 11-ig kész legyen.")],
               uzenetek=[{"name": "U-1", "sorszam": 1, "szoveg": "Január 11-ig kész legyen."}])
        self.assertNotIn("INK-02", szabalyok(fut(k)))

    def test_ink02_valodi_szam_meg_jelzi(self):
        k = ko(elemek=[el("C1", "2027. január 11. és 40 db hiba")],
               biz=[bz("C1", "Január 11-ig kész legyen.")],
               uzenetek=[{"name": "U-1", "sorszam": 1, "szoveg": "Január 11-ig kész legyen."}])
        self.assertIn("INK-02", szabalyok(fut(k)))

    def test_ink04_negativ_koz_erthato_kerdes(self):
        k = ko(elemek=[el("C1", "Jövő hét.", datum="2027-01-11"), el("C2", "Január.", datum="2027-01-04")])
        talalatok = fut(k)
        ink04 = [t for t in talalatok if t["szabaly"] == "INK-04"]
        self.assertEqual(len(ink04), 1)
        kerdes = ink04[0]["kerdes"]
        self.assertNotIn("-7", kerdes)
        self.assertNotIn(" -", kerdes)
        self.assertIn("2027-01-04", kerdes)
        self.assertIn("2027-01-11", kerdes)
        self.assertIn("előtt", kerdes)


if __name__ == "__main__":
    unittest.main()
