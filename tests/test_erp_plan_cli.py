"""Egységtesztek az erp_plan.py tiszta függvényeire (hálózat nélkül)."""
import importlib.util
import os
import pathlib
import stat
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI_UTVONAL = ROOT / "skills" / "erp-plan" / "erp_plan.py"

spec = importlib.util.spec_from_file_location("felmero", CLI_UTVONAL)
felmero = importlib.util.module_from_spec(spec)
spec.loader.exec_module(felmero)


def uzenet(name, sorszam, szoveg):
    return {"name": name, "sorszam": sorszam, "szoveg": szoveg}


def sor(kod, **mezok):
    d = {"kod": kod, "ertek": "", "datum": None, "szam": None, "kiegeszites": "",
         "forras": "kliens", "mernok_allapot": "", "mernok_megjegyzes": ""}
    d.update(mezok)
    return d


class Normalizalas(unittest.TestCase):
    def test_whitespace_egy_szokozre_es_levag(self):
        self.assertEqual(felmero.normal("  Egy\n\nkettő\t három  "), "Egy kettő három")

    def test_nfc_egyenlove_teszi_a_szetbontott_ekezetet(self):
        szetbontott = "és"
        osszevont = "és"
        self.assertEqual(felmero.normal(szetbontott), felmero.normal(osszevont))

    def test_kis_es_nagybetu_marad(self):
        self.assertEqual(felmero.normal("Havonta FUT"), "Havonta FUT")

    def test_ures_es_none(self):
        self.assertEqual(felmero.normal(None), "")
        self.assertEqual(felmero.normal("   "), "")


class IdezetFormai(unittest.TestCase):
    def test_rovid_idezet_elutasitva(self):
        self.assertEqual(felmero.idezet_formai_hiba("egy szó"), "FELMERO_IDEZET_ROVID")

    def test_egy_szo_hosszan_is_rovid(self):
        self.assertEqual(felmero.idezet_formai_hiba("egyetlenegyszoroshosszu"), "FELMERO_IDEZET_ROVID")

    def test_tul_hosszu_idezet_elutasitva(self):
        self.assertEqual(felmero.idezet_formai_hiba("szó " * 400), "FELMERO_HOSSZ")

    def test_jo_idezet_elfogadva(self):
        self.assertIsNone(felmero.idezet_formai_hiba("Havonta egyszer kézzel számolom újra."))


class IdezetEgyezes(unittest.TestCase):
    def setUp(self):
        self.uzenetek = [
            uzenet("U-1", 1, "Meséld el, mi a gond."),
            uzenet("U-2", 2, "Ez a folyamat havonta\nfut, kézzel."),
            uzenet("U-3", 3, "Havonta fut, és mindig ugyanaz."),
        ]

    def test_normalizalt_szoveggel_is_talal(self):
        self.assertEqual(felmero.idezet_keres("Ez a folyamat havonta fut, kézzel.", self.uzenetek), ("U-2", 2))

    def test_elso_talalat_sorszam_szerint(self):
        self.assertEqual(felmero.idezet_keres("havonta fut", self.uzenetek), ("U-2", 2))

    def test_nem_szo_szerinti_idezet_nincs_talalat(self):
        self.assertIsNone(felmero.idezet_keres("havonta kétszer fut", self.uzenetek))

    def test_ures_lista_nincs_talalat(self):
        self.assertIsNone(felmero.idezet_keres("Havonta fut", []))

    def test_ures_idezet_nem_talal(self):
        self.assertIsNone(felmero.idezet_keres("   ", self.uzenetek))


