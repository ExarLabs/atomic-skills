# Helyi kipróbálás (ezen a Macen, push nélkül)

Ez az útmutató a `p1-erp-plan` ágról, a saját gépeden próbálja ki az ERP Plant a demó A kliens nevében. Nincs push: a publikus repóba és a honlapra nem kerül fel semmi.

## 1. Ellenőrzés

```
cd ~/Downloads/munka/ExarLabs/atomic-skills
git switch p1-erp-plan
sh scripts/ellenorzes.sh
claude plugin validate --strict .
```

A végén `ellenorzes: rendben` és `Validation passed` kell álljon.

## 2. Melyik kliens nevében

Add át a demó A kliens konfigját környezeti változóként. A konfigot nem kell megnyitni:

```
export ERP_PLAN_CONFIG="$HOME/.config/felmero/a/config.json"
```

A B kliens (`$HOME/.config/felmero/b/config.json`) ugyanígy használható. B-vel nem szabad látnod A munkáit. Egy terminálban mindig csak egy kliens legyen beállítva.

## 3. Telepítés: a kettő közül az egyik

Ne legyen egyszerre mindkettő: minden skill kétszer jelenne meg.

**A) Plugin, egy munkamenetre** (nem telepít tartósan):

```
mkdir -p ~/erp-plan-proba && cd ~/erp-plan-proba
claude --plugin-dir ~/Downloads/munka/ExarLabs/atomic-skills
```

A skillek neve: `/erp-plan:erp-plan`, `/erp-plan:erp-plan-munkak` és így tovább.

**B) Kézi másolás** a `~/.claude/skills/` alá:

```
python3 -I ~/Downloads/munka/ExarLabs/atomic-skills/scripts/telepit.py
ls ~/.claude/skills | grep erp-plan
```

Ezután a Claude Code-ot abban a terminálban indítsd, ahol az `ERP_PLAN_CONFIG` be van állítva: `claude`. A skillek neve: `/erp-plan`, `/erp-plan-munkak` és így tovább.

Az asztali alkalmazás Code fülén a terminálban beállított változó valószínűleg nem látszik. Ezt nem próbáltam ki. Ha ott kell, a program a `~/.config/felmero/config.json` fájlt keresi, és a demó A konfigját oda másolhatod: `cp ~/.config/felmero/a/config.json ~/.config/felmero/config.json`. Visszavonás: a másolat törlése.

Eltávolítás kézi telepítésnél: `rm -rf ~/.claude/skills/erp-plan ~/.claude/skills/erp-plan-*`.

## 4. Mondatok, ebben a sorrendben

Új beszélgetésben, a 3. lépés után:

1. `ERP Plan`: köszön, megmondja, hány munka vár rád, és a következő lépést.
2. `Mutasd a munkáimat.` Aztán: `És a lezártakat?` Majd: `Az összeset.`
3. `Új munkát nyitnék: a szállítólevelek rögzítése.` Válaszolj két-három kérdésre, majd: `Most hagyjuk abba.`
4. Új beszélgetésben: `Folytassuk a szállítóleveleset.` (A szerverről veszi fel a fonalat.)
5. `Január 11-én kezdenénk, a határidő január 4.` (Ellentmondás: rá kell kérdeznie, nem dönthet helyetted.)
6. `Mennyibe fog ez kerülni, és mikorra lesz kész?` (A rögzített mondat jön, ígéret nélkül.)
7. `Mit írtam a hozzáférésekről?` (A projekt anyagából válaszol, forrással.) Majd: `Milyen adatbázist használtok?` (Kimondja, hogy ezt nem tudja az anyagból, és felajánlja a továbbítást.)
8. `Készítsük elő fejlesztésre.` (Frappe-kérdések. A végén: `Készítsd el a leírást a fejlesztőnek.`)
9. `Telepítsd a PAROS Advisort.` (Ezen a gépen már telepítve van: ezt kell mondania, a verzióval, újratelepítés nélkül.)

## 5. Kapcsolódási varázsló (nincs konfig)

Új terminálban:

```
export ERP_PLAN_CONFIG="$HOME/erp-plan-proba/nincs.json"
```

Majd mondd: `Nem tudok kapcsolódni.` A program hozzáférés-kérő levelet ír, de nem küldi el; a levelet te küldöd. Ha megadsz egy portálcímet, a demón a `beallit` parancsot kapod. A jelszót nem kéri el.

## 6. Mit keress a kimenetben

- minden válasz végén `Következő lépés:` sor áll;
- a jelszó és a kulcs sehol nincs;
- a munkák a demón (`FP-...`, `FT-...`) megjelennek.

## 7. Mi nincs benne ebben a próbában

- Az eszközkódos belépés (kulcs egy rövid kóddal) a szerver oldalán még nincs élesítve. A hamis szerveres tesztek fedik.
- A push, a honlap élesítése és a PAROS Advisor módosítása külön gazdai igent kér.
