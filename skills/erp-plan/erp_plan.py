#!/usr/bin/env python3
"""erp_plan.py: a feature-felmérő kliens-CLI (csak szabványos könyvtár, Python 3.9+).

A CLI továbbít és érthetően jelent. A teljességet és az idézetek egyezését a
PLAN.md 4.8 szerint maga számolja (ugyanazzal a normalizálással). A két
háttér-adapter közül a `proto` a demó szabványos Frappe-API-ján dolgozik;
az `atomi` adapter egyelőre váz: minden parancsa "még nem elérhető" hibát ad.

Kimenet: JSON a szabványos kimeneten (`--szoveg` kapcsolóval rövid forma).
Kilépési kódok: 0 siker, 2 hibás használat, 3 nincs vagy hibás beállítás (és
401), 4 a szerver megtagadta, 5 hálózati hiba vagy időtúllépés.
"""
import argparse
import datetime
import getpass
import hashlib
import http.cookiejar
import json
import mimetypes
import os
import re
import stat
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid

VERSION = "0.2.0"
API_VERZIO = 1
USER_AGENT = "atomic-skills-erp-plan/0.2.0"

KILEP_SIKER, KILEP_HASZNALAT, KILEP_BEALLITAS, KILEP_MEGTAGADVA, KILEP_HALOZAT = 0, 2, 3, 4, 5

IDEZET_MIN, IDEZET_MAX = 8, 1000
UZENET_MAX = 20000
OSSZEFOGLALO_MAX = 20000
HATTERTUDAS_MAX = 200000
DOKUMENTUM_MAX = 25 * 1024 ** 2
IDEZET_DARAB_MAX = 10

# (kod, cim, kotelezo, mit_kell_tudni)
ELEMEK = [
    ("A1", "Ügyféloldali felelős", True, "Név és szerep: akié a probléma, és aki elfogadja az eredményt."),
    ("B1", "A probléma ma", True, "Ki csinálja ma, milyen gyakran, mennyi időbe, hibába vagy pénzbe kerül."),
    ("B2", "A megoldás", True, "Mit automatizálunk, mi lesz a kimenet, ki használja."),
    ("B3", "Ami nincs benne", True, "Legalább egy tétel, ami nem része a munkának."),
    ("B4", "Bemenetek és hozzáférések", True, "Milyen adat, melyik rendszer, milyen jogosultság, és ki adja meg."),
    ("C1", "Ideális kezdés", True, "Dátum vagy hét."),
    ("C2", "Ideális határidő", True, "Dátum; a kezdéstől 1-4 hét."),
    ("D1", "Elfogadási feltételek", True, "Soronként egy feltétel: megfigyelhető, igen vagy nem, van gazdája és tesztadata."),
    ("D2", "Kiinduló állapot", True, "A mai szám, amihez később mérünk, és a forrása."),
    ("D3", "Sikerkritérium", True, "Az üzleti hatás, amit a mérési időszak végén várunk."),
    ("D4", "Mérési időszak és mód", True, "30, 60 vagy 90 nap; ki méri, milyen adatból."),
    ("UZ", "Üzleti követelmények", True, "Szabályok, kivételek, érintettek, amit a megoldásnak tudnia kell."),
    ("UX", "Felület és használat", False, "Hol, milyen eszközön, milyen lépésekben használják."),
    ("TD", "Technikai adottságok", False, "Meglévő rendszerek, formátumok, korlátok."),
    ("KZ", "Kizárások", False, "Amit a fejlesztés kifejezetten nem érint."),
]
KODOK = [e[0] for e in ELEMEK]
KOTELEZO = [e[0] for e in ELEMEK if e[2]]
CIMEK = {e[0]: e[1] for e in ELEMEK}
MIT_KELL_TUDNI = {e[0]: e[3] for e in ELEMEK}
# A hiánylista sorrendje: a legjobban blokkoló elöl
PRIORITAS = ["B1", "B2", "A1", "B3", "B4", "D1", "D2", "D3", "D4", "C1", "C2", "UZ", "KZ", "UX", "TD"]
DATUMOS = ("C1", "C2")
MERESI_NAPOK = (30, 60, 90)

FEATURE_ALLAPOTOK = ("Vázlat", "Interjú", "Bírálatra vár", "Visszaküldve", "Elfogadva", "Lezárva")
KLIENS_IRHAT = ("Vázlat", "Interjú", "Visszaküldve")
KLIENS_UZENHET = ("Vázlat", "Interjú", "Visszaküldve", "Bírálatra vár")

SZOVEG_KITERJESZTES = ("md", "txt", "csv", "json")
KEP_KITERJESZTES = ("png", "jpg", "jpeg", "webp")
HANG_KITERJESZTES = ("m4a", "mp3", "wav", "ogg", "webm")
NEV_RE = re.compile(r"^(FP|FT|FA)-[0-9A-Za-z.]{1,20}$")
HIBAKOD_RE = re.compile(r"\[(FELMERO_[A-Z_]+)\]")

PROTO_UTAK = ("/api/resource/", "/api/method/login", "/api/method/logout", "/api/method/upload_file",
              "/api/method/frappe.sessions.get_csrf_token", "/private/files/", "/files/")
ALAP_HIBAKOD = {401: "FELMERO_BEJELENTKEZES", 403: "FELMERO_TILTOTT", 404: "FELMERO_NEM_TALALHATO",
                429: "FELMERO_NAPI_KORLAT"}


class FelmeroHiba(Exception):
    def __init__(self, kod, uzenet, kilepes, http_kod=None):
        super().__init__(uzenet)
        self.kod = kod
        self.uzenet = uzenet
        self.kilepes = kilepes
        self.http_kod = http_kod


# ---------------------------------------------------------------------------
# Tiszta függvények (egységtesztelve)
# ---------------------------------------------------------------------------

def normal(szoveg):
    s = unicodedata.normalize("NFC", szoveg or "")
    return " ".join(s.split())


def belepes_sikeres(valasz):
    # A Frappe a sikeres bejelentkezést "Logged In" üzenettel jelzi, a desk-hozzáférés nélküli
    # (Website User) fiókoknál viszont "No App" érkezik. A hibás jelszó HTTP 401, nem 200.
    return isinstance(valasz, dict) and valasz.get("message") in ("Logged In", "No App")


def idezet_formai_hiba(idezet):
    n = normal(idezet)
    if len(n) < IDEZET_MIN or len(n.split()) < 2:
        return "FELMERO_IDEZET_ROVID"
    if len(n) > IDEZET_MAX:
        return "FELMERO_HOSSZ"
    return None


def idezet_keres(idezet, uzenetek):
    """uzenetek: dict-ek (name, sorszam, szoveg). -> (name, sorszam) vagy None."""
    n = normal(idezet)
    if not n:
        return None
    for u in sorted(uzenetek, key=lambda u: u["sorszam"]):
        if n in normal(u.get("szoveg")):
            return u["name"], u["sorszam"]
    return None


