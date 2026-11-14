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
import shutil
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
KILEP_TALALAT = 6

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
              "/api/method/frappe.sessions.get_csrf_token", "/private/files/", "/files/",
              "/api/method/ping", "/api/method/atomi.felmero.api.szolgaltatas")
ATOMI_UTAK = ("/api/method/atomi.felmero.api.", "/api/method/ping")
ALAP_URL = "https://atomic.exarlabs.com"
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


NYITOTT_ALLAPOTOK = ("Vázlat", "Interjú", "Visszaküldve", "Bírálatra vár")
KITOLTOTT_ALLAPOTOK = ("Kész", "Hiányos")
SZAM_RE = re.compile(r"\d+(?:[ .]\d{3})*(?:,\d+)?")
EGYSEG = r"(óra|perc|nap|hét|hónap|év|fő|db|darab|számla|tétel|százalék|%|RON|lej|EUR|euró|Ft|forint)"
SZAM_EGYSEG_RE = re.compile(r"(?<![\w,.])(\d+(?:[ .]\d{3})*(?:,\d+)?)\s*" + EGYSEG + r"(?!\w)")
HOMALY_SZAVAK = ("gyors", "könnyű", "egyszerű", "felhasználóbarát", "jó", "megfelelő", "szép", "hatékony",
                 "stabil", "megbízható", "modern", "rugalmas", "intuitív", "kényelmes")
MEGFIGYELHETO_TOVEK = ("megjelen", "létrejö", "elkészül", "megkap", "kiment", "szerepel", "egyezik", "látsz",
                       "látható", "legfeljebb", "legalább", "belül", "nem enged", "hibaüzenet")
ELLENORZES_SULY = {"hiba": 0, "figyelem": 1}
SZAMPAROK_09 = (("B1", "D2"), ("B2", "UZ"), ("B4", "TD"))


def szam_kanon(szam):
    return szam.replace(" ", "").replace(".", "").replace(",", ".")


def szamok(szoveg):
    return {szam_kanon(t) for t in SZAM_RE.findall(szoveg or "")}


