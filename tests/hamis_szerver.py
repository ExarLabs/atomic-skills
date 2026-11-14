"""Hamis proto-szerver a parancsréteg teszteléséhez (csak 127.0.0.1, csak szabványos könyvtár).

Frappe-szerű REST: bejelentkezés, CSRF, /api/resource/<doctype>[/<név>], upload_file, /private/files/.
A rekordok memóriában élnek. Hibainjektálással tesztelhető a hálózati hiba (`drop`) és a félbemaradt
írás (`store_drop`: a szerver elmenti, de a választ már nem küldi el).
"""
import http.server
import json
import re
import socket
import threading
import urllib.parse

FELHASZNALO = "ugyfel-proba"
JELSZO = "proba-jelszo-1234"
CEG = "Hamis Cég Kft"
MAS_CEG = "Masik Cég Zrt"
SID = "hamis-munkamenet"
PREFIXEK = {"Felmero Projekt": "FP", "Felmero Feature": "FT", "Felmero Uzenet": "UZ",
            "Felmero Osszefoglalo": "OS", "Felmero Fajl": "FA", "File": "FILE"}
SZERVEZETI = ("Felmero Projekt", "Felmero Feature", "Felmero Uzenet", "Felmero Osszefoglalo", "Felmero Fajl")


class Kezelo(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self._kezel("GET")

    def do_POST(self):
        self._kezel("POST")

    def do_PUT(self):
        self._kezel("PUT")

    def log_message(self, *_args):
        pass

    def _kezel(self, metodus):
        sz = self.server.szerver
        resz = urllib.parse.urlsplit(self.path)
        ut = urllib.parse.unquote(resz.path)
        q = dict(urllib.parse.parse_qsl(resz.query))
        hossz = int(self.headers.get("Content-Length") or 0)
        torzs = self.rfile.read(hossz) if hossz else b""
        mod = sz.szabaly_keres(metodus, ut)
        sz.naplo.append((metodus, ut, torzs))
        if mod == "drop":
            self._megszakit()
            return
        status, fejlec, valasz = sz.feldolgoz(metodus, ut, q, torzs, self.headers)
        if mod == "store_drop":
            self._megszakit()
            return
        self.send_response(status)
        for kulcs, ertek in fejlec.items():
            self.send_header(kulcs, ertek)
        self.send_header("Content-Length", str(len(valasz)))
        self.end_headers()
        self.wfile.write(valasz)

    def _megszakit(self):
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


class HamisSzerver:
    def __init__(self):
        self.zar = threading.Lock()
        self.naplo = []
        self._szabalyok = []
        self._rekordok = {}
        self._fajlok = {}
        self._szamlalo = {}
        self._ido = 0
        self.http = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Kezelo)
        self.http.daemon_threads = True
        self.http.szerver = self
        self.url = "http://127.0.0.1:%d" % self.http.server_address[1]
        self.szal = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.szal.start()
        self._alap_adatok()

    def leallitas(self):
        self.http.shutdown()
        self.http.server_close()

    # Hibainjektálás és megfigyelés

    def hiba(self, metodus, prefix, mod):
        self._szabalyok.append((metodus, prefix, mod))

    def hiba_torol(self):
        self._szabalyok = []

    def szabaly_keres(self, metodus, ut):
        for m, prefix, mod in self._szabalyok:
            if m == metodus and ut.startswith(prefix):
                return mod
        return None

    def irasok(self):
        """A szerverhez érkezett írások (POST, PUT) a rekord-API-n."""
        return [n for n in self.naplo if n[0] != "GET" and n[1].startswith("/api/resource/")]

    # Adatkezelés

    def rekordok(self, dt):
        return self._rekordok.setdefault(dt, [])

    def rekord(self, dt, nev):
        for r in self.rekordok(dt):
            if r["name"] == nev:
                return r
        return None

    def tarol(self, dt, rekord):
        self._ido += 1
        rekord.setdefault("modified", "2026-11-14 10:%02d:%02d" % (self._ido // 60 % 60, self._ido % 60))
        self.rekordok(dt).append(rekord)
        return rekord

    def fajl_tarol(self, nev, bajt, file_nev=None):
        """Csatolt fájl a File doctype-ban; a file_url a letöltő útvonal."""
        file_url = "/private/files/" + (file_nev or nev)
        self._fajlok[file_url] = bajt
        self.tarol("File", {"name": nev, "file_url": file_url, "file_name": file_nev or nev})
        return file_url

    def _uj_nev(self, dt):
        pref = PREFIXEK.get(dt, "DOC")
        self._szamlalo[dt] = self._szamlalo.get(dt, 0) + 1
        return "%s-%05d" % (pref, 100 + self._szamlalo[dt])

    def _alap_adatok(self):
        self.tarol("User Permission", {"name": "UP-1", "user": FELHASZNALO, "allow": "CRM Organization",
                                       "for_value": CEG})
        self.tarol("Felmero Projekt", {"name": "FP-00001", "cim": "Próba projekt", "crm_organization": CEG,
                                       "allapot": "Aktív"})
        self.tarol("Felmero Projekt", {"name": "FP-00002", "cim": "Idegen projekt", "crm_organization": MAS_CEG,
                                       "allapot": "Aktív"})
        self.tarol("Felmero Feature", {"name": "FT-00001", "cim": "Próba munka", "projekt": "FP-00001",
                                       "crm_organization": CEG, "allapot": "Interjú", "elemek": [],
                                       "bizonyitekok": [], "hivatkozasok": [], "teljesseg_szazalek": 0,
                                       "uzenet_db": 1, "utolso_uzenet": "2026-11-14 09:00:00",
                                       "frappe_lap": None})
        self.tarol("Felmero Feature", {"name": "FT-00002", "cim": "Idegen munka", "projekt": "FP-00002",
                                       "crm_organization": MAS_CEG, "allapot": "Interjú", "elemek": [],
                                       "bizonyitekok": [], "hivatkozasok": [], "teljesseg_szazalek": 0,
                                       "uzenet_db": 0})
        self.tarol("Felmero Uzenet", {"name": "UZ-00001", "feature": "FT-00001", "sorszam": 1,
                                      "szerep": "kliens", "forras": "szoveg", "szerzo_nev": "Próba Ügyfél",
                                      "szoveg": "Havonta egyszer kézzel számolom újra a készletet.",
                                      "kliens_azonosito": "seed-1", "crm_organization": CEG,
                                      "projekt": "FP-00001", "creation": "2026-11-14 09:00:00"})
        self.tarol("Felmero Osszefoglalo", {"name": "OS-00001", "feature": "FT-00001", "verzio": 1,
                                            "uzenet_sorszamig": 1, "szoveg": "Próba összefoglaló.",
                                            "crm_organization": CEG, "projekt": "FP-00001",
                                            "creation": "2026-11-14 09:05:00"})
        self.fajl_tarol("FILE-00001", b"# Minta\n\nHavonta fut a folyamat.\n", "minta.md.txt")
        self.tarol("Felmero Fajl", {"name": "FA-00001", "fajl_nev": "minta.md", "projekt": "FP-00001",
                                    "feature": "FT-00001", "crm_organization": CEG, "tipus": "szoveg",
                                    "elsodleges_forma": "markdown", "markdown_file": "FILE-00001",
                                    "file": "FILE-00001", "atalakitas_allapot": "Nem kell",
                                    "atiras_allapot": "Nem kell", "creation": "2026-11-14 09:06:00"})

    # Kérések feldolgozása

    def feldolgoz(self, metodus, ut, q, torzs, fejlec):
        if ut == "/api/method/login":
            return self._belepes(torzs)
        if not fejlec.get("Cookie") or SID not in fejlec.get("Cookie"):
            return self._json(401, {"message": "Nincs bejelentkezve."})
        with self.zar:
            if ut == "/api/method/frappe.sessions.get_csrf_token":
                return self._json(200, {"message": "csrf-proba"})
            if ut == "/api/method/upload_file" and metodus == "POST":
                return self._feltoltes(torzs)
            if ut.startswith("/private/files/") and metodus == "GET":
                if ut not in self._fajlok:
                    return self._json(404, {"message": "Nincs ilyen fájl."})
                return 200, {"Content-Type": "application/octet-stream"}, self._fajlok[ut]
            if ut.startswith("/api/resource/"):
                return self._rekord_api(metodus, ut[len("/api/resource/"):], q, torzs)
        return self._json(404, {"message": "Ismeretlen végpont."})

    def _belepes(self, torzs):
        try:
            adat = json.loads(torzs.decode("utf-8") or "{}")
        except ValueError:
            adat = {}
        if adat.get("usr") != FELHASZNALO or adat.get("pwd") != JELSZO:
            return self._json(401, {"message": "Hibás belépési adatok."})
        fejlec = {"Content-Type": "application/json", "Set-Cookie": "sid=%s; Path=/" % SID}
        return 200, fejlec, json.dumps({"message": "Logged In", "full_name": "Próba Ügyfél"}).encode("utf-8")

    def _feltoltes(self, torzs):
        m = re.search(rb'filename="([^"]+)"', torzs)
        if not m:
            return self._json(400, {"message": "Hiányzik a fájl."})
        file_nev = m.group(1).decode("utf-8")
        if file_nev.lower().endswith(".md"):
            return self._json(417, {"message": "Csak JPG, PNG, GIF, PDF, TXT, CSV vagy Microsoft dokumentumokat tölthet fel."})
        start = torzs.index(b"\r\n\r\n", m.end()) + 4
        bajt = torzs[start:torzs.rindex(b"\r\n--")]
        nev = self._uj_nev("File")
        file_url = self.fajl_tarol(nev, bajt, file_nev)
        return self._json(200, {"message": {"name": nev, "file_url": file_url, "file_name": file_nev}})

    def _rekord_api(self, metodus, resz, q, torzs):
        if "/" in resz:
            dt, nev = resz.split("/", 1)
        else:
            dt, nev = resz, None
        szervezeti = dt in SZERVEZETI
        if metodus == "GET" and nev is None:
            sorok = self.rekordok(dt)
            szurok = json.loads(q.get("filters", "[]"))
            for mezo, op, ert in szurok:
                if op == "=":
                    sorok = [r for r in sorok if r.get(mezo) == ert]
                elif op == ">":
                    sorok = [r for r in sorok if r.get(mezo) is not None and r.get(mezo) > ert]
            if szervezeti:
                sorok = [r for r in sorok if r.get("crm_organization") in (None, CEG)]
            rendezes = q.get("order_by")
            if rendezes:
                mezo, _, irany = rendezes.partition(" ")
                sorok = sorted(sorok, key=lambda r: r.get(mezo) if r.get(mezo) is not None else 0,
                               reverse=(irany == "desc"))
            limit = int(q.get("limit_page_length", "100"))
            mezok = json.loads(q.get("fields", "[]"))
            kimenet = [{k: r[k] for k in mezok if k in r} for r in sorok[:limit]]
            return self._json(200, {"data": kimenet})
        if metodus == "GET":
            r = self.rekord(dt, nev)
            if r is None:
                return self._json(404, {"exception": "DoesNotExistError", "message": "Nincs ilyen rekord."})
            if szervezeti and r.get("crm_organization") not in (None, CEG):
                return self._json(403, {"exception": "PermissionError",
                                        "message": "Nincs jogosultságod: %s." % r["crm_organization"]})
            return self._json(200, {"data": r})
        adat = json.loads(torzs.decode("utf-8") or "{}")
        if metodus == "POST" and nev is None:
            if szervezeti and adat.get("crm_organization") not in (None, CEG):
                return self._json(403, {"exception": "PermissionError",
                                        "message": "Nincs jogosultságod: %s." % adat["crm_organization"]})
            uj = dict(adat)
            uj.pop("doctype", None)
            uj["name"] = self._uj_nev(dt)
            self.tarol(dt, uj)
            return self._json(200, {"data": uj})
        if metodus == "PUT" and nev is not None:
            r = self.rekord(dt, nev)
            if r is None:
                return self._json(404, {"exception": "DoesNotExistError", "message": "Nincs ilyen rekord."})
            if szervezeti and r.get("crm_organization") not in (None, CEG):
                return self._json(403, {"exception": "PermissionError",
                                        "message": "Nincs jogosultságod: %s." % r["crm_organization"]})
            r.update(adat)
            self._ido += 1
            r["modified"] = "2026-11-14 11:%02d:%02d" % (self._ido // 60 % 60, self._ido % 60)
            return self._json(200, {"data": r})
        return self._json(405, {"message": "Nem támogatott művelet."})

    def _json(self, status, adat):
        return status, {"Content-Type": "application/json"}, json.dumps(adat, ensure_ascii=False).encode("utf-8")