class ElemAllapot(unittest.TestCase):
    def test_hianyzo_sor(self):
        self.assertEqual(felmero.elem_allapot(None, 0), ("Hiányzik", ["nincs kitöltve"]))

    def test_idezettel_kesz(self):
        self.assertEqual(felmero.elem_allapot(sor("B1", ertek="Kézi számolás."), 1), ("Kész", []))

    def test_idezet_nelkul_hiányos(self):
        allapot, okok = felmero.elem_allapot(sor("B1", ertek="Kézi számolás."), 0)
        self.assertEqual(allapot, "Hiányos")
        self.assertEqual(okok, ["nincs szó szerinti idézet egy kliens-üzenetből"])

    def test_mernok_sor_idezet_nelkul_is_kesz(self):
        self.assertEqual(felmero.elem_allapot(sor("B1", ertek="x", forras="mernok"), 0), ("Kész", []))

    def test_c1_datum_kell(self):
        allapot, okok = felmero.elem_allapot(sor("C1", ertek="Jövő hét."), 1)
        self.assertEqual((allapot, okok), ("Hiányos", ["nincs dátum"]))

    def test_c2_nem_lehet_c1_elott(self):
        c2 = sor("C2", ertek="Január vége.", datum="2027-01-10")
        allapot, okok = felmero.elem_allapot(c2, 1, c1_datum="2027-01-11")
        self.assertEqual(allapot, "Hiányos")
        self.assertIn("a határidő a kezdés előtt van", okok)

    def test_c2_ugyanazon_a_napon_jo(self):
        c2 = sor("C2", ertek="Január vége.", datum="2027-01-11")
        self.assertEqual(felmero.elem_allapot(c2, 1, c1_datum="2027-01-11"), ("Kész", []))

    def test_d4_csak_30_60_90(self):
        allapot, okok = felmero.elem_allapot(sor("D4", ertek="Egy hónap.", szam=45), 1)
        self.assertEqual(allapot, "Hiányos")
        self.assertIn("a mérési időszak 30, 60 vagy 90 nap legyen", okok)
        self.assertEqual(felmero.elem_allapot(sor("D4", ertek="Két hónap.", szam=60), 1), ("Kész", []))

    def test_d2_baseline_forras_kell(self):
        allapot, okok = felmero.elem_allapot(sor("D2", ertek="Ma 40 db.", kiegeszites=""), 1)
        self.assertEqual(allapot, "Hiányos")
        self.assertIn("nincs megadva a baseline forrása", okok)

    def test_pontositando_mernoki_jeloles(self):
        s = sor("UZ", ertek="Kivétel: hétvége.", mernok_allapot="Pontosítandó", mernok_megjegyzes="Melyik hétvége?")
        allapot, okok = felmero.elem_allapot(s, 1)
        self.assertEqual(allapot, "Hiányos")
        self.assertEqual(okok, ["a mérnök pontosítást kér: Melyik hétvége?"])


