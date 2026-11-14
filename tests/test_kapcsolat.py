"""A kapcsolat (4.5) és a paros-allapot (4.7) tesztjei: a teendő-döntés tiszta függvény, a parancs hamis szerver ellen."""
import importlib.util
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from tests.hamis_szerver import CEG, FELHASZNALO, JELSZO, HamisSzerver
from tests.test_parancsok import CliTeszt

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "skills" / "erp-plan" / "erp_plan.py"

spec = importlib.util.spec_from_file_location("erp_plan", CLI)
erp_plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(erp_plan)

KULCS = "hamis-kulcs-7731"
TITOK = "hamis-titok-9d2c8e41f0"
ALAP_LEPESEK = {"BEALLITAS": True, "URL": True, "HALOZAT": True, "BELEPES": True, "SZERVEZET": True,
                "IRHAT": True, "API_VERZIO": True}


def lepesek(**felulir):
    d = dict(ALAP_LEPESEK)
    d.update({k: v for k, v in felulir.items()})
    return d


class TeendoDontes(unittest.TestCase):
    """A teendo-választás tiszta függvénye: minden ága egy eset."""

    def test_teendo_alap_probe_eles(self):
        self.assertEqual(erp_plan.teendo_valaszt(False, None, True, lepesek(), "eles"), "KULCS_IGENYLES")

    def test_teendo_alap_probe_nincs_szolgaltatas(self):
        self.assertEqual(erp_plan.teendo_valaszt(False, None, True, lepesek(), "proba"), "HOZZAFERES_KERES")

    def test_teendo_url_halozat_hamis(self):
        self.assertEqual(erp_plan.teendo_valaszt(False, None, False, lepesek(HALOZAT=False), None), "HALOZAT_VARJ")

    def test_teendo_url_eles(self):
        self.assertEqual(erp_plan.teendo_valaszt(False, None, False, lepesek(), "eles"), "KULCS_IGENYLES")

    def test_teendo_url_proba(self):
        self.assertEqual(erp_plan.teendo_valaszt(False, None, False, lepesek(), "proba"), "BEALLIT")

    def test_teendo_cfg_url_hamis(self):
        self.assertEqual(erp_plan.teendo_valaszt(True, "proto", False, lepesek(URL=False, HALOZAT=False), "eles"),
                         "BEALLIT")

    def test_teendo_cfg_halozat_hamis(self):
        self.assertEqual(erp_plan.teendo_valaszt(True, "proto", True, lepesek(HALOZAT=False), "eles"), "HALOZAT_VARJ")

    def test_teendo_cfg_belepes_atomi_es_proto(self):
        h = lepesek(BELEPES=False, SZERVEZET=False, IRHAT=False, API_VERZIO=False)
        self.assertEqual(erp_plan.teendo_valaszt(True, "atomi", True, h, "eles"), "KULCS_IGENYLES")
        self.assertEqual(erp_plan.teendo_valaszt(True, "proto", True, h, "proba"), "BEALLIT")

    def test_teendo_cfg_szervezet_irhat_verzio_nincs(self):
        self.assertEqual(erp_plan.teendo_valaszt(True, "proto", True, lepesek(SZERVEZET=False), "proba"),
                         "HOZZAFERES_KERES")
        self.assertEqual(erp_plan.teendo_valaszt(True, "atomi", True, lepesek(IRHAT=False), "eles"), "CSAK_OLVASAS")
        self.assertEqual(erp_plan.teendo_valaszt(True, "atomi", True, lepesek(API_VERZIO=False), "eles"), "FRISSITS")
        self.assertEqual(erp_plan.teendo_valaszt(True, "atomi", True, lepesek(), "eles"), "NINCS")


class CsakEngedelyezett(unittest.TestCase):
    def test_engedelyezett_utvonalak(self):
        self.assertIn("/api/method/ping", erp_plan.PROTO_UTAK)
        self.assertIn("/api/method/atomi.felmero.api.szolgaltatas", erp_plan.PROTO_UTAK)
        self.assertIn("/api/method/ping", erp_plan.ATOMI_UTAK)
        self.assertTrue(any("/api/method/atomi.felmero.api.szolgaltatas".startswith(p) for p in erp_plan.ATOMI_UTAK))

    def test_atomi_adapter_nem_ernek_el_adatot(self):
        erp_plan.AKTIV_UTAK[0] = erp_plan.ATOMI_UTAK
        with self.assertRaises(erp_plan.FelmeroHiba) as ctx:
            erp_plan.Kliens("http://127.0.0.1:9").keres("GET", "/api/resource/Felmero Feature")
        self.assertEqual(ctx.exception.kod, "FELMERO_BELSO")
        erp_plan.AKTIV_UTAK[0] = erp_plan.PROTO_UTAK