def _datum(s):
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _egesz(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def elem_allapot(sor, ervenyes_db, c1_datum=None):
    """-> (allapot, okok). sor: az elem dict-je vagy None."""
    if not sor or not normal(sor.get("ertek")):
        return "Hiányzik", ["nincs kitöltve"]
    okok = []
    kod = sor.get("kod")
    if kod in DATUMOS and not sor.get("datum"):
        okok.append("nincs dátum")
    if kod == "C2":
        d2, d1 = _datum(sor.get("datum")), _datum(c1_datum)
        if d2 and d1 and d2 < d1:
            okok.append("a határidő a kezdés előtt van")
    if kod == "D4" and _egesz(sor.get("szam")) not in MERESI_NAPOK:
        okok.append("a mérési időszak 30, 60 vagy 90 nap legyen")
    if kod == "D2" and not normal(sor.get("kiegeszites")):
        okok.append("nincs megadva a baseline forrása")
    if sor.get("forras") != "mernok" and ervenyes_db == 0:
        okok.append("nincs szó szerinti idézet egy kliens-üzenetből")
    if sor.get("mernok_allapot") == "Pontosítandó":
        megj = normal(sor.get("mernok_megjegyzes"))
        okok.append("a mérnök pontosítást kér" + (": " + megj if megj else ""))
    return ("Kész", []) if not okok else ("Hiányos", okok)


def teljesseg_szazalek(allapotok):
    kesz = sum(1 for k in KOTELEZO if allapotok.get(k) == "Kész")
    return round(100 * kesz / len(KOTELEZO))


def szamol(elemek, bizonyitekok, uzenetek):
    """A PLAN.md 4.8.2 szerint: újraellenőrzi az idézeteket, beírja az elem-állapotokat
    és a teljességet. A bemenetet nem módosítja. -> (elemek, bizonyitekok, szazalek)"""
    biz_ki = []
    for b in bizonyitekok:
        b = dict(b)
        kandidatus = [u for u in uzenetek if u["name"] == b["uzenet"]] if b.get("uzenet") else uzenetek
        talalat = idezet_keres(b.get("idezet"), kandidatus)
        b["ervenyes"] = 1 if talalat else 0
        if talalat:
            b["uzenet"], b["uzenet_sorszam"] = talalat
        biz_ki.append(b)
    c1 = next((e.get("datum") for e in elemek if e.get("kod") == "C1"), None)
    el_ki = []
    for e in elemek:
        e = dict(e)
        db = sum(1 for b in biz_ki if b.get("elem") == e.get("kod") and b["ervenyes"])
        e["allapot"], okok = elem_allapot(e, db, c1)
        e["hiany_ok"] = "\n".join(okok)
        el_ki.append(e)
    return el_ki, biz_ki, teljesseg_szazalek({e["kod"]: e["allapot"] for e in el_ki})


def hianylista(elemek, osszefoglalo_db, allapot):
    """elemek: a szamol() kimenete. A PRIORITAS sorrendben adja a nem kész elemeket."""
    sorok = {e.get("kod"): e for e in elemek}
    allapot_kod, okok_kod = {}, {}
    for kod in KODOK:
        e = sorok.get(kod)
        if e is None:
            allapot_kod[kod] = "Hiányzik"
            okok_kod[kod] = ["nincs kitöltve"]
        else:
            allapot_kod[kod] = e.get("allapot") or "Hiányos"
            okok_kod[kod] = [o for o in (e.get("hiany_ok") or "").split("\n") if o]
    akadalyok = []
    hianyos_kotelezo = [k for k in PRIORITAS if k in KOTELEZO and allapot_kod[k] != "Kész"]
    if hianyos_kotelezo:
        akadalyok.append("hiányzó kötelező elem: " + ", ".join(hianyos_kotelezo))
    if osszefoglalo_db < 1:
        akadalyok.append("nincs összefoglaló")
    if allapot not in ("Interjú", "Visszaküldve"):
        akadalyok.append("állapot: " + str(allapot))
    return {
        "szazalek": teljesseg_szazalek(allapot_kod),
        "kesz": [k for k in PRIORITAS if allapot_kod[k] == "Kész"],
        "hianyzik": [{"kod": k, "cim": CIMEK[k], "kotelezo": k in KOTELEZO, "allapot": allapot_kod[k],
                      "okok": okok_kod[k], "mit_kell_tudni": MIT_KELL_TUDNI[k]}
                     for k in PRIORITAS if allapot_kod[k] != "Kész"],
        "bekuldheto": not akadalyok,
        "akadalyok": akadalyok,
    }


# ---------------------------------------------------------------------------
# Munkák listája és a következő lépés (4.1, 4.2)
# ---------------------------------------------------------------------------

ALLAPOT_CSOPORT = {
    "Vázlat": ("nyitott", "nalad"), "Interjú": ("nyitott", "nalad"),
    "Visszaküldve": ("nyitott", "nalad"), "Bírálatra vár": ("nyitott", "mernoknel"),
    "Elfogadva": ("lezart", "lezarva"), "Lezárva": ("lezart", "lezarva"),
}
KINEL_SORREND = {"nalad": 0, "mernoknel": 1, "lezarva": 2}


def munka_sor(feature, projekt):
    csoport, kinel = ALLAPOT_CSOPORT.get(feature.get("allapot"), ("nyitott", "nalad"))
    projekt = projekt or {}
    return {"feature": feature["name"], "cim": feature.get("cim"),
            "projekt": feature.get("projekt") or projekt.get("name"), "projekt_cim": projekt.get("cim"),
            "allapot": feature.get("allapot"), "csoport": csoport, "kinel": kinel,
            "teljesseg_szazalek": feature.get("teljesseg_szazalek") or 0,
            "utolso_uzenet": feature.get("utolso_uzenet"), "modified": feature.get("modified")}


def munkak_rendez(sorok, szuro="nyitott"):
    """Nalad, mernoknel, lezarva sorrendben; csoporton belül a legfrissebb elöl."""
    valasztott = [s for s in sorok if szuro == "mind" or s["csoport"] == szuro]
    valasztott = sorted(valasztott, key=lambda s: s.get("modified") or "", reverse=True)
    return sorted(valasztott, key=lambda s: KINEL_SORREND[s["kinel"]])


def munkak_db(sorok):
    nyitott = sum(1 for s in sorok if s["csoport"] == "nyitott")
    return {"nyitott": nyitott, "lezart": len(sorok) - nyitott, "mind": len(sorok)}


def ellenoriz(kontextus, testverek, kimeno_db, ma):
    """A szabálymotor helye (INK-01 ... INK-19, P1-04). Most még nem talál semmit."""
    return []


def _valasz(feature, lepes, skill, szoveg, parancs=None, reszletek=None):
    return {"feature": feature, "lepes": lepes, "skill": skill, "szoveg": szoveg,
            "parancs": parancs, "reszletek": reszletek or {}}


def munka_lepes(m):
    """A munka szintű 12 szabály (4.2 tábla). Az első illeszkedő sor nyer."""
    f = m["feature"]
    hiba_db = sum(1 for t in m["talalatok"] if t["suly"] == "hiba")
    figyelem_db = sum(1 for t in m["talalatok"] if t["suly"] == "figyelem" and not t.get("elfogadva"))
    kotelezo = [h for h in m["hianylista"]["hianyzik"] if h["kotelezo"]]
    nem_kotelezo = [h for h in m["hianylista"]["hianyzik"]
                    if not h["kotelezo"] and h["kod"] not in m["kihagyott"]]
    frappe = m.get("frappe") or {}
    frappe_hianyzik = []
    if frappe.get("elerheto") and not frappe.get("kihagyva"):
        frappe_hianyzik = [t for t in frappe.get("temak", []) if t.get("allapot") == "Hiányzik"]

    if m["allapot"] in ("Elfogadva", "Lezárva"):
        return _valasz(f, "LEZART", "erp-plan-munkak",
                       "Ez a munka lezárult. Kérdezhetsz róla, vagy nyithatsz újat.",
                       reszletek={"allapot": m["allapot"]})
    if m["allapot"] == "Bírálatra vár":
        return _valasz(f, "VARAKOZAS", "erp-plan",
                       "Ez a munka a mérnöknél van. Üzenhetsz neki, vagy dolgozhatunk egy másikon.")
    if m["kimeno_db"] > 0:
        return _valasz(f, "KIMENO", "erp-plan-felmeres",
                       "%d üzeneted még nincs fent: töltsük fel." % m["kimeno_db"],
                       parancs="kimeno " + f)
    if hiba_db:
        return _valasz(f, "ELLENTMONDAS", "erp-plan-ellenorzes",
                       "%d ellentmondást találtam a leírásban: tisztázzuk." % hiba_db)
    if m["kliens_uzenet_db"] == 0:
        return _valasz(f, "SZABAD_MESE", "erp-plan-felmeres",
                       "Meséld el, mi a gond ma, és mit szeretnél helyette.")
    if m["allapot"] == "Visszaküldve" and m["pontositando"]:
        elso = m["pontositando"][0]
        return _valasz(f, "PONTOSITAS", "erp-plan-felmeres",
                       "A mérnök pontosítást kért: %s." % elso["cim"],
                       reszletek={"kod": elso["kod"], "megjegyzes": elso.get("megjegyzes") or "",
                                  "visszakuldes_indoka": m.get("visszakuldes_indoka")})
    if kotelezo:
        h = kotelezo[0]
        return _valasz(f, "KERDES", "erp-plan-felmeres", "A következő kérdés: %s." % h["cim"],
                       reszletek={"kod": h["kod"], "cim": h["cim"], "mit_kell_tudni": h["mit_kell_tudni"],
                                  "okok": h["okok"]})
    if nem_kotelezo:
        h = nem_kotelezo[0]
        return _valasz(f, "KERDES_NEM_KOTELEZO", "erp-plan-felmeres",
                       "Még egy nem kötelező pont: %s. Kihagyható." % h["cim"],
                       reszletek={"kod": h["kod"], "cim": h["cim"], "mit_kell_tudni": h["mit_kell_tudni"],
                                  "okok": h["okok"]})
    if frappe_hianyzik:
        t = frappe_hianyzik[0]
        return _valasz(f, "FRAPPE", "erp-plan-frappe",
                       "Jöhetnek a részletes kérdések, hogy a mérnök fejlesztésre kész leírást kapjon: %s." % t["cim"],
                       reszletek={"tema": t["kod"], "tema_cim": t["cim"]})
    if figyelem_db:
        return _valasz(f, "FIGYELEM", "erp-plan-ellenorzes",
                       "%d dolgot érdemes még tisztázni beküldés előtt." % figyelem_db)
    if m["osszefoglalo_db"] == 0 or m.get("ink07"):
        return _valasz(f, "OSSZEFOGLALO", "erp-plan-felmeres", "Írjunk friss összefoglalót.")
    return _valasz(f, "BEKULDES", "erp-plan-felmeres",
                   "Minden megvan: felolvasom az összefoglalót, és ha jó, beküldhetjük.")


def kapcsolodas_oka(h):
    if h.kod == "FELMERO_BEJELENTKEZES":
        return "belepes"
    if h.kilepes == KILEP_HALOZAT:
        return "halozat"
    return "nincs_beallitas"


def kovetkezo_lepes(adat):
    """Tiszta függvény: a már összegyűjtött állapotból egyetlen javaslat (4.2)."""
    if adat.get("kapcsolodas"):
        return _valasz(None, "KAPCSOLODAS", "erp-plan-kapcsolat", "Előbb kapcsolódjunk az EXAR ERP-hez.",
                       reszletek={"ok": adat["kapcsolodas"]})
    if adat.get("feature"):
        return munka_lepes(adat["munka"])
    if adat.get("aktiv_projekt_db", 0) == 0:
        return _valasz(None, "UJ_PROJEKT", "erp-plan-munkak", "Még nincs projekted: nyissuk meg az elsőt.")
    if adat.get("munka"):
        r = munka_lepes(adat["munka"])
        r["reszletek"]["tovabbi_nyitott"] = adat.get("tovabbi_nyitott", 0)
        return r
    if adat.get("mernoknel_db", 0) > 0:
        return _valasz(None, "VARAKOZAS", "erp-plan",
                       "%d munkád a mérnöknél van. Közben nyithatsz újat, vagy kérdezhetsz." % adat["mernoknel_db"])
    return _valasz(None, "UJ_MUNKA", "erp-plan-munkak", "Nincs nyitott munkád. Nyissunk egy újat?")


def hibakod_kiolvas(szoveg):
    m = HIBAKOD_RE.search(szoveg or "")
    return m.group(1) if m else "ISMERETLEN"


def url_ervenyes(url):
    try:
        p = urllib.parse.urlsplit(url or "")
    except ValueError:
        return False
    host = p.hostname or ""
    if p.scheme == "https":
        return bool(host)
    if p.scheme == "http":
        return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")
    return False


def szurj(szoveg, titkok):
    for t in titkok:
        if t:
            szoveg = szoveg.replace(t, "***")
    return szoveg


def szerver_hiba(torzs):
    """-> (kod, uzenet) a Frappe hibatörzséből. A kód a szöveges mezőkből jön."""
    szovegek = []
    try:
        j = json.loads(torzs)
    except (ValueError, TypeError):
        j = None
    if isinstance(j, dict):
        v = j.get("_server_messages")
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                v = [v]
        for elem in (v if isinstance(v, list) else []):
            if isinstance(elem, str):
                try:
                    elem = json.loads(elem)
                except ValueError:
                    pass
            szovegek.append(str(elem.get("message", "")) if isinstance(elem, dict) else str(elem))
        for kulcs in ("exception", "message"):
            if j.get(kulcs):
                szovegek.append(str(j[kulcs]))
    else:
        szovegek.append(torzs or "")
    teljes = "\n".join(szovegek)
    return hibakod_kiolvas(teljes), teljes.strip()[:500]


def http_kilepes(http_kod):
    if http_kod == 401:
        return KILEP_BEALLITAS
    if http_kod >= 500:
        return KILEP_HALOZAT
    return KILEP_MEGTAGADVA


def json_be(torzs):
    try:
        return json.loads(torzs)
    except (ValueError, TypeError):
        raise FelmeroHiba("FELMERO_VALASZ", "Érvénytelen válasz a szervertől.", KILEP_HALOZAT)


# ---------------------------------------------------------------------------
# Konfiguráció és helyi fájlok
# ---------------------------------------------------------------------------

def config_utvonal():
    return os.environ.get("ERP_PLAN_CONFIG") or os.environ.get("FELMERO_CONFIG") or os.path.join(
        os.path.expanduser("~"), ".config", "felmero", "config.json")


def config_mentes(utvonal, adat):
    mappa = os.path.dirname(os.path.abspath(utvonal))
    os.makedirs(mappa, mode=0o700, exist_ok=True)
    os.chmod(mappa, 0o700)
    ideiglenes = utvonal + ".tmp"
    fd = os.open(ideiglenes, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(adat, f, ensure_ascii=False, indent=2)
    os.chmod(ideiglenes, 0o600)
    os.replace(ideiglenes, utvonal)


def config_betoltes(utvonal):
    if not os.path.exists(utvonal):
        return {}
    if stat.S_IMODE(os.stat(utvonal).st_mode) & 0o077:
        print("figyelmeztetés: a beállító fájl jogai túl tágak, 0600-ra szűkítem.", file=sys.stderr)
        os.chmod(utvonal, 0o600)
    try:
        with open(utvonal, encoding="utf-8") as f:
            return json.load(f)
    except ValueError:
        raise FelmeroHiba("FELMERO_BEALLITAS", "A beállító fájl sérült. Futtasd újra: erp_plan.py beallit --url <cím>", KILEP_BEALLITAS)


def kell_cfg():
    cfg = config_betoltes(config_utvonal())
    for kulcs, env in (("url", "FELMERO_URL"), ("user", "FELMERO_USER"), ("jelszo", "FELMERO_PASSWORD"),
                       ("api_key", "FELMERO_API_KEY"), ("api_secret", "FELMERO_API_SECRET"),
                       ("adapter", "FELMERO_ADAPTER")):
        if os.environ.get(env):
            cfg[kulcs] = os.environ[env]
    if not cfg.get("url"):
        raise FelmeroHiba("FELMERO_NINCS_BEALLITAS", "Nincs beállítás. Futtasd: erp_plan.py beallit --url <cím>", KILEP_BEALLITAS)
    if not url_ervenyes(cfg["url"]):
        raise FelmeroHiba("FELMERO_URL", "Az URL csak https lehet (kivétel: localhost).", KILEP_BEALLITAS)
    cfg.setdefault("adapter", "proto")
    return cfg


def kimeno_mappa():
    return os.path.join(os.path.dirname(os.path.abspath(config_utvonal())), "kimeno")


def kimeno_utvonal(feature):
    return os.path.join(kimeno_mappa(), feature + ".jsonl")


def kimeno_olvas(feature):
    utvonal = kimeno_utvonal(feature)
    if not os.path.exists(utvonal):
        return []
    with open(utvonal, encoding="utf-8") as f:
        return [json.loads(sor) for sor in f if sor.strip()]


def kimeno_iras(feature, tetelek):
    os.makedirs(kimeno_mappa(), mode=0o700, exist_ok=True)
    utvonal = kimeno_utvonal(feature)
    tmp = utvonal + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for t in tetelek:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, utvonal)


def helyi_utvonal(feature):
    return os.path.join(os.path.dirname(os.path.abspath(config_utvonal())), "helyi", feature + ".json")


def helyi_olvas(feature):
    utvonal = helyi_utvonal(feature)
    if not os.path.exists(utvonal):
        return {"elfogadott": [], "kihagyott": []}
    with open(utvonal, encoding="utf-8") as f:
        adat = json.load(f)
    return {"elfogadott": list(adat.get("elfogadott", [])), "kihagyott": list(adat.get("kihagyott", []))}


def helyi_iras(feature, adat):
    utvonal = helyi_utvonal(feature)
    mappa = os.path.dirname(utvonal)
    os.makedirs(mappa, mode=0o700, exist_ok=True)
    os.chmod(mappa, 0o700)
    ideiglenes = utvonal + ".tmp"
    fd = os.open(ideiglenes, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(adat, f, ensure_ascii=False, indent=2)
    os.chmod(ideiglenes, 0o600)
    os.replace(ideiglenes, utvonal)


def beolvas(utvonal):
    if not utvonal or not os.path.isfile(utvonal):
        raise FelmeroHiba("FELMERO_NINCS_FAJL", "A megadott fájl nem található: " + str(utvonal), KILEP_HASZNALAT)
    with open(utvonal, encoding="utf-8") as f:
        return f.read()


def nev_tipus(minta):
    def ellenoriz(ertek):
        if not NEV_RE.match(ertek) or not ertek.startswith(minta + "-"):
            raise argparse.ArgumentTypeError("érvénytelen azonosító: " + minta + "-… alakot várok")
        return ertek
    return ellenoriz


def most():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# HTTP réteg: egy helyen, az adapter útvonal-előtagjaival
# ---------------------------------------------------------------------------

AKTIV_UTAK = [PROTO_UTAK]


class Kliens:
    def __init__(self, url, idotullepes=30):
        self.url = url.rstrip("/")
        self.idotullepes = idotullepes
        self.jar = http.cookiejar.CookieJar()
        self.nyito = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = None
        self.titkok = []

    def keres(self, metodus, ut, adat=None, nyers=None, tipus=None):
        ut_resz = ut.split("?", 1)[0]
        if not any(ut_resz.startswith(p) for p in AKTIV_UTAK[0]):
            raise FelmeroHiba("FELMERO_BELSO", "Nem engedélyezett végpont.", KILEP_HASZNALAT)
        fej = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        torzs = None
        if nyers is not None:
            torzs = nyers
            fej["Content-Type"] = tipus
        elif adat is not None:
            torzs = json.dumps(adat, ensure_ascii=False).encode("utf-8")
            fej["Content-Type"] = "application/json"
        if metodus != "GET" and self.csrf:
            fej["X-Frappe-CSRF-Token"] = self.csrf
        req = urllib.request.Request(self.url + ut, data=torzs, method=metodus, headers=fej)
        try:
            with self.nyito.open(req, timeout=self.idotullepes) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 403:
                # A szerver szövege nem megy tovább: a hiba kimondhatná, mely cég adatait nem látod.
                raise FelmeroHiba("FELMERO_TILTOTT", "Ehhez nincs hozzáférésed, vagy nem létezik.",
                                  KILEP_MEGTAGADVA, 403)
            torzs_hiba = e.read().decode("utf-8", "replace")
            kod, uzenet = szerver_hiba(torzs_hiba)
            if kod == "ISMERETLEN":
                kod = ALAP_HIBAKOD.get(e.code, "ISMERETLEN")
            raise FelmeroHiba(kod, szurj(uzenet or "A szerver hibát jelzett.", self.titkok),
                              http_kilepes(e.code), e.code)
        except (urllib.error.URLError, OSError):
            raise FelmeroHiba("FELMERO_HALOZAT", "Hálózati hiba vagy időtúllépés. Később próbáld újra.", KILEP_HALOZAT)


def multipart(mezok, fajl_nev, bajt, mime):
    hatar = uuid.uuid4().hex
    reszek = []
    for k, v in mezok.items():
        reszek.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (hatar, k, v)).encode("utf-8"))
    tiszta = fajl_nev.replace("\"", "")
    reszek.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                   "Content-Type: %s\r\n\r\n" % (hatar, tiszta, mime)).encode("utf-8"))
    reszek.append(bajt + b"\r\n")
    reszek.append(("--%s--\r\n" % hatar).encode("utf-8"))
    return b"".join(reszek), "multipart/form-data; boundary=" + hatar