class TeljessegEsHianylista(unittest.TestCase):
    def test_szazalek_ures_es_teljes(self):
        self.assertEqual(felmero.teljesseg_szazalek({}), 0)
        self.assertEqual(felmero.teljesseg_szazalek({k: "Kész" for k in felmero.KOTELEZO}), 100)

    def test_szazalek_harom_a_tizenkettobol(self):
        allapotok = {k: "Kész" for k in felmero.KOTELEZO[:3]}
        self.assertEqual(felmero.teljesseg_szazalek(allapotok), 25)

    def test_nem_kotelezo_kesz_nem_szamit(self):
        self.assertEqual(felmero.teljesseg_szazalek({"UX": "Kész", "TD": "Kész", "KZ": "Kész"}), 0)

    def test_prioritas_lefedi_a_kodokat(self):
        self.assertEqual(sorted(felmero.PRIORITAS), sorted(felmero.KODOK))
        self.assertEqual(len(set(felmero.PRIORITAS)), len(felmero.PRIORITAS))

    def test_tizenket_kotelezo_elem(self):
        self.assertEqual(len(felmero.KOTELEZO), 12)

    def test_hianylista_prioritas_sorrendben(self):
        elemek = []
        for kod in felmero.KODOK:
            if kod in ("B1", "A1", "D3", "TD"):
                elemek.append(sor(kod, ertek="x", allapot="Hiányos", hiany_ok="nincs szó szerinti idézet egy kliens-üzenetből"))
            else:
                elemek.append(sor(kod, ertek="x", allapot="Kész", hiany_ok=""))
        h = felmero.hianylista(elemek, 1, "Interjú")
        kodok = [t["kod"] for t in h["hianyzik"]]
        self.assertEqual(kodok, ["B1", "A1", "D3", "TD"])
        self.assertEqual(kodok, [k for k in felmero.PRIORITAS if k in kodok])

    def test_hianylista_hianyzo_sor_is_megjelenik(self):
        h = felmero.hianylista([], 0, "Vázlat")
        self.assertEqual(h["hianyzik"][0]["kod"], felmero.PRIORITAS[0])
        self.assertEqual(h["hianyzik"][0]["allapot"], "Hiányzik")

    def test_bekuldheto_ha_minden_kesz(self):
        elemek = [sor(k, ertek="x", allapot="Kész", hiany_ok="") for k in felmero.KODOK]
        h = felmero.hianylista(elemek, 1, "Interjú")
        self.assertTrue(h["bekuldheto"])
        self.assertEqual(h["akadalyok"], [])
        self.assertEqual(h["szazalek"], 100)

    def test_nincs_osszefoglalo_akadaly(self):
        elemek = [sor(k, ertek="x", allapot="Kész", hiany_ok="") for k in felmero.KODOK]
        h = felmero.hianylista(elemek, 0, "Interjú")
        self.assertFalse(h["bekuldheto"])
        self.assertIn("nincs összefoglaló", h["akadalyok"])

    def test_rossz_allapot_akadaly(self):
        elemek = [sor(k, ertek="x", allapot="Kész", hiany_ok="") for k in felmero.KODOK]
        h = felmero.hianylista(elemek, 1, "Bírálatra vár")
        self.assertIn("állapot: Bírálatra vár", h["akadalyok"])

    def test_hianyos_kotelezo_kodok_prioritas_sorrendben(self):
        h = felmero.hianylista([], 1, "Interjú")
        self.assertTrue(h["akadalyok"][0].startswith("hiányzó kötelező elem: B1, B2, A1"))


class Szamol(unittest.TestCase):
    def test_idezet_kesz_elemet_csinal(self):
        elemek = [sor("B1", ertek="Kézi számolás.")]
        biz = [{"elem": "B1", "idezet": "kézi számolás, minden nap"}]
        uzen = [uzenet("U-7", 7, "Most kézi számolás, minden nap, és tudom.")]
        el, b, szazalek = felmero.szamol(elemek, biz, uzen)
        self.assertEqual(el[0]["allapot"], "Kész")
        self.assertEqual(b[0]["ervenyes"], 1)
        self.assertEqual((b[0]["uzenet"], b[0]["uzenet_sorszam"]), ("U-7", 7))
        self.assertEqual(szazalek, 8)

    def test_rossz_idezet_hianyos_marad(self):
        elemek = [sor("B1", ertek="Kézi számolás.")]
        biz = [{"elem": "B1", "idezet": "ez nincs az üzenetekben"}]
        uzen = [uzenet("U-7", 7, "Most kézi számolás, minden nap, és tudom.")]
        el, b, _ = felmero.szamol(elemek, biz, uzen)
        self.assertEqual(el[0]["allapot"], "Hiányos")
        self.assertEqual(b[0]["ervenyes"], 0)

    def test_bizonyitek_uzenethez_kotott(self):
        elemek = [sor("B1", ertek="Kézi számolás.")]
        biz = [{"elem": "B1", "idezet": "kézi számolás, minden nap", "uzenet": "U-9"}]
        uzen = [uzenet("U-7", 7, "Most kézi számolás, minden nap, és tudom.")]
        _, b, _ = felmero.szamol(elemek, biz, uzen)
        self.assertEqual(b[0]["ervenyes"], 0)

    def test_szamol_nem_modositja_a_bemenetet(self):
        elemek = [sor("B1", ertek="x")]
        felmero.szamol(elemek, [], [])
        self.assertEqual(elemek[0]["allapot"] if "allapot" in elemek[0] else None, None)