class KapcsolatCli(CliTeszt):
    def setUp(self):
        super().setUp()
        self.szerver.szolgaltatas_el = False
        self.szerver.kulcsok = {KULCS: TITOK}
        self.konfig_hely = os.path.join(self.tmp, "nincs-ilyen", "config.json")
        self.env["ERP_PLAN_CONFIG"] = self.konfig_hely

    def proto_konfig(self, jelszo=JELSZO):
        with open(self.konfig, "w", encoding="utf-8") as f:
            json.dump({"url": self.szerver.url, "adapter": "proto", "user": FELHASZNALO, "jelszo": jelszo,
                       "ceg": ""}, f)
        os.chmod(self.konfig, 0o600)
        self.env["ERP_PLAN_CONFIG"] = self.konfig

    def atomi_konfig(self):
        with open(self.konfig, "w", encoding="utf-8") as f:
            json.dump({"url": self.szerver.url, "adapter": "atomi", "api_key": KULCS, "api_secret": TITOK,
                       "user": FELHASZNALO}, f)
        os.chmod(self.konfig, 0o600)
        self.env["ERP_PLAN_CONFIG"] = self.konfig

    def lepes(self, kimenet, kod):
        return next(s for s in kimenet["lepesek"] if s["kod"] == kod)

    def test_konfig_nelkul_is_fut(self):
        r = self.ep("kapcsolat", "--url", self.szerver.url)
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        kimenet = json.loads(r.stdout)
        self.assertFalse(self.lepes(kimenet, "BEALLITAS")["rendben"])
        self.assertEqual(kimenet["teendo"], "BEALLIT")
        self.assertEqual(kimenet["mod"], "proba")
        self.assertEqual(kimenet["adapter"], None)

    def test_kilepes_0_ha_nincs_teendo(self):
        self.proto_konfig()
        r = self.ep("kapcsolat")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        kimenet = json.loads(r.stdout)
        self.assertEqual(kimenet["teendo"], "NINCS")
        self.assertIsNone(kimenet["elso_akadaly"])
        self.assertEqual(kimenet["adapter"], "proto")

    def test_kilepes_6_hibas_jelszo(self):
        self.proto_konfig(jelszo="rossz-jelszo")
        r = self.ep("kapcsolat")
        self.assertEqual(r.returncode, 6)
        kimenet = json.loads(r.stdout)
        self.assertEqual(kimenet["elso_akadaly"], "BELEPES")
        self.assertEqual(kimenet["teendo"], "BEALLIT")

    def test_kimenet_nem_tartalmaz_titkot(self):
        self.proto_konfig(jelszo="titkos-jelszo-42")
        r = self.ep("kapcsolat")
        self.assertNotIn("titkos-jelszo-42", r.stdout + r.stderr)
        self.atomi_konfig()
        r = self.ep("kapcsolat")
        self.assertNotIn(TITOK, r.stdout + r.stderr)
        self.assertNotIn(KULCS, r.stdout + r.stderr)

    def test_atomi_belepes_token_fejleccel(self):
        self.atomi_konfig()
        r = self.ep("kapcsolat")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["adapter"], "atomi")
        self.assertEqual(self.szerver.utolso_auth, "token %s:%s" % (KULCS, TITOK))

    def test_szolgaltatas_eles_mod(self):
        self.szerver.szolgaltatas_el = True
        self.atomi_konfig()
        kimenet = json.loads(self.ep("kapcsolat").stdout)
        self.assertEqual(kimenet["mod"], "eles")

    def test_halozati_hiba_halozat_varj(self):
        r = self.ep("kapcsolat", "--url", "http://127.0.0.1:9")
        self.assertEqual(r.returncode, 6)
        self.assertEqual(json.loads(r.stdout)["teendo"], "HALOZAT_VARJ")


class ParosAllapot(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.env = dict(os.environ)
        self.env["HOME"] = self.home
        self.env.pop("ERP_PLAN_CONFIG", None)
        self.env.pop("FELMERO_CONFIG", None)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def futtat(self):
        r = subprocess.run([sys.executable, "-I", str(CLI), "paros-allapot"], env=self.env, capture_output=True,
                           text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def test_paros_allapot_ideiglenes_home_mal_nincs_telepitve(self):
        kimenet = self.futtat()
        self.assertFalse(kimenet["telepitve"])
        self.assertIsNone(kimenet["verzio"])
        self.assertFalse(kimenet["parancs"])
        self.assertEqual(kimenet["mappa"], "~/.paros-advisor")

    def test_paros_allapot_telepitve_verzioval(self):
        mappa = os.path.join(self.home, ".paros-advisor")
        os.makedirs(mappa)
        with open(os.path.join(mappa, "VERSION"), "w", encoding="utf-8") as f:
            f.write("0.21.0\n")
        parancs = os.path.join(self.home, ".claude", "commands")
        os.makedirs(parancs)
        with open(os.path.join(parancs, "paros.md"), "w", encoding="utf-8") as f:
            f.write("parancs\n")
        kimenet = self.futtat()
        self.assertTrue(kimenet["telepitve"])
        self.assertEqual(kimenet["verzio"], "0.21.0")
        self.assertTrue(kimenet["parancs"])
        self.assertIsInstance(kimenet["git"], bool)


if __name__ == "__main__":
    unittest.main()