# ---------------------------------------------------------------------------
# Proto adapter: a demó szabványos Frappe-API-ja, jelszavas munkamenettel
# ---------------------------------------------------------------------------

class Proto:
    def __init__(self, cfg):
        AKTIV_UTAK[0] = PROTO_UTAK
        self.cfg = cfg
        self.user = cfg["user"]
        self.k = Kliens(cfg["url"])
        self.k.titkok = [cfg.get("jelszo", ""), cfg.get("api_secret", "")]
        t = self.k.keres("POST", "/api/method/login", {"usr": self.user, "pwd": cfg["jelszo"]})
        j = json_be(t)
        if not belepes_sikeres(j):
            raise FelmeroHiba("FELMERO_BEJELENTKEZES", "A bejelentkezés nem sikerült.", KILEP_BEALLITAS)
        self.nev = j.get("full_name") or self.user
        try:
            self.k.csrf = json_be(self.k.keres("GET", "/api/method/frappe.sessions.get_csrf_token")).get("message")
        except FelmeroHiba:
            self.k.csrf = None

    def lista(self, dt, mezok, szurok=None, rendezes=None, limit=100):
        q = {"fields": json.dumps(mezok), "limit_page_length": str(limit)}
        if szurok:
            q["filters"] = json.dumps(szurok)
        if rendezes:
            q["order_by"] = rendezes
        return json_be(self.k.keres("GET", "/api/resource/" + urllib.parse.quote(dt) + "?" + urllib.parse.urlencode(q))).get("data", [])

    def egy(self, dt, nev):
        return json_be(self.k.keres("GET", "/api/resource/%s/%s" % (urllib.parse.quote(dt), urllib.parse.quote(nev))))["data"]

    def uj(self, dt, adat):
        return json_be(self.k.keres("POST", "/api/resource/" + urllib.parse.quote(dt), dict(adat, doctype=dt)))["data"]

    def frissit(self, dt, nev, adat):
        return json_be(self.k.keres("PUT", "/api/resource/%s/%s" % (urllib.parse.quote(dt), urllib.parse.quote(nev)), adat))["data"]

    def feltolt_bajt(self, dt, docname, fajl_nev, bajt, mime):
        torzs, ct = multipart({"is_private": "1", "doctype": dt, "docname": docname}, fajl_nev, bajt, mime)
        return json_be(self.k.keres("POST", "/api/method/upload_file", nyers=torzs, tipus=ct))["message"]

    def fajl_letolt(self, file_url):
        return self.k.keres("GET", file_url)

    def szervezetek(self):
        try:
            sorok = self.lista("User Permission", ["for_value"],
                               [["user", "=", self.user], ["allow", "=", "CRM Organization"]], limit=20)
            ert = [s["for_value"] for s in sorok]
        except FelmeroHiba:
            ert = []
        if not ert and self.cfg.get("ceg"):
            ert = [self.cfg["ceg"]]
        return ert

    def szervezet(self, ceg=None):
        if ceg:
            return ceg
        ert = self.szervezetek()
        if len(ert) == 1:
            return ert[0]
        raise FelmeroHiba("FELMERO_CEG_NEM", "Nem állapítható meg a cég. Add meg a --ceg kapcsolóval.", KILEP_HASZNALAT)

    def whoami(self):
        return {"felhasznalo": self.user, "nev": self.nev, "adapter": "proto", "api_verzio": API_VERZIO,
                "mod": "ugyfel", "irhat": True, "szervezetek": self.szervezetek()}

    def projektek(self):
        return self.lista("Felmero Projekt", ["name", "cim", "crm_organization", "allapot", "modified"], rendezes="modified desc")

    def munka_lista(self, projekt):
        return self.lista("Felmero Feature", ["name", "cim", "projekt", "allapot", "teljesseg_szazalek",
                                              "utolso_uzenet", "modified"],
                          [["projekt", "=", projekt]], rendezes="modified desc")

    def featurek(self, projekt):
        return self.lista("Felmero Feature", ["name", "cim", "allapot", "teljesseg_szazalek", "modified"],
                          [["projekt", "=", projekt]], rendezes="modified desc")

    def feature(self, nev):
        return self.egy("Felmero Feature", nev)

    def kliens_uzenetek(self, feature):
        return self.lista("Felmero Uzenet", ["name", "sorszam", "szoveg"],
                          [["feature", "=", feature], ["szerep", "=", "kliens"]], rendezes="sorszam asc", limit=1000)

    def uzenetek(self, feature, utan=0, limit=100):
        return self.lista("Felmero Uzenet", ["name", "sorszam", "szerep", "szerzo_nev", "forras", "szoveg", "fajl",
                                             "creation", "kliens_azonosito"],
                          [["feature", "=", feature], ["sorszam", ">", utan]], rendezes="sorszam asc", limit=limit)

    def uzenet_ir(self, feature, szerep, szoveg, kliens_azonosito, fajl=None):
        mar = self.lista("Felmero Uzenet", ["name", "sorszam"], [["kliens_azonosito", "=", kliens_azonosito]], limit=1)
        if mar:
            return {"name": mar[0]["name"], "sorszam": mar[0]["sorszam"], "mar_volt": True}
        utolso = self.lista("Felmero Uzenet", ["sorszam"], [["feature", "=", feature]], rendezes="sorszam desc", limit=1)
        sorszam = (utolso[0]["sorszam"] if utolso else 0) + 1
        f = self.feature(feature)
        d = self.uj("Felmero Uzenet", {"feature": feature, "sorszam": sorszam, "szerep": szerep, "forras": "szoveg",
                                        "szerzo": self.user, "szerzo_nev": self.nev, "projekt": f["projekt"],
                                        "crm_organization": f["crm_organization"], "szoveg": szoveg,
                                        "kliens_azonosito": kliens_azonosito, "fajl": fajl or None,
                                        "skill_verzio": VERSION})
        self.frissit("Felmero Feature", feature, {"uzenet_db": sorszam, "utolso_uzenet": most()})
        return {"name": d["name"], "sorszam": sorszam, "mar_volt": False}

    def osszefoglalok(self, feature):
        return self.lista("Felmero Osszefoglalo", ["name", "verzio", "szoveg", "uzenet_sorszamig", "creation"],
                          [["feature", "=", feature]], rendezes="verzio desc")

    def osszefoglalo_ir(self, f, szoveg):
        osz = self.osszefoglalok(f["name"])
        verzio = (osz[0]["verzio"] if osz else 0) + 1
        uz = self.lista("Felmero Uzenet", ["sorszam"], [["feature", "=", f["name"]]], rendezes="sorszam desc", limit=1)
        d = self.uj("Felmero Osszefoglalo", {"feature": f["name"], "verzio": verzio, "szerep": "asszisztens",
                                              "szerzo": self.user, "szerzo_nev": self.nev, "projekt": f["projekt"],
                                              "crm_organization": f["crm_organization"],
                                              "uzenet_sorszamig": uz[0]["sorszam"] if uz else 0, "szoveg": szoveg})
        return {"name": d["name"], "verzio": verzio}

    def fajlok(self, szurok):
        return self.lista("Felmero Fajl", ["name", "fajl_nev", "tipus", "meret", "feature", "projekt",
                                           "elsodleges_forma", "atalakitas_allapot", "atiras_allapot", "creation"],
                          szurok, rendezes="creation desc")

    def fajl_file_url(self, file_nev):
        sorok = self.lista("File", ["file_url"], [["name", "=", file_nev]], limit=1)
        if not sorok:
            raise FelmeroHiba("FELMERO_NEM_TALALHATO", "A fájl nem található.", KILEP_MEGTAGADVA)
        return sorok[0]["file_url"]