class Egyeb(unittest.TestCase):
    def test_url_ervenyesseg(self):
        self.assertTrue(felmero.url_ervenyes("https://atomic.exarlabs.com"))
        self.assertTrue(felmero.url_ervenyes("http://localhost:8000"))
        self.assertTrue(felmero.url_ervenyes("http://127.0.0.1"))
        self.assertTrue(felmero.url_ervenyes("http://app.localhost"))
        self.assertFalse(felmero.url_ervenyes("http://example.com"))
        self.assertFalse(felmero.url_ervenyes("ftp://localhost"))
        self.assertFalse(felmero.url_ervenyes("nem url"))

    def test_belepes_logged_in_es_no_app_is_sikeres(self):
        # Demó, Website User fiók: a Frappe "No App" üzenettel válaszol sikeres bejelentkezésnél.
        self.assertTrue(felmero.belepes_sikeres({"message": "Logged In", "full_name": "X"}))
        self.assertTrue(felmero.belepes_sikeres({"message": "No App", "full_name": "X"}))

    def test_belepes_mas_valasz_sikertelen(self):
        self.assertFalse(felmero.belepes_sikeres({"message": "Invalid login credentials"}))
        self.assertFalse(felmero.belepes_sikeres({}))
        self.assertFalse(felmero.belepes_sikeres(None))

    def test_hibakod_kiolvasas(self):
        self.assertEqual(felmero.hibakod_kiolvas("[FELMERO_ALLAPOT] Az állapot nem engedi."), "FELMERO_ALLAPOT")
        self.assertEqual(felmero.hibakod_kiolvas("valami más"), "ISMERETLEN")

    def test_titok_kiszurese(self):
        szoveg = "hiba: jelszo=titkos-ertek-123 vege"
        self.assertNotIn("titkos-ertek-123", felmero.szurj(szoveg, ["titkos-ertek-123"]))

    def test_konfig_600_as_fajlt_es_700_as_mappat_ir(self):
        with tempfile.TemporaryDirectory() as tmp:
            utvonal = os.path.join(tmp, "felmero", "config.json")
            felmero.config_mentes(utvonal, {"url": "https://example.org", "user": "u"})
            self.assertEqual(stat.S_IMODE(os.stat(utvonal).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(utvonal)).st_mode), 0o700)

    def test_csak_stdlib_import(self):
        import ast
        allowed = {"argparse", "datetime", "getpass", "http", "json", "mimetypes", "os", "re", "stat",
                   "sys", "time", "unicodedata", "urllib", "uuid", "hashlib", "pathlib", "shutil", "platform", "secrets"}
        fa = ast.parse(CLI_UTVONAL.read_text(encoding="utf-8"))
        nevek = set()
        for csomo in ast.walk(fa):
            if isinstance(csomo, ast.Import):
                nevek.update(a.name.split(".")[0] for a in csomo.names)
            elif isinstance(csomo, ast.ImportFrom) and csomo.module:
                nevek.add(csomo.module.split(".")[0])
        self.assertTrue(nevek <= allowed, nevek - allowed)

    def test_erp_plan_config_nyer_a_regi_valtozon(self):
        regi = os.environ.get("FELMERO_CONFIG")
        uj = os.environ.get("ERP_PLAN_CONFIG")
        try:
            os.environ["FELMERO_CONFIG"] = "/tmp/regi.json"
            os.environ["ERP_PLAN_CONFIG"] = "/tmp/uj.json"
            self.assertEqual(felmero.config_utvonal(), "/tmp/uj.json")
            del os.environ["ERP_PLAN_CONFIG"]
            self.assertEqual(felmero.config_utvonal(), "/tmp/regi.json")
        finally:
            for kulcs, ertek in (("FELMERO_CONFIG", regi), ("ERP_PLAN_CONFIG", uj)):
                if ertek is None:
                    os.environ.pop(kulcs, None)
                else:
                    os.environ[kulcs] = ertek


if __name__ == "__main__":
    unittest.main()
