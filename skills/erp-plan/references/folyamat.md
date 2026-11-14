# A munka folyamata (az ERP Plan kliensének)

Ez a leírás a kliens nyelvén mondja el, mi történik egy munkával. A skillek ezt használják, ha a felhasználó a folyamatról kérdez. Csak nyilvános tudás van benne.

## Mi az a munka

Egy munka egy fejlesztési igény, a felméréstől a lezárásig. Egy projekt több, egymáshoz tartozó munkát fog össze. Minden munkának van címe, azonosítója (FT-...) és állapota.

## Állapotok a kliens szavaival

| Állapot | Mit jelent |
|---|---|
| Vázlat | Még te írod a leírást. Kérdezel, válaszolsz, fájlt töltesz fel. |
| Interjú | A kikérdezés folyik. Az elemek és a részletes kérdések még hiányoznak. |
| Bírálatra vár | Beküldted. A mérnöknél van, nálad most nincs teendő. |
| Visszaküldve | A mérnök pontosítást kért. A jelölt pontokkal kezded. |
| Elfogadva | A mérnök elfogadta a leírást. A munka lezárult. |
| Lezárva | A munka véglegesen lezárult. Csak olvasható. |

## Ki lép melyik állapotban

- **Te (kliens):** Vázlat, Interjú, Visszaküldve. Ezekben írsz, kérdezel, javítasz.
- **A mérnök:** Bírálatra vár. Ő átnézi a leírást, kérdezhet, visszaküldheti pontosításra, vagy elfogadja.
- Elfogadva és Lezárva állapotban egyikötök sem ír elemet.

## Mi történik beküldés után

1. A mérnök átnézi az összefoglalót és az elemeket.
2. Kérdezhet. A kérdést ugyanitt kapod meg, és ugyanitt válaszolhatsz.
3. Visszaküldheti pontosításra. Ilyenkor a munka Visszaküldve állapotba kerül, és megmondja, mit kell pontosítani.
4. Elfogadhatja. Ekkor a munka Elfogadva lesz.
5. Az árról és a határidőről a mérnök beszél veled. A program és a skill ezeket nem mondja meg.

## Mit jelent a találat

A program néha ellentmondást talál a leírásban: például a határidő a kezdés előtt van, vagy egy idézet nem a te üzeneted. Ezeket a találatokat egyenként tisztázzátok.

- **Hiba:** a leírás önmagának mond ellent. Amíg van ilyen, a munkát nem lehet beküldeni.
- **Figyelem:** gyanús, de lehet rendben. Te döntesz. Ha jó így, elfogadhatod.

## Mit jelent a Frappe-lap

A Frappe-lap tizenkét fejlesztési témát tartalmaz (például adatok, jogosultságok, állapotok, listák, más rendszerekkel való kapcsolat). Ezekkel a rendszer nyelvére lehet lefordítani a leírást. A témák kihagyhatók; a kihagyott témát a mérnök később kérdezi meg.

## Hol marad az adat

- **A szerveren** marad: amit a felmérés során mondasz vagy írsz, és a feltöltött fájlok.
- **A gépeden** marad: a beállító fájl (csak neked olvasható), a fel nem töltött üzenetek átmeneti sora, és a többi fájlod.
- Részletek: a telepítési és adatkezelési leírás (docs/adatkezeles.md).

## Másik gépről folytatni

1. Telepítsd az ERP Plant az új gépen, és kapcsolódj a varázslóval.
2. Mondd: „Folytassuk.” vagy írd meg a munka címét.
3. A munka a szerverről olvasódik vissza. A beszélgetés régi fonalát a program adja vissza, nem a gép emlékezete.

## Mit érdemes tudni

- Ha a gépen nincs hálózat, a fel nem töltött üzenetek megmaradnak, és később feltölthetők.
- Egy napra a felmérésnek van korlátja. Ha eléred, a munka másnap folytatható.