class Atomi:
    """Váz: a későbbi atomi.felmero.api.* végpontok helye. Most minden parancs erre fut."""

    def __init__(self, cfg):
        self.cfg = cfg

    def __getattr__(self, nev):
        if nev.startswith("__"):
            raise AttributeError(nev)

        def nem_elerheto(*_a, **_k):
            raise FelmeroHiba("FELMERO_NEM_ELERHETO", "Ez a parancs még nem elérhető: az atomi adapter egyelőre váz.",
                              KILEP_HASZNALAT)
        return nem_elerheto


def adapter(cfg):
    if cfg["adapter"] == "proto":
        if not cfg.get("user") or not cfg.get("jelszo"):
            raise FelmeroHiba("FELMERO_NINCS_BEALLITAS", "Hiányzik a felhasználó vagy a jelszó. Futtasd újra: erp_plan.py beallit --url <cím>", KILEP_BEALLITAS)
        AKTIV_UTAK[0] = PROTO_UTAK
        return Proto(cfg)
    if cfg["adapter"] == "atomi":
        AKTIV_UTAK[0] = ("/api/method/atomi.felmero.api.",)
        return Atomi(cfg)
    raise FelmeroHiba("FELMERO_ADAPTER", "Ismeretlen adapter: " + str(cfg["adapter"]), KILEP_BEALLITAS)


# ---------------------------------------------------------------------------
# Üzleti szabályok a CLI-ben (proto: a szerver ezt még nem tudja)
# ---------------------------------------------------------------------------

def irhato_feature(f):
    if f.get("allapot") not in KLIENS_IRHAT:
        raise FelmeroHiba("FELMERO_ALLAPOT", "A feature állapota (%s) nem engedi a módosítást." % f.get("allapot"), KILEP_MEGTAGADVA)