def sorok_szovegbol(szoveg):
    """A szöveg sorai (sortörés és pontosvessző mentén), a sor eleji jelölők nélkül."""
    ki = []
    for resz in re.split(r"[\n;]", szoveg or ""):
        sor = normal(re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", resz))
        if sor:
            ki.append(sor)
    return ki


def tetelek_szovegbol(szoveg):
    """A tételek: legalább 12 karakter és két szó, casefold után."""
    return [s for s in sorok_szovegbol(szoveg) if len(s.casefold()) >= 12 and len(s.split()) >= 2]


def _ert(k, kod):
    """Az elem sora, ha ki van töltve (Kész vagy Hiányos, és van értéke)."""
    for e in k["elemek"]:
        if e.get("kod") == kod and e.get("allapot") in KITOLTOTT_ALLAPOTOK and normal(e.get("ertek")):
            return e
    return None


def _biz(k, kod, csak_ervenyes=False):
    return [b for b in k["bizonyitekok"] if b.get("elem") == kod and (b.get("ervenyes") or not csak_ervenyes)]


def _talalat(kod, suly, elemek, ertekek, leiras, kerdes):
    szoveg = "|".join("" if v is None else normal(str(v)) for v in ertekek)
    ujj = hashlib.sha1((kod + "|" + szoveg).encode("utf-8")).hexdigest()[:10]
    return {"szabaly": kod, "suly": suly, "elemek": elemek, "leiras": leiras, "kerdes": kerdes,
            "ujjlenyomat": ujj, "reszletek": {}}


def _ink01(k, tv, kd, ma):
    ki = []
    for kod in KODOK:
        e = _ert(k, kod)
        if e is None:
            continue
        for b in _biz(k, kod):
            if not b.get("ervenyes"):
                ki.append(_talalat("INK-01", "hiba", [kod], [e.get("ertek"), b.get("idezet")],
                                   "Az idézet nincs meg szó szerint a kliens-üzenetben.",
                                   "Ezt rögzítettük a(z) %s pontnál: «%s». A hozzá tartozó mondatot («%s») "
                                   "nem találom az üzeneteid között. Elmondanád újra a saját szavaiddal?"
                                   % (CIMEK[kod], normal(e.get("ertek")), normal(b.get("idezet")))))
    return ki


def _ink02(k, tv, kd, ma):
    ki = []
    for kod in KODOK:
        e = _ert(k, kod)
        if e is None:
            continue
        nevek = {b.get("uzenet") for b in _biz(k, kod, True)}
        uzenetek = [u for u in k["uzenetek"] if u["name"] in nevek]
        if not uzenetek:
            continue
        van = set()
        for u in uzenetek:
            van |= szamok(u.get("szoveg"))
        hianyzo = next((s for resz in (e.get("ertek"), e.get("kiegeszites"))
                        for s in SZAM_RE.findall(resz or "") if szam_kanon(s) not in van), None)
        if hianyzo:
            ki.append(_talalat("INK-02", "figyelem", [kod], [e.get("ertek"), e.get("kiegeszites")],
                               "Az elemben szereplő szám nincs az idézett üzenetben.",
                               "A(z) %s pontnál ez a szám áll: %s. Az üzenetedben nem találom. Honnan való, és pontos?"
                               % (CIMEK[kod], hianyzo)))
    return ki


def _ink03(k, tv, kd, ma):
    c1, c2 = _ert(k, "C1"), _ert(k, "C2")
    if not c1 or not c2:
        return []
    d1, d2 = _datum(c1.get("datum")), _datum(c2.get("datum"))
    if d1 and d2 and d2 < d1:
        return [_talalat("INK-03", "hiba", ["C1", "C2"], [c1.get("datum"), c2.get("datum")],
                         "A határidő a kezdés előtt van.",
                         "Kezdésnek %s, határidőnek %s van felírva: a határidő a kezdés előtt van. Melyik a helyes?"
                         % (c1.get("datum"), c2.get("datum")))]
    return []


def _ink04(k, tv, kd, ma):
    c1, c2 = _ert(k, "C1"), _ert(k, "C2")
    if not c1 or not c2:
        return []
    d1, d2 = _datum(c1.get("datum")), _datum(c2.get("datum"))
    if d1 and d2:
        nap = (d2 - d1).days
        if nap > 28 or nap < 7:
            return [_talalat("INK-04", "figyelem", ["C1", "C2"], [c1.get("datum"), c2.get("datum")],
                             "A kezdés és a határidő között szokatlan a távolság.",
                             "A kezdés (%s) és a határidő (%s) között %d nap van. Így gondoltad?"
                             % (c1.get("datum"), c2.get("datum"), nap))]
    return []


def _ink05(k, tv, kd, ma):
    c1 = _ert(k, "C1")
    d1 = _datum(c1.get("datum")) if c1 else None
    if d1 and d1 < ma and k.get("allapot") in ("Vázlat", "Interjú", "Visszaküldve"):
        return [_talalat("INK-05", "figyelem", ["C1"], [c1.get("datum")],
                         "A felírt kezdés napja már elmúlt.",
                         "A kezdésnek felírt nap (%s) már elmúlt. Mi legyen az új kezdés?" % c1.get("datum"))]
    return []


def _ink06(k, tv, kd, ma):
    d4 = _ert(k, "D4")
    if d4 and _egesz(d4.get("szam")) not in MERESI_NAPOK:
        return [_talalat("INK-06", "hiba", ["D4"], [d4.get("ertek"), d4.get("szam")],
                         "A mérési időszak nem 30, 60 vagy 90 nap.",
                         "A mérési időszak 30, 60 vagy 90 nap lehet. Melyiket választod?")]
    return []


def _ink07(k, tv, kd, ma):
    osz = k.get("osszefoglalo")
    if osz and k["uzenetek"]:
        utolso = max(u["sorszam"] for u in k["uzenetek"])
        if osz["uzenet_sorszamig"] < utolso:
            db = sum(1 for u in k["uzenetek"] if u["sorszam"] > osz["uzenet_sorszamig"])
            return [_talalat("INK-07", "figyelem", [], [osz["verzio"], osz["uzenet_sorszamig"], utolso],
                             "Új üzenetek érkeztek az utolsó összefoglaló óta.",
                             "Az utolsó összefoglaló (%s. verzió) óta %d új üzeneted van. Frissítsem az összefoglalót?"
                             % (osz["verzio"], db))]
    return []


def _ink08(k, tv, kd, ma):
    ki = []
    for hv in k.get("hivatkozasok", []):
        if hv.get("allapot") in (None, "Lezárva"):
            ki.append(_talalat("INK-08", "figyelem", [], [hv["cel"], hv.get("allapot")],
                               "A hivatkozott munka lezárult, vagy nem érhető el.",
                               "Ez a munka a(z) «%s» munkára hivatkozik, amely lezárult. Marad a hivatkozás, "
                               "vagy már nem érvényes?" % (hv.get("cel_cim") or hv["cel"])))
    return ki


def _egyseg_szamok(szoveg):
    ki = {}
    for szam, egyseg in SZAM_EGYSEG_RE.findall(szoveg or ""):
        ki.setdefault(egyseg.casefold(), set()).add(szam_kanon(szam))
    return ki


def _ink09(k, tv, kd, ma):
    ki = []
    for a, b in SZAMPAROK_09:
        ea, eb = _ert(k, a), _ert(k, b)
        if not ea or not eb:
            continue
        sa, sb = _egyseg_szamok(ea.get("ertek")), _egyseg_szamok(eb.get("ertek"))
        for egyseg in sorted(set(sa) & set(sb)):
            if sa[egyseg].isdisjoint(sb[egyseg]):
                szam_a, szam_b = sorted(sa[egyseg])[0], sorted(sb[egyseg])[0]
                ki.append(_talalat("INK-09", "figyelem", [a, b], [ea.get("ertek"), eb.get("ertek")],
                                   "Két pontban eltérő szám ugyanarra az egységre.",
                                   "A(z) %s pontnál %s %s, a(z) %s pontnál %s %s szerepel. Ugyanarról van szó? "
                                   "Melyik a pontos?" % (CIMEK[a], szam_a, egyseg, CIMEK[b], szam_b, egyseg)))
                break
    return ki


def _ink10(k, tv, kd, ma):
    ki = []
    cel = [e for e in (_ert(k, "B2"), _ert(k, "UZ")) if e]
    hay = " ".join(normal(e.get("ertek")) for e in cel).casefold()
    for kod in ("B3", "KZ"):
        e = _ert(k, kod)
        if not e:
            continue
        for tetel in tetelek_szovegbol(e.get("ertek")):
            if tetel.casefold() in hay:
                ki.append(_talalat("INK-10", "hiba", [kod] + [c["kod"] for c in cel],
                                   [tetel, e.get("ertek")] + [c.get("ertek") for c in cel],
                                   "Kizárt tétel szerepel a megoldás leírásában.",
                                   "Ezt kizártad: «%s», de a megoldás leírásában is szerepel. Benne van, vagy nincs?"
                                   % tetel))
    return ki


def _ink11(k, tv, kd, ma):
    e = _ert(k, "D1")
    if not e:
        return []
    ki = []
    for sor in sorok_szovegbol(e.get("ertek")):
        cf = sor.casefold()
        szavak = set(re.findall(r"\w+", cf))
        homaly = any(h in szavak for h in HOMALY_SZAVAK)
        szam_van = bool(SZAM_RE.search(sor))
        tove = any(t in cf for t in MEGFIGYELHETO_TOVEK)
        if (homaly and not szam_van) or (not szam_van and not tove) or len(sor) < 15:
            ki.append(_talalat("INK-11", "figyelem", ["D1"], [sor],
                               "Az elfogadási feltétel nehezen ellenőrizhető.",
                               "Ez az elfogadási feltétel nehezen ellenőrizhető: «%s». Miből látod majd átvételkor, "
                               "igen vagy nem, konkrét adaton?" % sor))
    return ki


def _ink12(k, tv, kd, ma):
    e = _ert(k, "D2")
    if e and not SZAM_RE.search((e.get("ertek") or "") + " " + (e.get("kiegeszites") or "")):
        return [_talalat("INK-12", "figyelem", ["D2"], [e.get("ertek"), e.get("kiegeszites")],
                         "A kiinduló állapotban nincs szám.",
                         "A kiinduló állapotnál nincs szám. Mennyi ma, és honnan tudod?")]
    return []


def _ink13(k, tv, kd, ma):
    e = _ert(k, "D3")
    if e and not SZAM_RE.search(e.get("ertek") or ""):
        return [_talalat("INK-13", "figyelem", ["D3"], [e.get("ertek")],
                         "A sikerkritériumban nincs szám.",
                         "A sikerkritériumnál nincs szám. Mihez képest, mennyit vársz?")]
    return []


def _ink14(k, tv, kd, ma):
    csoport = {}
    for b in k["bizonyitekok"]:
        if b.get("ervenyes"):
            csoport.setdefault(normal(b.get("idezet")).casefold(), set()).add(b["elem"])
    ki = []
    for idezet, kodok in csoport.items():
        if len(kodok) >= 3:
            rendezett = sorted(kodok, key=KODOK.index)
            ki.append(_talalat("INK-14", "figyelem", rendezett,
                               [idezet] + [(_ert(k, kod) or {}).get("ertek") for kod in rendezett],
                               "Ugyanaz a mondat több pontot is alátámaszt.",
                               "Ugyanaz a mondatod támaszt alá %d pontot: %s. Mondanál mindegyikről külön is valamit?"
                               % (len(rendezett), ", ".join(rendezett))))
    return ki


def _ink15(k, tv, kd, ma):
    cim = normal(k.get("cim")).casefold()
    if not cim:
        return []
    return [_talalat("INK-15", "figyelem", [], [cim, t["name"]],
                     "Ugyanezzel a címmel másik nyitott munka van.",
                     "Ugyanezzel a címmel van egy másik nyitott munkád (%s). Kettő kell, vagy az egyiket "
                     "visszavonod?" % t["name"])
            for t in tv if t.get("allapot") in NYITOTT_ALLAPOTOK and normal(t.get("cim")).casefold() == cim]


def _ink16(k, tv, kd, ma):
    ki = []
    for kod in ("B3", "KZ"):
        e = _ert(k, kod)
        if not e:
            continue
        for t in tv[:20]:
            if t.get("allapot") not in NYITOTT_ALLAPOTOK:
                continue
            b2 = next((x for x in t.get("elemek") or [] if x.get("kod") == "B2" and normal(x.get("ertek"))), None)
            if not b2:
                continue
            hay = normal(b2.get("ertek")).casefold()
            for tetel in tetelek_szovegbol(e.get("ertek")):
                if tetel.casefold() in hay:
                    ki.append(_talalat("INK-16", "figyelem", [kod], [tetel, t["name"], b2.get("ertek"), e.get("ertek")],
                                       "Kizárt tétel más nyitott munkában szerepel kérésként.",
                                       "Amit itt kizársz («%s»), azt a(z) %s munkában kéred. Szándékos a szétválasztás?"
                                       % (tetel, t["name"])))
    return ki


def _ink17(k, tv, kd, ma):
    ki = []
    for fi in k.get("frappe_idezetek", []):
        if idezet_keres(fi.get("idezet"), k["uzenetek"]) is None:
            ki.append(_talalat("INK-17", "hiba", [], [fi.get("tema"), fi.get("idezet")],
                               "A Frappe-lap idézete nincs meg a kliens szavai között.",
                               "Ezt rögzítettük a(z) %s pontnál: «%s». A hozzá tartozó mondatot nem találom az "
                               "üzeneteid között. Elmondanád újra a saját szavaiddal?"
                               % (fi.get("cim"), normal(fi.get("idezet")))))
    return ki


def _ink18(k, tv, kd, ma):
    if kd > 0:
        return [_talalat("INK-18", "figyelem", [], [kd], "A helyi kimenő sor nincs feltöltve.",
                         "%d üzeneted még nincs fent a szerveren. Feltöltsem most?" % kd)]
    return []


def _ink19(k, tv, kd, ma):
    tarolt = k.get("tarolt_szazalek")
    if tarolt is None:
        return []
    szamolt = teljesseg_szazalek({e["kod"]: e.get("allapot") for e in k["elemek"]})
    if tarolt != szamolt:
        return [_talalat("INK-19", "figyelem", [], [tarolt, szamolt],
                         "A tárolt készültség eltér a számolttól.",
                         "A tárolt készültség (%s%%) eltér a számolttól (%s%%). Újraszámolom." % (tarolt, szamolt))]
    return []


SZABALYOK = (_ink01, _ink02, _ink03, _ink04, _ink05, _ink06, _ink07, _ink08, _ink09, _ink10,
             _ink11, _ink12, _ink13, _ink14, _ink15, _ink16, _ink17, _ink18, _ink19)


def ellenoriz(kontextus, testverek, kimeno_db, ma):
    """Tiszta függvény (4.3): a találatok listája, hiba elöl, azon belül szabálykód szerint.
    Az elfogadást a hívó jelöli (a helyi fájl alapján)."""
    talalatok = []
    for szabaly in SZABALYOK:
        talalatok.extend(szabaly(kontextus, list(testverek or []), kimeno_db, ma))
    talalatok.sort(key=lambda t: (ELLENORZES_SULY[t["suly"]], t["szabaly"]))
    return talalatok


# ---------------------------------------------------------------------------
# Frappe-kérdésbank, Frappe-lap, CONTEXT-vázlat (4.4). Tiszta függvények.
# ---------------------------------------------------------------------------

FRAPPE_TEMAK = [
    {"kod": "FR-ADAT", "cim": "Nyilvántartott adatok", "kotelezo": True,
     "mit_kell_tudni": "Milyen dolgokról vezet nyilvántartást, mindegyikről milyen adatot, mi kötelező, mi nem ismétlődhet, mi kapcsolódik mihez.",
     "kerdesek": ["Sorold fel, milyen dolgokat tartanál nyilván ebben a megoldásban, és mindegyikről milyen adatokat írnál fel.",
                  "Melyik adat nélkül nem menthető el egy ilyen tétel, és melyikből nem lehet kettő egyforma?",
                  "Mutass egy valódi példát: hogyan néz ki ma egy ilyen sor a táblázatodban vagy a papíron?"]},
    {"kod": "FR-MEGLEVO", "cim": "Ami már megvan", "kotelezo": False,
     "mit_kell_tudni": "Mit használ ma ugyanerre a rendszerünkben vagy máshol, és mit kell ebből megtartani.",
     "kerdesek": ["Mit használtok ma erre: a rendszer melyik részét, táblázatot, más programot?",
                  "Mi az, ami a mostani megoldásban jól működik, és maradjon így?"]},
    {"kod": "FR-JOG", "cim": "Ki mit láthat és tehet", "kotelezo": True,
     "mit_kell_tudni": "Szerepkörönként: ki látja, ki rögzíti, ki módosítja, ki törölheti; belép-e külső ember.",
     "kerdesek": ["Kik dolgoznak majd vele, és ki mit tehet: ki rögzít, ki hagy jóvá, ki csak nézi?",
                  "Van-e olyan adat, amit nem láthat mindenki?",
                  "Belép-e a rendszerbe külső ember, például ügyfél vagy beszállító?"]},
    {"kod": "FR-FOLYAMAT", "cim": "Állapotok és jóváhagyás", "kotelezo": False,
     "mit_kell_tudni": "A tétel állapotai az elejétől a végéig, ki léptetheti tovább, milyen feltétellel, vissza lehet-e lépni.",
     "kerdesek": ["Milyen állapotokon megy át egy tétel az elejétől a végéig?",
                  "Ki léptetheti a következő állapotba, és mi kell hozzá?",
                  "Vissza lehet-e küldeni, és akkor mi történik?"]},
    {"kod": "FR-SZABALY", "cim": "Szabályok és számítások", "kotelezo": False,
     "mit_kell_tudni": "A számítások pontos szabálya példával, kerekítés, határértékek, tiltott esetek.",
     "kerdesek": ["Van-e, amit a rendszernek ki kell számolnia? Mondd el a szabályt egy valódi példán.",
                  "Mit nem szabad engednie a rendszernek akkor sem, ha valaki megpróbálja?"]},
    {"kod": "FR-ERTESITES", "cim": "Értesítések", "kotelezo": False,
     "mit_kell_tudni": "Ki kap értesítést, milyen eseménynél, milyen csatornán, mi álljon benne.",
     "kerdesek": ["Kinek kell szólnia a rendszernek, és mikor?",
                  "Hol érje el: e-mailben, a rendszeren belül, máshol? Mi legyen az üzenetben?"]},
    {"kod": "FR-JELENTES", "cim": "Listák, jelentések, nyomtatványok", "kotelezo": False,
     "mit_kell_tudni": "Milyen lista vagy összesítés kell, milyen oszlopokkal és szűrőkkel, kell-e nyomtatott vagy letölthető forma.",
     "kerdesek": ["Milyen listát vagy összesítést néznél meg rendszeresen, és milyen oszlopok legyenek benne?",
                  "Mire szűrnél vagy csoportosítanál?",
                  "Kell-e nyomtatni vagy letölteni valamit, és kinek megy?"]},
    {"kod": "FR-INTEGRACIO", "cim": "Kapcsolat más rendszerekkel", "kotelezo": False,
     "mit_kell_tudni": "Melyik rendszerből jön vagy melyikbe megy adat, milyen gyakran, ki felel a másik oldalért, mi legyen hiba esetén.",
     "kerdesek": ["Melyik másik programból kellene adatot átvenni, vagy melyikbe átadni?",
                  "Milyen gyakran, és ki felel a másik rendszerért?",
                  "Mi történjen, ha a másik rendszer éppen nem érhető el?"]},
    {"kod": "FR-MIGRACIO", "cim": "Meglévő adatok átvétele", "kotelezo": False,
     "mit_kell_tudni": "Van-e átveendő régi adat, honnan, mennyi, milyen formában, ki ellenőrzi az átvétel után.",
     "kerdesek": ["Van-e meglévő adat, amit át kell hozni? Honnan, és nagyjából mennyi?",
                  "Milyen formában van ma, és ki tudja megmondani az átvétel után, hogy jó-e?"]},
    {"kod": "FR-FELULET", "cim": "Hol és hogyan használják", "kotelezo": False,
     "mit_kell_tudni": "Számítógépen vagy telefonon, irodában vagy terepen, milyen nyelven, milyen lépésekben.",
     "kerdesek": ["Hol használják majd: irodában gépen, vagy terepen telefonon?",
                  "Milyen nyelven legyen a felület?",
                  "Mi az a három lépés, amit a leggyakrabban csinálnak majd benne?"]},
    {"kod": "FR-UZEM", "cim": "Mennyiség és megőrzés", "kotelezo": False,
     "mit_kell_tudni": "Havi tételszám, felhasználók száma, csúcsidőszak, meddig kell megőrizni az adatot.",
     "kerdesek": ["Nagyjából hány ilyen tétel keletkezik egy hónapban, és hányan dolgoznak vele egyszerre?",
                  "Van-e időszak, amikor sokkal több a munka?",
                  "Meddig kell megőrizni ezeket az adatokat?"]},
    {"kod": "FR-PROBA", "cim": "Elfogadási próbák", "kotelezo": True,
     "mit_kell_tudni": "Legalább egy teljes próba: kiinduló adat, lépések, várt eredmény; és legalább egy dolog, aminek soha nem szabad megtörténnie.",
     "kerdesek": ["Mondj egy valódi esetet az elejétől a végéig: mivel indul, mit csinál az ember, és mit kell látnia a végén?",
                  "Mi az, aminek soha nem szabad megtörténnie ebben a megoldásban?",
                  "Milyen adaton próbálnád ki átvételkor?"]},
]
FRAPPE_TEMA_MAP = {t["kod"]: t for t in FRAPPE_TEMAK}
FRAPPE_LAP_VERZIO = 1
FRAPPE_ALLAPOTOK = ("Kész", "Nem releváns")
CONTEXT_FAJL_NEV = "CONTEXT-vazlat.md"
CONTEXT_LIGHT_WAY = "TODO (engineer): how far the site's existing modules get without code; one line per intent line."
CONTEXT_RIGOR = "TODO (engineer): light or heavy."
CONTEXT_RIGOR_HINT = "Hint: permissions or data migration are in scope, heavy by default."
CONTEXT_TODO = "TODO (engineer)"
CONTEXT_NINCS = "- nincs nyitott pont"


def ures_lap():
    return {"verzio": FRAPPE_LAP_VERZIO, "kihagyva": False, "temak": {}}


def lap_szovegbol(szoveg):
    """A szerver frappe_lap mezőjének szövege -> lap. Üres szöveg: üres lap."""
    if not szoveg:
        return ures_lap()
    try:
        adat = json.loads(szoveg)
    except ValueError:
        raise FelmeroHiba("FELMERO_NEM_ELERHETO", "A Frappe-lap nem olvasható.", KILEP_HASZNALAT)
    if not isinstance(adat, dict):
        raise FelmeroHiba("FELMERO_NEM_ELERHETO", "A Frappe-lap nem olvasható.", KILEP_HASZNALAT)
    adat.setdefault("kihagyva", False)
    adat.setdefault("temak", {})
    return adat


def frappe_nezet(lap):
    """A lap kérdésbankkal összevetve. lap None: a mező nem érhető el a szerveren."""
    if lap is None:
        return {"elerheto": False, "kihagyva": False, "kesz_db": 0, "ossz_db": len(FRAPPE_TEMAK), "temak": []}
    temak = lap.get("temak") or {}
    sorok = []
    for t in FRAPPE_TEMAK:
        r = temak.get(t["kod"])
        sorok.append({"kod": t["kod"], "cim": t["cim"], "kotelezo": t["kotelezo"],
                      "mit_kell_tudni": t["mit_kell_tudni"], "kerdesek": list(t["kerdesek"]),
                      "allapot": r.get("allapot") if r else "Hiányzik",
                      "ertek": (r or {}).get("ertek", "")})
    return {"elerheto": True, "kihagyva": bool(lap.get("kihagyva")),
            "kesz_db": sum(1 for s in sorok if s["allapot"] != "Hiányzik"), "ossz_db": len(sorok), "temak": sorok}


def frappe_idezetek(lap):
    """A lap idézetei az INK-17 szabálynak: [{tema, cim, idezet}]."""
    ki = []
    for t in FRAPPE_TEMAK:
        r = (lap or {}).get("temak", {}).get(t["kod"])
        for i in (r or {}).get("idezetek") or []:
            ki.append({"tema": t["kod"], "cim": t["cim"], "idezet": i.get("idezet")})
    return ki


def _kvota(sor):
    return "> „%s” (üzenet #%s)" % (normal(sor.get("idezet")), sor.get("uzenet_sorszam"))


def _elem_sor(kod, el, biz):
    """Egy elem egy tartalmi sora, alatta az érvényes idézetei."""
    e = el.get(kod)
    cim = CIMEK[kod]
    if not e or not e.get("ertek"):
        return ["- **%s %s:** %s" % (kod, cim, CONTEXT_TODO)]
    ertek = " / ".join(sorok_szovegbol(e["ertek"]))
    if e.get("datum"):
        ertek += " (%s)" % e["datum"]
    sorok =["- **%s %s:** %s" % (kod, cim, ertek)]
    sorok += [_kvota(b) for b in biz if b.get("elem") == kod and b.get("ervenyes")]
    return sorok


def _tema_sor(tema, t):
    """Egy Frappe-téma sora, alatta az idézetei; Nem releváns esetén a kliens jelölésével."""
    if not t or t.get("allapot") == "Hiányzik":
        return ["- %s" % CONTEXT_TODO]
    idezetek = [_kvota(i) for i in (t.get("idezetek") or [])]
    if t["allapot"] == "Nem releváns":
        return ["- Not relevant (client): %s" % tema["cim"]] + idezetek
    return ["- **%s:** %s" % (tema["cim"], " / ".join(sorok_szovegbol(t.get("ertek", ""))) or CONTEXT_TODO)] + idezetek


def _szakasz(sorok):
    return sorok if sorok else ["- %s" % CONTEXT_TODO]


def _intent(el, biz, lap_temak):
    """Legfeljebb négy számozott sor (D1 és FR-PROBA), utána a Must not sor (B3 első tétele)."""
    numerált = []
    for s in sorok_szovegbol((el.get("D1") or {}).get("ertek", "")):
        numerált.append((s, [_kvota(b) for b in biz if b.get("elem") == "D1" and b.get("ervenyes")]))
    proba = lap_temak.get("FR-PROBA") or {}
    if proba.get("allapot") == "Kész":
        for s in sorok_szovegbol(proba.get("ertek", "")):
            numerált.append((s, [_kvota(i) for i in proba.get("idezetek") or []]))
    numerált = numerált[:4]
    sorok = []
    for i, (s, idezetek) in enumerate(numerált, 1):
        sorok.append("%d. %s" % (i, s))
        sorok += idezetek
    if not sorok:
        sorok.append("1. %s" % CONTEXT_TODO)
    tetel = tetelek_szovegbol((el.get("B3") or {}).get("ertek", ""))
    if tetel:
        sorok.append("Must not: %s" % tetel[0])
        sorok += [_kvota(b) for b in biz if b.get("elem") == "B3" and b.get("ervenyes")][:1]
    else:
        sorok.append("Must not: %s" % CONTEXT_TODO)
    return sorok


def context_md(k, lap, ma):
    """A CONTEXT-vázlat (4.4). Tiszta, determinisztikus: ugyanaz a bemenet, ugyanaz a bájt.
    k: name, cim, allapot, projekt, projekt_cim, elemek, bizonyitekok, hianylista, talalatok.
    lap: a Frappe-lap (vagy ures_lap()); ma: datetime.date."""
    el = {e["kod"]: e for e in k.get("elemek") or []}
    biz = k.get("bizonyitekok") or []
    nezet = frappe_nezet(lap or ures_lap())
    temak = {t["kod"]: t for t in nezet["temak"]}
    lap_temak = (lap or {}).get("temak") or {}

    def tema(kod):
        t = temak.get(kod)
        if t is not None:
            t = dict(t, idezetek=(lap_temak.get(kod) or {}).get("idezetek") or [])
        return _szakasz(_tema_sor(FRAPPE_TEMA_MAP[kod], t))

    def elemek(kodok):
        ki = []
        for kod in kodok:
            ki += _elem_sor(kod, el, biz)
        return ki

    def temak_sorai(kodok):
        ki = []
        for kod in kodok:
            ki += tema(kod)
        return ki

    hianyzo = [t for t in FRAPPE_TEMAK if temak.get(t["kod"], {}).get("allapot") == "Hiányzik"]
    nyitott = [("- Hiányzik: %s. %s" % (t["cim"], t["mit_kell_tudni"])) for t in hianyzo]
    nyitott += [("- %s %s: %s" % (h["kod"], h["cim"], h["mit_kell_tudni"]))
                for h in (k.get("hianylista") or {}).get("hianyzik", [])]
    nyitott += ["- %s: %s" % (t.get("szabaly"), t.get("leiras")) for t in k.get("talalatok") or []]

    szakaszok = [
        ("## Jira / Ticket", ["- Feature: %s" % k["name"],
                              "- Projekt: %s (%s)" % (k.get("projekt", ""), k.get("projekt_cim", "")),
                              "- Állapot: %s" % k.get("allapot", "")]),
        ("## Business Requirements", elemek(["B1", "B2", "UZ", "D2", "D3", "D4", "A1"])),
        ("## Intent", _intent(el, biz, lap_temak)),
        ("## Data model (DocTypes and fields)", temak_sorai(["FR-ADAT"])),
        ("## Permissions", temak_sorai(["FR-JOG"])),
        ("## Workflow", temak_sorai(["FR-FOLYAMAT"])),
        ("## Validation and calculations", temak_sorai(["FR-SZABALY"])),
        ("## Notifications", temak_sorai(["FR-ERTESITES"])),
        ("## Reports and print", temak_sorai(["FR-JELENTES"])),
        ("## Integrations", temak_sorai(["FR-INTEGRACIO"]) + elemek(["B4"])),
        ("## Data migration", temak_sorai(["FR-MIGRACIO"])),
        ("## UX / Design Decisions", elemek(["UX"]) + temak_sorai(["FR-FELULET"])),
        ("## Technical Decisions", elemek(["TD"]) + temak_sorai(["FR-MEGLEVO", "FR-UZEM"])),
        ("## Light way", [CONTEXT_LIGHT_WAY]),
        ("## Acceptance tests", temak_sorai(["FR-PROBA"]) + elemek(["D1"])),
        ("## Exclusions", elemek(["B3", "KZ"])),
        ("## Open questions", nyitott or [CONTEXT_NINCS]),
        ("## Timeline (client's wish, not a commitment)", elemek(["C1", "C2"])),
        ("## Rigor", [CONTEXT_RIGOR] + ([CONTEXT_RIGOR_HINT] if any(
            temak.get(kod, {}).get("allapot") == "Kész" for kod in ("FR-JOG", "FR-MIGRACIO")) else [])),
    ]
    sorok = ["# %s: Context (DRAFT)" % k.get("cim", ""), "",
             "Gépileg összeállítva a kliens szavaiból, %s. A mérnök ellenőrzi és egészíti ki." % ma.isoformat()]
    for cim, tartalom in szakaszok:
        sorok += ["", cim] + _szakasz(tartalom)
    return "\n".join(sorok) + "\n"


def nyitott_db(szoveg):
    """A „Open questions” szakasz tartalmi sorainak száma (a „nincs” sor nélkül)."""
    resz = szoveg.split("## Open questions", 1)[-1].split("## Timeline", 1)[0]
    return sum(1 for s in resz.splitlines() if s.startswith("- ") and s != CONTEXT_NINCS)


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

    def keres(self, metodus, ut, adat=None, nyers=None, tipus=None, fejlec=None):
        ut_resz = ut.split("?", 1)[0]
        if not any(ut_resz.startswith(p) for p in AKTIV_UTAK[0]):
            raise FelmeroHiba("FELMERO_BELSO", "Nem engedélyezett végpont.", KILEP_HASZNALAT)
        fej = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        fej.update(fejlec or {})
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

    def frappe_lap_nyers(self, nev):
        """A frappe_lap mező szövege. None, ha a szerver nem adja vissza a mezőt (a mező nincs a demón)."""
        try:
            sorok = self.lista("Felmero Feature", ["name", "frappe_lap"], [["name", "=", nev]], limit=1)
        except FelmeroHiba as h:
            if h.http_kod in (400, 404, 417, 500):
                return None
            raise
        if not sorok or "frappe_lap" not in sorok[0]:
            return None
        return sorok[0]["frappe_lap"] or ""


class Atomi:
    """Váz: a későbbi atomi.felmero.api.* végpontok helye. Most minden parancs erre fut."""

    def __init__(self, cfg):
        self.cfg = cfg

    def whoami(self):
        """Az eszközkulccsal: a szerver mondja meg, ki vagy és mit érsz el. A kulcs a fejlécben megy, nem a kimenetben."""
        key, secret = self.cfg.get("api_key") or "", self.cfg.get("api_secret") or ""
        if not key or not secret:
            raise FelmeroHiba("FELMERO_BEJELENTKEZES", "Nincs eszközkulcs a beállításban.", KILEP_BEALLITAS)
        k = Kliens(self.cfg["url"])
        k.titkok = [key, secret]
        torzs = k.keres("GET", "/api/method/atomi.felmero.api.whoami",
                        fejlec={"Authorization": "token %s:%s" % (key, secret)})
        adat = json_be(torzs).get("message")
        if not isinstance(adat, dict):
            raise FelmeroHiba("FELMERO_VALASZ", "Érvénytelen válasz a szervertől.", KILEP_HALOZAT)
        return dict(adat, adapter="atomi")

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
        AKTIV_UTAK[0] = ATOMI_UTAK
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


def hivatkozasok(p, f):
    ki = []
    for hv in f.get("hivatkozasok") or []:
        try:
            cf = p.feature(hv["cel"])
            ki.append({"cel": hv["cel"], "cel_cim": cf.get("cim"), "allapot": cf.get("allapot")})
        except FelmeroHiba:
            ki.append({"cel": hv["cel"], "cel_cim": hv["cel"], "allapot": None})
    return ki


def testverek(p, f):
    nyitott = [s for s in p.munka_lista(f["projekt"]) if s["name"] != f["name"] and s.get("allapot") in NYITOTT_ALLAPOTOK]
    return [{"name": s["name"], "cim": s.get("cim") or "", "allapot": s["allapot"],
             "elemek": p.feature(s["name"]).get("elemek") or []} for s in nyitott[:20]]


def munka_reszlet(p, f):
    uz = p.kliens_uzenetek(f["name"])
    el, biz, _ = szamol(f.get("elemek") or [], f.get("bizonyitekok") or [], uz)
    osz = p.osszefoglalok(f["name"])
    h = hianylista(el, len(osz), f.get("allapot"))
    kimeno_db = len(kimeno_olvas(f["name"]))
    lap = frappe_lap_olvas(p, f)
    kontext = {"name": f["name"], "cim": f.get("cim") or "", "allapot": f.get("allapot"), "elemek": el,
               "bizonyitekok": biz, "uzenetek": uz,
               "osszefoglalo": {"verzio": osz[0]["verzio"], "uzenet_sorszamig": osz[0]["uzenet_sorszamig"]} if osz else None,
               "hivatkozasok": hivatkozasok(p, f), "frappe_idezetek": frappe_idezetek(lap),
               "tarolt_szazalek": f.get("teljesseg_szazalek")}
    talalatok = ellenoriz(kontext, testverek(p, f), kimeno_db, datetime.date.today())
    elfogadott = set(helyi_olvas(f["name"])["elfogadott"])
    for t in talalatok:
        t["elfogadva"] = t["suly"] == "figyelem" and t["ujjlenyomat"] in elfogadott
    return {"feature": f["name"], "cim": f.get("cim"), "allapot": f.get("allapot"), "kimeno_db": kimeno_db,
            "kliens_uzenet_db": len(uz), "osszefoglalo_db": len(osz), "talalatok": talalatok,
            "ink07": any(t["szabaly"] == "INK-07" for t in talalatok), "hianylista": h,
            "kihagyott": helyi_olvas(f["name"])["kihagyott"],
            "pontositando": [{"kod": e["kod"], "cim": CIMEK.get(e["kod"], e["kod"]),
                              "megjegyzes": e.get("mernok_megjegyzes") or ""}
                             for e in el if e.get("mernok_allapot") == "Pontosítandó"],
            "visszakuldes_indoka": f.get("visszakuldes_indoka"), "frappe": frappe_nezet(lap)}


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


def cmd_ellenorzes(p, a):
    f = p.feature(a.feature)
    if a.elfogad:
        ismert = {t["ujjlenyomat"]: t for t in munka_reszlet(p, f)["talalatok"]}
        helyi = helyi_olvas(a.feature)
        for u in a.elfogad:
            t = ismert.get(u)
            if t is None:
                raise FelmeroHiba("FELMERO_ELEM_ADAT", "Ehhez a munkához nincs ilyen találat: " + u, KILEP_HASZNALAT)
            if t["suly"] == "hiba":
                raise FelmeroHiba("FELMERO_ELEM_ADAT", "A hiba súlyú találatot nem lehet elfogadni.", KILEP_HASZNALAT)
            if u not in helyi["elfogadott"]:
                helyi["elfogadott"].append(u)
        helyi_iras(a.feature, helyi)
    talalatok = munka_reszlet(p, f)["talalatok"]
    hiba_db = sum(1 for t in talalatok if t["suly"] == "hiba")
    return {"_kilepes": KILEP_TALALAT if hiba_db else KILEP_SIKER, "feature": a.feature, "hiba_db": hiba_db,
            "figyelem_db": sum(1 for t in talalatok if t["suly"] == "figyelem" and not t["elfogadva"]),
            "elfogadott_db": sum(1 for t in talalatok if t["elfogadva"]),
            "talalatok": [t for t in talalatok if a.mind or not t["elfogadva"]]}


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


def frappe_lap_olvas(p, f):
    """A feature Frappe-lapja, vagy None, ha a mező nem érhető el."""
    szoveg = p.frappe_lap_nyers(f["name"])
    return None if szoveg is None else lap_szovegbol(szoveg)


def frappe_lap_ment(p, f, lap):
    """Írás után visszaolvassa: ha nem egyezik, FELMERO_NEM_ELERHETO."""
    p.frissit("Felmero Feature", f["name"], {"frappe_lap": json.dumps(lap, ensure_ascii=False, sort_keys=True)})
    vissza = p.frappe_lap_nyers(f["name"])
    if vissza is None or lap_szovegbol(vissza) != lap_szovegbol(json.dumps(lap, ensure_ascii=False)):
        raise FelmeroHiba("FELMERO_NEM_ELERHETO", "A mentés után a Frappe-lap nem olvasható vissza.", KILEP_HASZNALAT)


def cmd_frappe_kerdesek(p, a):
    if not a.feature:
        return {"temak": [dict(t, kerdesek=list(t["kerdesek"])) for t in FRAPPE_TEMAK]}
    f = p.feature(a.feature)
    return dict({"feature": f["name"]}, **frappe_nezet(frappe_lap_olvas(p, f)))


def cmd_frappe_lap(p, a):
    f = p.feature(a.feature)
    pr = p.egy("Felmero Projekt", f["projekt"])
    irhato_projekt(pr)
    irhato_feature(f)
    lap = frappe_lap_olvas(p, f)
    if lap is None:
        raise FelmeroHiba("FELMERO_NEM_ELERHETO", "Ezen a szerveren a Frappe-lap nem érhető el.", KILEP_HASZNALAT)
    if a.kihagy or a.folytat:
        lap["kihagyva"] = bool(a.kihagy)
        frappe_lap_ment(p, f, lap)
        n = frappe_nezet(lap)
        return {"kihagyva": n["kihagyva"], "kesz_db": n["kesz_db"],
                "hianyzik": [t["kod"] for t in n["temak"] if t["allapot"] == "Hiányzik"]}
    if not a.tema or a.tema not in FRAPPE_TEMA_MAP:
        raise FelmeroHiba("FELMERO_ISMERETLEN_ELEM", "Ismeretlen téma. A kódok: " + ", ".join(FRAPPE_TEMA_MAP) + ".",
                          KILEP_HASZNALAT)
    idezetek = a.idezet or []
    if not idezetek:
        raise FelmeroHiba("FELMERO_IDEZET_NINCS", "Legalább egy idézet kell a kliens üzenetéből. Nem mentettem semmit.",
                          KILEP_MEGTAGADVA)
    if len(idezetek) > IDEZET_DARAB_MAX:
        raise FelmeroHiba("FELMERO_HOSSZ", "Legfeljebb %d idézet adható meg." % IDEZET_DARAB_MAX, KILEP_HASZNALAT)
    for i in idezetek:
        hiba = idezet_formai_hiba(i)
        if hiba:
            raise FelmeroHiba(hiba, "Az idézet túl rövid vagy túl hosszú.", KILEP_HASZNALAT)
    uz = p.kliens_uzenetek(f["name"])
    talalatok = []
    for i in idezetek:
        t = idezet_keres(i, uz)
        if not t:
            raise FelmeroHiba("FELMERO_IDEZET_NINCS", "Az idézet nem egyezik egy kliens-üzenettel sem. Nem mentettem semmit.",
                              KILEP_MEGTAGADVA)
        talalatok.append({"idezet": i, "uzenet": t[0], "uzenet_sorszam": t[1]})
    if a.nem_relevans:
        allapot, ertek = "Nem releváns", ""
    else:
        if not a.ertek_fajl:
            raise FelmeroHiba("FELMERO_ELEM_ADAT", "Az értékhez add meg a --ertek-fajl kapcsolót, vagy a --nem-relevans kapcsolót.",
                              KILEP_HASZNALAT)
        ertek = beolvas(a.ertek_fajl).strip()
        if not ertek or len(ertek) > UZENET_MAX:
            raise FelmeroHiba("FELMERO_URES", "Az érték nem lehet üres, és legfeljebb %d karakter lehet." % UZENET_MAX,
                              KILEP_HASZNALAT)
        allapot = "Kész"
    lap["temak"][a.tema] = {"allapot": allapot, "ertek": ertek, "idezetek": talalatok, "modositva": most()}
    frappe_lap_ment(p, f, lap)
    n = frappe_nezet(lap)
    return {"tema": a.tema, "allapot": allapot, "kesz_db": n["kesz_db"],
            "hianyzik": [t["kod"] for t in n["temak"] if t["allapot"] == "Hiányzik"]}


def context_feltolt(p, pr, f, szoveg):
    """A vázlat csatolása a munkához: Markdown, a demón .md.txt néven megy, a nyilvántartásban CONTEXT-vazlat.md marad."""
    bajt = szoveg.encode("utf-8")
    file_doc = p.feltolt_bajt("Felmero Feature", f["name"], CONTEXT_FAJL_NEV + ".txt", bajt, "text/plain")
    fa = p.uj("Felmero Fajl", {
        "fajl_nev": CONTEXT_FAJL_NEV, "projekt": f["projekt"], "feature": f["name"],
        "crm_organization": pr["crm_organization"], "tipus": "szoveg", "mime": "text/markdown", "meret": len(bajt),
        "sha256": hashlib.sha256(bajt).hexdigest(), "feltoltotte": p.user, "feltolto_nev": p.nev,
        "elsodleges_forma": "markdown", "file": file_doc["name"], "markdown_file": file_doc["name"],
        "markdown_meret": len(bajt), "markdown_minoseg": "jó", "atalakitas_allapot": "Nem kell",
        "atiras_allapot": "Nem kell"})
    return fa["name"]


def cmd_context_vazlat(p, a):
    f = p.feature(a.feature)
    pr = p.egy("Felmero Projekt", f["projekt"])
    if a.feltolt:
        irhato_feature(f)
    el, biz, h, _ = ertekeles(p, f)
    talalatok = [t for t in munka_reszlet(p, f)["talalatok"] if not t.get("elfogadva")]
    lap = frappe_lap_olvas(p, f) or ures_lap()
    k = {"name": f["name"], "cim": f.get("cim") or "", "allapot": f.get("allapot"), "projekt": f["projekt"],
         "projekt_cim": pr.get("cim") or "", "elemek": el, "bizonyitekok": biz, "hianylista": h,
         "talalatok": talalatok}
    szoveg = context_md(k, lap, datetime.date.today())
    os.makedirs(os.path.dirname(os.path.abspath(a.ki)), exist_ok=True)
    fd = os.open(a.ki, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(szoveg.encode("utf-8"))
    os.chmod(a.ki, 0o600)
    fajl = context_feltolt(p, pr, f, szoveg) if a.feltolt else None
    return {"ki": a.ki, "sorok": szoveg.count("\n"), "nyitott_db": nyitott_db(szoveg), "fajl": fajl}


def teendo_valaszt(van_cfg, adapter_nev, alap_url, rend, mod):
    """A kapcsolódás teendője (4.5 táblája). rend: lépéskód -> rendben; mod: eles, proba vagy None."""
    if not van_cfg:
        if alap_url:
            return "KULCS_IGENYLES" if mod == "eles" else "HOZZAFERES_KERES"
        if not rend.get("URL"):
            return "BEALLIT"
        if not rend.get("HALOZAT"):
            return "HALOZAT_VARJ"
        return "KULCS_IGENYLES" if mod == "eles" else "BEALLIT"
    if not rend.get("URL"):
        return "BEALLIT"
    if not rend.get("HALOZAT"):
        return "HALOZAT_VARJ"
    if not rend.get("BELEPES"):
        return "KULCS_IGENYLES" if adapter_nev == "atomi" else "BEALLIT"
    if not rend.get("SZERVEZET"):
        return "HOZZAFERES_KERES"
    if not rend.get("IRHAT"):
        return "CSAK_OLVASAS"
    if not rend.get("API_VERZIO"):
        return "FRISSITS"
    return "NINCS"


def kimeno_darab():
    mappa = kimeno_mappa()
    if not os.path.isdir(mappa):
        return 0
    return sum(len(kimeno_olvas(nev[:-len(".jsonl")])) for nev in os.listdir(mappa) if nev.endswith(".jsonl"))


def kapcsolat_adat(cfg, url, alap_url):
    """A kapcsolódás lépései (4.5). A függő lépés kihagyva, ha az előfeltétele hamis.
    A HALOZAT és a SZOLGALTATAS konfig nélkül is fut: a teendő-ágak ezt kérik."""
    lepesek, rend = [], {}
    mod, who = None, None
    adapter_nev = (cfg or {}).get("adapter", "proto") if cfg else None

    def rogzit(kod, ok, reszlet="", kihagyva=False):
        rend[kod] = bool(ok) and not kihagyva
        sor = {"kod": kod, "rendben": rend[kod], "reszlet": reszlet}
        if kihagyva:
            sor["kihagyva"] = True
        lepesek.append(sor)

    rogzit("BEALLITAS", bool(cfg), "van beállítás" if cfg else "nincs beállító fájl, vagy nem olvasható")
    if url is None:
        rogzit("URL", False, "nincs cím a beállításban")
    else:
        rogzit("URL", url_ervenyes(url), "rendben" if url_ervenyes(url) else "csak https, vagy localhost")
    if not rend["URL"]:
        rogzit("HALOZAT", False, "kihagyva", kihagyva=True)
    else:
        try:
            valasz = json_be(Kliens(url, idotullepes=10).keres("GET", "/api/method/ping"))
            rogzit("HALOZAT", isinstance(valasz, dict) and valasz.get("message") == "pong", "ping")
        except FelmeroHiba as h:
            rogzit("HALOZAT", False, h.kod)
    if not rend["HALOZAT"]:
        rogzit("SZOLGALTATAS", False, "kihagyva", kihagyva=True)
    else:
        try:
            valasz = json_be(Kliens(url).keres("GET", "/api/method/atomi.felmero.api.szolgaltatas"))
            if isinstance(valasz, dict) and isinstance(valasz.get("message"), dict):
                mod = "eles"
                rogzit("SZOLGALTATAS", True, "az eszközkódos út él")
            else:
                mod = "proba"
                rogzit("SZOLGALTATAS", True, "nincs eszközkódos végpont (a próba-mód ez, nem akadály)")
        except FelmeroHiba as h:
            if h.http_kod is None:
                rogzit("SZOLGALTATAS", False, h.kod)
            else:
                mod = "proba"
                rogzit("SZOLGALTATAS", True, "nincs eszközkódos végpont (a próba-mód ez, nem akadály)")
    if not cfg or not rend["URL"] or not rend["HALOZAT"]:
        rogzit("BELEPES", False, "kihagyva", kihagyva=True)
    else:
        try:
            p = adapter(dict(cfg, url=url, adapter=cfg.get("adapter", "proto")))
            who = p.whoami()
            rogzit("BELEPES", True, "belépés rendben")
        except FelmeroHiba as h:
            rogzit("BELEPES", False, h.kod)
    if who is None:
        for kod in ("SZERVEZET", "IRHAT", "API_VERZIO"):
            rogzit(kod, False, "kihagyva", kihagyva=True)
    else:
        rogzit("SZERVEZET", bool(who.get("szervezetek")), "legalább egy cég")
        rogzit("IRHAT", bool(who.get("irhat")), "írhat" if who.get("irhat") else "csak olvashat")
        rogzit("API_VERZIO", who.get("api_verzio") == API_VERZIO, "a szerver API-verziója egyezik")
    rogzit("KIMENO", True, "%d üzenet vár feltöltésre" % kimeno_darab())
    elso = next((s["kod"] for s in lepesek if not s["rendben"] and not s.get("kihagyva")), None)
    return {"adapter": adapter_nev, "mod": mod, "lepesek": lepesek, "elso_akadaly": elso, "rend": rend}


def cmd_kapcsolat(a):
    utvonal = config_utvonal()
    cfg = None
    if os.path.exists(utvonal):
        try:
            cfg = config_betoltes(utvonal) or None
        except FelmeroHiba:
            cfg = None
    alap_url = a.url is None and cfg is None
    url = a.url or (cfg or {}).get("url") or (ALAP_URL if alap_url else None)
    adat = kapcsolat_adat(cfg, url, alap_url)
    teendo = teendo_valaszt(bool(cfg), adat["adapter"], alap_url, adat["rend"], adat["mod"])
    kimenet = {"url": url, "adapter": adat["adapter"], "mod": adat["mod"], "lepesek": adat["lepesek"],
               "elso_akadaly": adat["elso_akadaly"], "teendo": teendo}
    if teendo != "NINCS":
        kimenet["_kilepes"] = KILEP_TALALAT
    return kimenet


def cmd_paros_allapot(a):
    """A PAROS Advisor telepítése a gépen. Hálózat nélkül, mindig 0-val lép ki."""
    mappa = os.path.expanduser("~/.paros-advisor")
    verzio_fajl = os.path.join(mappa, "VERSION")
    telepitve = os.path.isfile(verzio_fajl)
    verzio = None
    if telepitve:
        try:
            with open(verzio_fajl, encoding="utf-8") as f:
                verzio = f.read().strip() or None
        except OSError:
            verzio = None
    return {"telepitve": telepitve, "mappa": "~/.paros-advisor", "verzio": verzio,
            "parancs": os.path.isfile(os.path.expanduser(os.path.join("~", ".claude", "commands", "paros.md"))),
            "git": shutil.which("git") is not None}


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
    "ellenorzes": cmd_ellenorzes,
    "frappe-kerdesek": cmd_frappe_kerdesek, "frappe-lap": cmd_frappe_lap, "context-vazlat": cmd_context_vazlat,
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

    x = sub.add_parser("ellenorzes", help="a leírás ellentmondásai és figyelmeztetései (6: van hiba)")
    x.add_argument("feature", type=nev_tipus("FT"))
    x.add_argument("--elfogad", action="append", default=[], metavar="UJJLENYOMAT",
                   help="figyelem súlyú találat elfogadása (többször is adható)")
    x.add_argument("--mind", action="store_true", help="az elfogadott találatokat is mutatja")

    x = sub.add_parser("kapcsolat", help="kapcsolódás-ellenőrzés: a lépések és a teendő (6: van teendő)")
    x.add_argument("--url", help="a szerver címe, ha még nincs beállítás")

    sub.add_parser("paros-allapot", help="a PAROS Advisor telepítésének állapota (hálózat nélkül)")

    x = sub.add_parser("frappe-kerdesek", help="a 12 Frappe-téma kérdései (FT-vel: a feature állapota)")
    x.add_argument("feature", nargs="?", type=nev_tipus("FT"))

    x = sub.add_parser("frappe-lap", help="egy Frappe-téma rögzítése idézettel, vagy kihagyás")
    x.add_argument("feature", type=nev_tipus("FT"))
    x.add_argument("--tema", help="a téma kódja, pl. FR-ADAT")
    x.add_argument("--ertek-fajl", help="a téma értéke (szöveg) fájlból")
    x.add_argument("--idezet", action="append", help="szó szerinti idézet a kliens üzenetéből (többször is adható)")
    x.add_argument("--nem-relevans", action="store_true", help="a téma a kliensnél nem releváns (idézet kell)")
    x.add_argument("--kihagy", action="store_true", help="az egész Frappe-lap kihagyása")
    x.add_argument("--folytat", action="store_true", help="a kihagyás visszavonása")

    x = sub.add_parser("context-vazlat", help="a CONTEXT-vázlat Markdownban (determinisztikus)")
    x.add_argument("feature", type=nev_tipus("FT"))
    x.add_argument("--ki", required=True, help="a fájl helye (600-as jog)")
    x.add_argument("--feltolt", action="store_true", help="csatolja a munkához CONTEXT-vazlat.md néven")

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
    if a.parancs == "kapcsolat":
        return cmd_kapcsolat(a)
    if a.parancs == "paros-allapot":
        return cmd_paros_allapot(a)
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
    kilepes = eredmeny.pop("_kilepes", KILEP_SIKER) if isinstance(eredmeny, dict) else KILEP_SIKER
    print(szoveges(eredmeny) if a.szoveg else json.dumps(eredmeny, ensure_ascii=False, indent=2))
    return kilepes


if __name__ == "__main__":
    sys.exit(main())