def irhato_projekt(p):
    if p.get("allapot") != "Aktív":
        raise FelmeroHiba("FELMERO_ARCHIVALT", "A projekt archivált, nem módosítható.", KILEP_MEGTAGADVA)


def ertekeles(p, f):
    el, biz, _ = szamol_feature(p, f)
    osz = p.osszefoglalok(f["name"])
    return el, biz, hianylista(el, len(osz), f.get("allapot")), osz


def szamol_feature(p, f):
    el, biz, szazalek = szamol(f.get("elemek") or [], f.get("bizonyitekok") or [], p.kliens_uzenetek(f["name"]))
    return el, biz, szazalek


# ---------------------------------------------------------------------------
# Parancsok
# ---------------------------------------------------------------------------

def cmd_beallit(a):
    if not url_ervenyes(a.url):
        raise FelmeroHiba("FELMERO_URL", "Az URL csak https lehet (kivétel: localhost).", KILEP_HASZNALAT)
    cfg = {"url": a.url, "adapter": a.adapter, "letrehozva": most(), "ceg": a.ceg or ""}
    if a.adapter == "atomi":
        par = getpass.getpass("API-kulcs és titok, kettősponttal elválasztva (nem látszik): ")
        if ":" not in par:
            raise FelmeroHiba("FELMERO_FORMA", "A párt kulcs:titok alakban add meg.", KILEP_HASZNALAT)
        kulcs, titok = par.split(":", 1)
        cfg.update({"api_key": kulcs.strip(), "api_secret": titok.strip()})
        config_mentes(config_utvonal(), cfg)
        return {"rendben": False, "megjegyzes": "Az atomi adapter még nem ellenőrizhető; a beállítás mentve."}
    cfg["user"] = input("E-mail (felhasználónév): ").strip()
    cfg["jelszo"] = getpass.getpass("Jelszó (nem látszik): ")
    p = Proto(cfg)
    who = p.whoami()
    config_mentes(config_utvonal(), cfg)
    return {"rendben": True, "user": cfg["user"], "szervezetek": who["szervezetek"]}


def cmd_kivagyok(p, a):
    d = p.whoami()
    d["url"] = p.cfg["url"]
    return d


def cmd_hozzaferes(p, a):
    return [dict(pr, featurek=p.featurek(pr["name"])) for pr in p.projektek()]


def cmd_projektek(p, a):
    return p.projektek()


def cmd_projekt(p, a):
    pr = p.egy("Felmero Projekt", a.projekt)
    return {"projekt": pr, "featurek": p.featurek(a.projekt)}


def cmd_uj_projekt(p, a):
    if len(a.cim.strip()) == 0 or len(a.cim) > 140:
        raise FelmeroHiba("FELMERO_CIM", "A cím 1-140 karakter legyen.", KILEP_HASZNALAT)
    leiras = a.leiras or ""
    return p.uj("Felmero Projekt", {"cim": a.cim.strip(), "leiras": leiras, "crm_organization": p.szervezet(a.ceg),
                                    "allapot": "Aktív", "letrehozta": p.user, "atiras_nyelv": "hu"})


def cmd_projekt_frissit(p, a):
    pr = p.egy("Felmero Projekt", a.projekt)
    irhato_projekt(pr)
    mezok = {}
    if a.cim is not None:
        if not a.cim.strip() or len(a.cim) > 140:
            raise FelmeroHiba("FELMERO_CIM", "A cím 1-140 karakter legyen.", KILEP_HASZNALAT)
        mezok["cim"] = a.cim.strip()
    if a.leiras is not None:
        mezok["leiras"] = a.leiras
    if a.hattertudas_fajl:
        szoveg = beolvas(a.hattertudas_fajl)
        if len(szoveg) > HATTERTUDAS_MAX:
            raise FelmeroHiba("FELMERO_HOSSZ", "A háttértudás túl hosszú.", KILEP_HASZNALAT)
        mezok["hattertudas"] = szoveg
    if a.szojegyzek is not None:
        mezok["szojegyzek"] = a.szojegyzek
    if a.nyelv:
        mezok["atiras_nyelv"] = a.nyelv
    if not mezok:
        raise FelmeroHiba("FELMERO_NINCS_MEZO", "Nincs megadott módosítás.", KILEP_HASZNALAT)
    return p.frissit("Felmero Projekt", a.projekt, mezok)


def cmd_archival(p, a):
    p.egy("Felmero Projekt", a.projekt)
    return p.frissit("Felmero Projekt", a.projekt, {"allapot": "Archivált"})


def cmd_uj_feature(p, a):
    pr = p.egy("Felmero Projekt", a.projekt)
    irhato_projekt(pr)
    if not a.cim.strip() or len(a.cim) > 140:
        raise FelmeroHiba("FELMERO_CIM", "A cím 1-140 karakter legyen.", KILEP_HASZNALAT)
    return p.uj("Felmero Feature", {"cim": a.cim.strip(), "projekt": a.projekt, "crm_organization": pr["crm_organization"],
                                    "allapot": "Vázlat", "teljesseg_szazalek": 0, "letrehozta": p.user, "uzenet_db": 0})


def cmd_feature_frissit(p, a):
    f = p.feature(a.feature)
    if not a.cim.strip() or len(a.cim) > 140:
        raise FelmeroHiba("FELMERO_CIM", "A cím 1-140 karakter legyen.", KILEP_HASZNALAT)
    return p.frissit("Felmero Feature", f["name"], {"cim": a.cim.strip()})


def cmd_feature(p, a):
    return p.feature(a.feature)


def cmd_hiany(p, a):
    f = p.feature(a.feature)
    el, biz, h, osz = ertekeles(p, f)
    return h


def cmd_uzenetek(p, a):
    p.feature(a.feature)
    return p.uzenetek(a.feature, a.utan, a.limit)


def uzenet_kuld(p, f, tetelek):
    """tetelek: [{"id", "szerep", "szoveg", "fajl"?}]. Előbb a kimenő sorba ír, siker után kiveszi."""
    kuldott = []
    for t in tetelek:
        if t["szerep"] == "kliens" and f.get("allapot") not in KLIENS_UZENHET:
            raise FelmeroHiba("FELMERO_ALLAPOT", "A feature állapota (%s) nem engedi az üzenetet." % f.get("allapot"), KILEP_MEGTAGADVA)
        if len(t["szoveg"]) > UZENET_MAX or not t["szoveg"].strip():
            raise FelmeroHiba("FELMERO_URES_VAGY_HOSSZ", "Az üzenet üres vagy túl hosszú.", KILEP_HASZNALAT)
        eredmeny = p.uzenet_ir(f["name"], t["szerep"], t["szoveg"], t["id"], t.get("fajl"))
        kimeno_torol(f["name"], t["id"])
        if t["szerep"] == "kliens" and f.get("allapot") == "Vázlat":
            p.frissit("Felmero Feature", f["name"], {"allapot": "Interjú"})
            f["allapot"] = "Interjú"
        kuldott.append({"name": eredmeny["name"], "sorszam": eredmeny["sorszam"], "szerep": t["szerep"],
                        "mar_volt": eredmeny["mar_volt"]})
    return kuldott


def kimeno_torol(feature, azonosito):
    kepek = [t for t in kimeno_olvas(feature) if t["id"] != azonosito]
    kimeno_iras(feature, kepek)


def kimeno_hozzaad(feature, tetelek):
    meglevo = kimeno_olvas(feature)
    kimeno_iras(feature, meglevo + tetelek)


def cmd_par(p, a):
    f = p.feature(a.feature)
    kerdes = beolvas(a.kerdes_fajl)
    valasz = beolvas(a.valasz_fajl)
    tetelek = [{"id": uuid.uuid4().hex, "szerep": "asszisztens", "szoveg": kerdes},
               {"id": uuid.uuid4().hex, "szerep": "kliens", "szoveg": valasz}]
    kimeno_hozzaad(a.feature, tetelek)
    return {"kuldott": uzenet_kuld(p, f, tetelek)}


def cmd_uzenet(p, a):
    f = p.feature(a.feature)
    szoveg = beolvas(a.fajl)
    tetel = {"id": uuid.uuid4().hex, "szerep": a.szerep, "szoveg": szoveg}
    kimeno_hozzaad(a.feature, [tetel])
    return {"kuldott": uzenet_kuld(p, f, [tetel])}


def cmd_kimeno(p, a):
    f = p.feature(a.feature)
    tetelek = kimeno_olvas(a.feature)
    if not tetelek:
        return {"kuldott": [], "megjegyzes": "A kimenő sor üres."}
    return {"kuldott": uzenet_kuld(p, f, tetelek)}


def cmd_elem(p, a):
    f = p.feature(a.feature)
    pr = p.egy("Felmero Projekt", f["projekt"])
    irhato_projekt(pr)
    irhato_feature(f)
    kod = a.kod
    if kod not in KODOK:
        raise FelmeroHiba("FELMERO_ISMERETLEN_ELEM", "Ismeretlen elemkód: " + kod, KILEP_HASZNALAT)
    ertek = beolvas(a.ertek_fajl).strip()
    if not ertek or len(ertek) > UZENET_MAX:
        raise FelmeroHiba("FELMERO_URES", "Az érték nem lehet üres, és legfeljebb %d karakter lehet." % UZENET_MAX, KILEP_HASZNALAT)
    datum = None
    if a.datum:
        if kod not in DATUMOS:
            raise FelmeroHiba("FELMERO_ELEM_ADAT", "Dátum csak a C1 és C2 elemnél adható meg.", KILEP_HASZNALAT)
        if _datum(a.datum) is None:
            raise FelmeroHiba("FELMERO_ELEM_ADAT", "A dátum ÉÉÉÉ-HH-NN alakú legyen.", KILEP_HASZNALAT)
        datum = a.datum
    szam = None
    if a.szam is not None:
        if kod != "D4" or a.szam not in MERESI_NAPOK:
            raise FelmeroHiba("FELMERO_ELEM_ADAT", "A szám csak a D4 elemnél adható meg: 30, 60 vagy 90.", KILEP_HASZNALAT)
        szam = a.szam
    if a.kiegeszites and len(a.kiegeszites) > 140:
        raise FelmeroHiba("FELMERO_HOSSZ", "A kiegészítés legfeljebb 140 karakter.", KILEP_HASZNALAT)
    idezetek = a.idezet or []
    if len(idezetek) > IDEZET_DARAB_MAX:
        raise FelmeroHiba("FELMERO_HOSSZ", "Legfeljebb %d idézet adható meg." % IDEZET_DARAB_MAX, KILEP_HASZNALAT)
    for i in idezetek:
        hiba = idezet_formai_hiba(i)
        if hiba:
            raise FelmeroHiba(hiba, "Az idézet túl rövid vagy túl hosszú.", KILEP_HASZNALAT)
    uzen = p.kliens_uzenetek(f["name"])
    talalatok = []
    for i in idezetek:
        t = idezet_keres(i, uzen)
        if not t:
            raise FelmeroHiba("FELMERO_IDEZET_NINCS", "Az idézet nem egyezik egy kliens-üzenettel sem. Nem mentettem semmit.", KILEP_MEGTAGADVA)
        talalatok.append((i, t))

    elemek = [dict(e) for e in f.get("elemek") or []]
    regi = next((e for e in elemek if e.get("kod") == kod), None)
    if regi and regi.get("forras") == "mernok" and not (
            f.get("allapot") == "Visszaküldve" and regi.get("mernok_allapot") == "Pontosítandó"):
        raise FelmeroHiba("FELMERO_MERNOK_ELEM", "Ezt az elemet a mérnök már kiegészítette.", KILEP_MEGTAGADVA)
    uj_sor = {"kod": kod, "ertek": ertek, "datum": datum, "szam": szam, "kiegeszites": a.kiegeszites or "",
              "forras": "kliens"}
    if regi:
        if regi.get("name"):
            uj_sor["name"] = regi["name"]
        uj_sor["mernok_allapot"] = "" if regi.get("mernok_allapot") == "Pontosítandó" else regi.get("mernok_allapot", "")
        uj_sor["mernok_megjegyzes"] = regi.get("mernok_megjegyzes", "") if uj_sor["mernok_allapot"] else ""
    elemek = [e for e in elemek if e.get("kod") != kod] + [uj_sor]

    biz = [dict(b) for b in f.get("bizonyitekok") or []]
    for i, (nev, sorszam) in talalatok:
        n = normal(i)
        if any(b.get("elem") == kod and normal(b.get("idezet")) == n for b in biz):
            continue
        biz.append({"elem": kod, "idezet": i, "uzenet": nev, "uzenet_sorszam": sorszam, "ervenyes": 1,
                    "rogzitette": p.user})

    el, biz2, szazalek = szamol(elemek, biz, uzen)
    p.frissit("Felmero Feature", f["name"], {"elemek": el, "bizonyitekok": biz2, "teljesseg_szazalek": szazalek})
    f_uj = dict(f, elemek=el, bizonyitekok=biz2, teljesseg_szazalek=szazalek)
    _, _, h, _ = ertekeles(p, f_uj)
    uj_allapot = next(e for e in el if e["kod"] == kod)
    return {"elem": {"kod": kod, "allapot": uj_allapot["allapot"], "hiany_ok": uj_allapot["hiany_ok"]},
            "hianylista": h}


def munka_reszlet(p, f):
    uz = p.kliens_uzenetek(f["name"])
    el, biz, _ = szamol(f.get("elemek") or [], f.get("bizonyitekok") or [], uz)
    osz = p.osszefoglalok(f["name"])
    h = hianylista(el, len(osz), f.get("allapot"))
    kimeno_db = len(kimeno_olvas(f["name"]))
    talalatok = ellenoriz(dict(f, elemek=el, bizonyitekok=biz), [], kimeno_db, datetime.date.today())
    return {"feature": f["name"], "cim": f.get("cim"), "allapot": f.get("allapot"), "kimeno_db": kimeno_db,
            "kliens_uzenet_db": len(uz), "osszefoglalo_db": len(osz), "talalatok": talalatok,
            "ink07": any(t["szabaly"] == "INK-07" for t in talalatok), "hianylista": h,
            "kihagyott": helyi_olvas(f["name"])["kihagyott"],
            "pontositando": [{"kod": e["kod"], "cim": CIMEK.get(e["kod"], e["kod"]),
                              "megjegyzes": e.get("mernok_megjegyzes") or ""}
                             for e in el if e.get("mernok_allapot") == "Pontosítandó"],
            "visszakuldes_indoka": f.get("visszakuldes_indoka"), "frappe": None}


def kovetkezo_adat(p, feature):
    if feature:
        f = p.feature(feature)
        return {"kapcsolodas": None, "feature": feature, "munka": munka_reszlet(p, f)}
    projektek = p.projektek()
    sorok = []
    for pr in projektek:
        sorok += [munka_sor(f, pr) for f in p.munka_lista(pr["name"])]
    nalad = [s for s in munkak_rendez(sorok, "nyitott") if s["kinel"] == "nalad"]
    munka = munka_reszlet(p, p.feature(nalad[0]["feature"])) if nalad else None
    return {"kapcsolodas": None, "feature": None,
            "aktiv_projekt_db": sum(1 for pr in projektek if pr.get("allapot") == "Aktív"),
            "mernoknel_db": sum(1 for s in sorok if s["kinel"] == "mernoknel"),
            "munka": munka, "tovabbi_nyitott": len(nalad) - 1 if nalad else 0}


def kovetkezo_cli(a):
    if a.kihagy:
        if not a.feature:
            raise FelmeroHiba("FELMERO_ELEM_ADAT", "A kihagyáshoz munka kell: add meg a FT-azonosítót.", KILEP_HASZNALAT)
        if a.kihagy not in KODOK or a.kihagy in KOTELEZO:
            raise FelmeroHiba("FELMERO_ELEM_ADAT", "Csak nem kötelező elem hagyható ki.", KILEP_HASZNALAT)
        helyi = helyi_olvas(a.feature)
        if a.kihagy not in helyi["kihagyott"]:
            helyi["kihagyott"].append(a.kihagy)
        helyi_iras(a.feature, helyi)
    try:
        p = adapter(kell_cfg())
        adat = kovetkezo_adat(p, a.feature)
    except FelmeroHiba as h:
        if h.kilepes not in (KILEP_BEALLITAS, KILEP_HALOZAT):
            raise
        return kovetkezo_lepes({"kapcsolodas": kapcsolodas_oka(h)})
    return kovetkezo_lepes(adat)


def cmd_munkak(p, a):
    if a.projekt:
        projektek = [p.egy("Felmero Projekt", a.projekt)]
    else:
        projektek = p.projektek()
    sorok = []
    for pr in projektek:
        sorok += [munka_sor(f, pr) for f in p.munka_lista(pr["name"])]
    return {"allapot_szuro": a.allapot, "db": munkak_db(sorok), "munkak": munkak_rendez(sorok, a.allapot)}


def cmd_osszefoglalo(p, a):
    f = p.feature(a.feature)
    irhato_feature(f)
    szoveg = beolvas(a.fajl).strip()
    if not szoveg or len(szoveg) > OSSZEFOGLALO_MAX:
        raise FelmeroHiba("FELMERO_HOSSZ", "Az összefoglaló üres vagy túl hosszú.", KILEP_HASZNALAT)
    return p.osszefoglalo_ir(f, szoveg)


def cmd_osszefoglalok(p, a):
    p.feature(a.feature)
    return p.osszefoglalok(a.feature)


def cmd_hivatkozas(p, a):
    f = p.feature(a.feature)
    irhato_feature(f)
    if a.cel == f["name"]:
        raise FelmeroHiba("FELMERO_HIVATKOZAS", "Egy feature nem hivatkozhat önmagára.", KILEP_HASZNALAT)
    cel = p.feature(a.cel)
    if cel["crm_organization"] != f["crm_organization"]:
        raise FelmeroHiba("FELMERO_NEM_TALALHATO", "A hivatkozott feature nem található.", KILEP_MEGTAGADVA)
    hiv = [dict(h) for h in f.get("hivatkozasok") or []]
    if any(h.get("cel") == a.cel for h in hiv):
        raise FelmeroHiba("FELMERO_HIVATKOZAS", "Ez a hivatkozás már szerepel.", KILEP_HASZNALAT)
    hiv.append({"cel": a.cel, "megjegyzes": a.megjegyzes or ""})
    p.frissit("Felmero Feature", f["name"], {"hivatkozasok": hiv})
    return {"feature": f["name"], "cel": a.cel}


def cmd_hivatkozas_torol(p, a):
    f = p.feature(a.feature)
    irhato_feature(f)
    hiv = [dict(h) for h in f.get("hivatkozasok") or [] if h.get("cel") != a.cel]
    p.frissit("Felmero Feature", f["name"], {"hivatkozasok": hiv})
    return {"feature": f["name"], "cel": a.cel}


def cmd_feltolt(p, a):
    pr = p.egy("Felmero Projekt", a.projekt)
    irhato_projekt(pr)
    f = None
    if a.feature:
        f = p.feature(a.feature)
        if f["projekt"] != a.projekt:
            raise FelmeroHiba("FELMERO_NEM_TALALHATO", "A feature nem ebben a projektben van.", KILEP_MEGTAGADVA)
        irhato_feature(f)
    eredmeny = []
    for utvonal in a.fajlok:
        if not os.path.isfile(utvonal):
            raise FelmeroHiba("FELMERO_NINCS_FAJL", "A fájl nem található: " + utvonal, KILEP_HASZNALAT)
        nev = os.path.basename(utvonal)
        kit = nev.rsplit(".", 1)[-1].lower() if "." in nev else ""
        if kit in HANG_KITERJESZTES:
            raise FelmeroHiba("FELMERO_TIPUS", "A prototípusban nincs hangkezelés. Írásban folytassátok.", KILEP_HASZNALAT)
        if kit not in SZOVEG_KITERJESZTES + KEP_KITERJESZTES:
            raise FelmeroHiba("FELMERO_TIPUS", "Ez a típus nem tölthető fel. PDF vagy Office helyett Markdown-változatot tölts fel.", KILEP_HASZNALAT)
        meret = os.path.getsize(utvonal)
        if meret > DOKUMENTUM_MAX:
            raise FelmeroHiba("FELMERO_MERET", "A fájl nagyobb a megengedettnél (25 MB).", KILEP_HASZNALAT)
        with open(utvonal, "rb") as fh:
            bajt = fh.read()
        mime = "text/markdown" if kit == "md" else (mimetypes.guess_type(nev)[0] or "application/octet-stream")
        szoveges = kit in SZOVEG_KITERJESZTES
        dt, docname = ("Felmero Feature", f["name"]) if f else ("Felmero Projekt", a.projekt)
        # A demó a .md kiterjesztést nem fogadja el: a szerverre .md.txt néven megy, a nyilvántartásban az eredeti név marad.
        if kit == "md":
            feltolt_nev, feltolt_mime = nev + ".txt", "text/plain"
        else:
            feltolt_nev, feltolt_mime = nev, mime
        file_doc = p.feltolt_bajt(dt, docname, feltolt_nev, bajt, feltolt_mime)
        fa = p.uj("Felmero Fajl", {
            "fajl_nev": nev, "projekt": a.projekt, "feature": a.feature or "",
            "crm_organization": pr["crm_organization"], "tipus": "szoveg" if szoveges else "kep",
            "mime": mime, "meret": meret,
            "sha256": hashlib.sha256(bajt).hexdigest(), "feltoltotte": p.user, "feltolto_nev": p.nev,
            "elsodleges_forma": "markdown" if szoveges else "eredeti", "file": file_doc["name"],
            "markdown_file": file_doc["name"] if szoveges else None,
            "markdown_meret": meret if szoveges else None, "markdown_minoseg": "jó" if szoveges else "",
            "atalakitas_allapot": "Nem kell", "atiras_allapot": "Nem kell"})
        eredmeny.append({"fajl": fa["name"], "fajl_nev": nev, "tipus": fa["tipus"]})
    return eredmeny


def cmd_fajlok(p, a):
    if a.feature:
        p.feature(a.feature)
        return p.fajlok([["feature", "=", a.feature]])
    p.egy("Felmero Projekt", a.projekt)
    return p.fajlok([["projekt", "=", a.projekt]])


def cmd_fajl(p, a):
    return p.egy("Felmero Fajl", a.fajl)


def cmd_var(p, a):
    hatar = time.time() + a.ido
    while True:
        fa = p.egy("Felmero Fajl", a.fajl)
        if all(fa.get(k) in ("Nem kell", "Kész", "Hiba", "", None) for k in ("atalakitas_allapot", "atiras_allapot")):
            return {"fajl": fa["name"], "atalakitas": fa.get("atalakitas_allapot"), "atiras": fa.get("atiras_allapot")}
        if time.time() >= hatar:
            raise FelmeroHiba("FELMERO_IDOTULLEPES", "Az átalakítás még nem készült el.", KILEP_HALOZAT)
        time.sleep(5)


def cmd_letolt(p, a):
    fa = p.egy("Felmero Fajl", a.fajl)
    if a.forma == "markdown":
        file_nev = fa.get("markdown_file")
        if not file_nev:
            raise FelmeroHiba("FELMERO_NINCS_MARKDOWN", "Ehhez a fájlhoz nincs Markdown-változat.", KILEP_MEGTAGADVA)
    else:
        file_nev = fa.get("file")
    bajt = p.fajl_letolt(p.fajl_file_url(file_nev))
    if a.ki:
        # A letöltött dokumentum csak a felhasználónak olvasható (600), akármi volt a fájl korábban.
        fd = os.open(a.ki, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(bajt)
        os.chmod(a.ki, 0o600)
        return {"ki": a.ki, "meret": len(bajt), "fajl_nev": fa.get("fajl_nev")}
    sys.stdout.buffer.write(bajt)
    return None


def cmd_forma(p, a):
    fa = p.egy("Felmero Fajl", a.fajl)
    if a.elsodleges == "markdown" and not fa.get("markdown_file"):
        raise FelmeroHiba("FELMERO_NINCS_MARKDOWN", "Ehhez a fájlhoz nincs Markdown-változat.", KILEP_MEGTAGADVA)
    return p.frissit("Felmero Fajl", a.fajl, {"elsodleges_forma": a.elsodleges})


def cmd_kontextus(p, a):
    f = p.feature(a.feature)
    pr = p.egy("Felmero Projekt", f["projekt"])
    el, biz, h, osz = ertekeles(p, f)
    uz = p.uzenetek(a.feature, 0, 1000)
    utolso_n = uz[-a.utolso:] if a.utolso else uz
    hivatkozott = []
    for hv in f.get("hivatkozasok") or []:
        try:
            cf = p.feature(hv["cel"])
            hivatkozott.append({"feature": cf["name"], "cim": cf["cim"], "allapot": cf["allapot"],
                                "fajlok": p.fajlok([["feature", "=", cf["name"]]])})
        except FelmeroHiba:
            hivatkozott.append({"feature": hv["cel"], "nem_elerheto": True})
    adat = {
        "projekt": {"name": pr["name"], "cim": pr["cim"], "allapot": pr["allapot"], "hattertudas": pr.get("hattertudas")},
        "feature": {"name": f["name"], "cim": f["cim"], "allapot": f["allapot"],
                    "visszakuldes_indoka": f.get("visszakuldes_indoka")},
        "hianylista": h,
        "osszefoglalo": osz[0] if osz else None,
        "uzenetek": utolso_n,
        "fajlok": p.fajlok([["feature", "=", a.feature]]),
        "hivatkozott": hivatkozott,
        "elemek": el,
        "bizonyitekok": biz,
    }
    if a.ki:
        os.makedirs(os.path.dirname(os.path.abspath(a.ki)), exist_ok=True)
        fd = os.open(a.ki, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(adat, fh, ensure_ascii=False, indent=2)
        return {"ki": a.ki, "uzenetek_db": len(uz), "szazalek": h["szazalek"],
                "hianyzik": [t["kod"] for t in h["hianyzik"]], "osszefoglalo_verzio": osz[0]["verzio"] if osz else None}
    return adat


def cmd_bekuld(p, a):
    f = p.feature(a.feature)
    if f.get("allapot") not in ("Interjú", "Visszaküldve"):
        raise FelmeroHiba("FELMERO_ALLAPOT", "Csak Interjú vagy Visszaküldve állapotból küldhető be.", KILEP_MEGTAGADVA)
    osz = p.osszefoglalok(a.feature)
    legfrissebb = osz[0]["verzio"] if osz else None
    if legfrissebb is None or a.osszefoglalo_verzio != legfrissebb:
        raise FelmeroHiba("FELMERO_OSSZEFOGLALO", "A beküldéshez a legfrissebb összefoglaló (%s. verzió) kell." % legfrissebb, KILEP_MEGTAGADVA)
    el, biz, h, _ = ertekeles(p, f)
    if not h["bekuldheto"]:
        raise FelmeroHiba("FELMERO_HIANYOS", "Még nem küldhető be: " + "; ".join(h["akadalyok"]), KILEP_MEGTAGADVA)
    p.frissit("Felmero Feature", a.feature, {"allapot": "Bírálatra vár", "bekuldve": most(), "bekuldte": p.user,
                                             "teljesseg_szazalek": h["szazalek"]})
    return {"feature": a.feature, "allapot": "Bírálatra vár", "teljesseg_szazalek": h["szazalek"]}


def cmd_visszavon(p, a):
    f = p.feature(a.feature)
    if f.get("allapot") not in ("Vázlat", "Interjú", "Visszaküldve", "Bírálatra vár"):
        raise FelmeroHiba("FELMERO_ALLAPOT", "Ebben az állapotban nem vonható vissza (%s)." % f.get("allapot"), KILEP_MEGTAGADVA)
    p.frissit("Felmero Feature", a.feature, {"allapot": "Lezárva", "lezaras_indoka": a.indok or "A kliens visszavonta."})
    return {"feature": a.feature, "allapot": "Lezárva"}


KEZELOK = {
    "kivagyok": cmd_kivagyok, "hozzaferes": cmd_hozzaferes, "projektek": cmd_projektek, "projekt": cmd_projekt,
    "uj-projekt": cmd_uj_projekt, "projekt-frissit": cmd_projekt_frissit, "archival": cmd_archival,
    "uj-feature": cmd_uj_feature, "feature-frissit": cmd_feature_frissit, "feature": cmd_feature,
    "kontextus": cmd_kontextus, "hiany": cmd_hiany, "uzenetek": cmd_uzenetek, "par": cmd_par,
    "uzenet": cmd_uzenet, "kimeno": cmd_kimeno, "elem": cmd_elem, "osszefoglalo": cmd_osszefoglalo,
    "osszefoglalok": cmd_osszefoglalok, "hivatkozas": cmd_hivatkozas, "hivatkozas-torol": cmd_hivatkozas_torol,
    "feltolt": cmd_feltolt, "fajlok": cmd_fajlok, "fajl": cmd_fajl, "var": cmd_var, "letolt": cmd_letolt,
    "forma": cmd_forma, "bekuld": cmd_bekuld, "visszavon": cmd_visszavon,
    "munkak": cmd_munkak,
}


def build_parser():
    p = argparse.ArgumentParser(prog="erp_plan.py", description="Feature-felmérő kliens-CLI (Atomi).")
    p.add_argument("--szoveg", action="store_true", help="ember-olvasható rövid kimenet JSON helyett")
    sub = p.add_subparsers(dest="parancs", required=True, metavar="PARANCS")

    b = sub.add_parser("beallit", help="kapcsolat beállítása (a jelszó kérdéssel, nem parancssorban)")
    b.add_argument("--url", required=True)
    b.add_argument("--adapter", choices=("proto", "atomi"), default="proto")
    b.add_argument("--ceg", help="a cég neve (CRM Organization), ha a szerver nem adja meg")

    sub.add_parser("kivagyok", help="ki vagyok, mit érek el")
    sub.add_parser("hozzaferes", help="a teljes fa: projektek és feature-ök")
    sub.add_parser("projektek", help="projektek listája")
    x = sub.add_parser("projekt", help="egy projekt és feature-jei")
    x.add_argument("projekt", type=nev_tipus("FP"))

    x = sub.add_parser("uj-projekt", help="új projekt")
    x.add_argument("--cim", required=True)
    x.add_argument("--leiras")
    x.add_argument("--ceg")

    x = sub.add_parser("projekt-frissit", help="projekt módosítása")
    x.add_argument("projekt", type=nev_tipus("FP"))
    x.add_argument("--cim")
    x.add_argument("--leiras")
    x.add_argument("--hattertudas-fajl")
    x.add_argument("--szojegyzek")
    x.add_argument("--nyelv", choices=("hu", "ro", "en", "auto"))

    x = sub.add_parser("archival", help="projekt archiválása (csak kimondott kérésre)")
    x.add_argument("projekt", type=nev_tipus("FP"))

    x = sub.add_parser("uj-feature", help="új feature a projektben")
    x.add_argument("--projekt", required=True, type=nev_tipus("FP"))
    x.add_argument("--cim", required=True)

    x = sub.add_parser("feature-frissit", help="feature átnevezése")
    x.add_argument("feature", type=nev_tipus("FT"))
    x.add_argument("--cim", required=True)

    x = sub.add_parser("feature", help="egy feature")
    x.add_argument("feature", type=nev_tipus("FT"))

    x = sub.add_parser("kontextus", help="minden, ami a feature folytatásához kell")
    x.add_argument("feature", type=nev_tipus("FT"))
    x.add_argument("--utolso", type=int, default=20)
    x.add_argument("--ki", help="fájlba írja a teljes kontextust")

    x = sub.add_parser("hiany", help="a hiánylista (a szerver sorrendjében)")
    x.add_argument("feature", type=nev_tipus("FT"))

    x = sub.add_parser("uzenetek", help="üzenetek a feature-ben")
    x.add_argument("feature", type=nev_tipus("FT"))
    x.add_argument("--utan", type=int, default=0)
    x.add_argument("--limit", type=int, default=100)

    x = sub.add_parser("par", help="egy kérdés-válasz pár feltöltése")
    x.add_argument("feature", type=nev_tipus("FT"))
    x.add_argument("--kerdes-fajl", required=True)
    x.add_argument("--valasz-fajl", required=True)

    x = sub.add_parser("uzenet", help="egyetlen üzenet feltöltése")
    x.add_argument("feature", type=nev_tipus("FT"))
    x.add_argument("--szerep", required=True, choices=("kliens", "asszisztens"))
    x.add_argument("--fajl", required=True)

    x = sub.add_parser("kimeno", help="a fel nem töltött üzenetek újraküldése")
    x.add_argument("feature", type=nev_tipus("FT"))

    x = sub.add_parser("elem", help="egy specifikációs elem rögzítése idézettel")
    x.add_argument("feature", type=nev_tipus("FT"))
    x.add_argument("--kod", required=True)
    x.add_argument("--ertek-fajl", required=True)
    x.add_argument("--idezet", action="append", help="szó szerinti idézet a kliens üzenetéből (többször is adható)")
    x.add_argument("--datum", help="ÉÉÉÉ-HH-NN (C1, C2)")
    x.add_argument("--szam", type=int, help="30, 60 vagy 90 (D4)")
    x.add_argument("--kiegeszites")

    x = sub.add_parser("osszefoglalo", help="összefoglaló új verzióként")
    x.add_argument("feature", type=nev_tipus("FT"))
    x.add_argument("--fajl", required=True)

    x = sub.add_parser("osszefoglalok", help="összefoglalók listája")
    x.add_argument("feature", type=nev_tipus("FT"))

    x = sub.add_parser("hivatkozas", help="hivatkozás másik feature-re")
    x.add_argument("feature", type=nev_tipus("FT"))
    x.add_argument("--cel", required=True, type=nev_tipus("FT"))
    x.add_argument("--megjegyzes")

    x = sub.add_parser("hivatkozas-torol", help="hivatkozás törlése")
    x.add_argument("feature", type=nev_tipus("FT"))
    x.add_argument("--cel", required=True, type=nev_tipus("FT"))

    x = sub.add_parser("feltolt", help="fájlok feltöltése (projekthez vagy feature-höz)")
    x.add_argument("--projekt", required=True, type=nev_tipus("FP"))
    x.add_argument("--feature", type=nev_tipus("FT"))
    x.add_argument("fajlok", nargs="+", metavar="FÁJL")

    x = sub.add_parser("fajlok", help="fájlok listája")
    g = x.add_mutually_exclusive_group(required=True)
    g.add_argument("--projekt", type=nev_tipus("FP"))
    g.add_argument("--feature", type=nev_tipus("FT"))

    x = sub.add_parser("fajl", help="egy fájl állapota")
    x.add_argument("fajl", type=nev_tipus("FA"))

    x = sub.add_parser("var", help="várakozás az átalakításra")
    x.add_argument("fajl", type=nev_tipus("FA"))
    x.add_argument("--ido", type=int, default=600)

    x = sub.add_parser("letolt", help="fájl letöltése")
    x.add_argument("fajl", type=nev_tipus("FA"))
    x.add_argument("--forma", choices=("markdown", "eredeti"), default="markdown")
    x.add_argument("--ki")

    x = sub.add_parser("forma", help="elsődleges forma beállítása")
    x.add_argument("fajl", type=nev_tipus("FA"))
    x.add_argument("--elsodleges", required=True, choices=("markdown", "eredeti"))

    x = sub.add_parser("bekuld", help="összefoglaló után beküldés a mérnöknek")
    x.add_argument("feature", type=nev_tipus("FT"))
    x.add_argument("--osszefoglalo-verzio", dest="osszefoglalo_verzio", type=int, required=True)

    x = sub.add_parser("visszavon", help="saját feature visszavonása")
    x.add_argument("feature", type=nev_tipus("FT"))
    x.add_argument("--indok")

    x = sub.add_parser("munkak", help="a munkáid: nyitott, lezárt vagy mind")
    x.add_argument("--allapot", choices=("nyitott", "lezart", "mind"), default="nyitott")
    x.add_argument("--projekt", type=nev_tipus("FP"))

    x = sub.add_parser("kovetkezo", help="a következő lépés: egy mondat és a parancs")
    x.add_argument("feature", nargs="?", type=nev_tipus("FT"))
    x.add_argument("--kihagy", metavar="KÓD", help="nem kötelező elem kihagyása")

    sub.add_parser("verzio", help="a CLI és az API-verzió")
    return p


def szoveges(obj):
    if isinstance(obj, dict) and "hiba" in obj:
        h = obj["hiba"]
        return "Hiba (%s): %s" % (h["kod"], h["uzenet"])
    if isinstance(obj, dict) and "uzenet" in obj:
        return str(obj["uzenet"])
    return json.dumps(obj, ensure_ascii=False, indent=2)


def futtat(a):
    if a.parancs == "verzio":
        return {"cli": VERSION, "api_verzio": API_VERZIO}
    if a.parancs == "beallit":
        return cmd_beallit(a)
    if a.parancs == "kovetkezo":
        return kovetkezo_cli(a)
    p = adapter(kell_cfg())
    return KEZELOK[a.parancs](p, a)


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        eredmeny = futtat(a)
    except FelmeroHiba as h:
        kimenet = {"hiba": {"kod": h.kod, "uzenet": h.uzenet, "http": h.http_kod}}
        print(szoveges(kimenet) if a.szoveg else json.dumps(kimenet, ensure_ascii=False, indent=2))
        return h.kilepes
    if eredmeny is None:
        return KILEP_SIKER
    print(szoveges(eredmeny) if a.szoveg else json.dumps(eredmeny, ensure_ascii=False, indent=2))
    return KILEP_SIKER


if __name__ == "__main__":
    sys.exit(main())
