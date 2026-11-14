# atomic-skills

<a href="https://exarlabs.com"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/exarlabs-logo-white.svg"><img src="assets/exarlabs-logo.svg" alt="ExarLabs" height="36"></picture></a>

Az ExarLabs készíti és tartja karban; ERPNext- és Frappe-szakértők (ERPNext-bevezetés, Frappe-fejlesztés; Frappe-partnerség folyamatban).

**Claude Code skillek az Atomi ügyfeleinek.** Első csomag: **ERP Plan**, a belépő az EXAR ERP-hez tartozó munkáidhoz: új munka, felmérés, kérdések a mérnöknek, és mindig megmondja a következő lépést.

> Verzió 0.2.0, előzetes. A kipróbálás meghívásos.

Ez a repó nyilvános: belső tartalom nem kerülhet bele. A kiadás előtti ellenőrzés (`scripts/tiltolista.py`) ezt kényszeríti ki.

## Skillek

| Skill | Mire való |
|---|---|
| `erp-plan` | a belépő: eligazít, válaszol, és megmondja a következő lépést |
| `erp-plan-munkak` | nyitott, lezárt és összes munka; új munka; folytatás; átnevezés; visszavonás |
| `erp-plan-felmeres` | kikérdezés egy igényről, egyszerre egy kérdéssel, szó szerinti idézetekkel |
| `erp-plan-ellenorzes` | a leírás ellentmondásainak felismerése és egyenkénti tisztázása |
| `erp-plan-frappe` | a részletes rendszer-kérdések, és a fejlesztésre kész leírás-vázlat |
| `erp-plan-kapcsolat` | kapcsolódás lépésenként: hozzáférés, belépés, kulcs, új gép |
| `erp-plan-paros` | a PAROS Advisor bemutatása és telepítése kérésre |

A parancssori program: `skills/erp-plan/erp_plan.py` (a régi `felmero.py` alias marad).

## Telepítés

Két út van: plugin (`/plugin marketplace add ExarLabs/atomic-skills`, majd `/plugin install erp-plan@atomic-skills`), vagy kézi másolás (`python3 scripts/telepit.py`, a skillek a `~/.claude/skills/` alá kerülnek). Részletek: [docs/telepites.md](docs/telepites.md).

Helyi kipróbálás push nélkül, egy kliens nevében: [docs/kiprobalas.md](docs/kiprobalas.md).

## Fejlesztés

```
python3 -m unittest discover tests
python3 scripts/tiltolista.py
claude plugin validate --strict .
```

Vagy egy paranccsal: `sh scripts/ellenorzes.sh`. Új skill: [docs/uj-skill.md](docs/uj-skill.md). Adatkezelés: [docs/adatkezeles.md](docs/adatkezeles.md).

A karbantartók gépén van egy helyi kiegészítő tiltólista (`scripts/tiltolista.local.txt`, nincs a repóban); a CI csak az általános listát (`scripts/tiltolista.txt`) futtatja.

## Védjegy

A Frappe és az ERPNext a Frappe Technologies Pvt. Ltd. védjegye. Ez a projekt nem áll kapcsolatban a Frappe Technologies-szal, és nem kapott tőle jóváhagyást. A nevek csak a munka leírására szolgálnak.

## Licenc

MIT, lásd [LICENSE](LICENSE).

## Az ExarLabsről

<a href="https://exarlabs.com"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/exarlabs-logo-white.svg"><img src="assets/exarlabs-logo.svg" alt="ExarLabs" height="48"></picture></a>

Ezt a projektet az [ExarLabs](https://exarlabs.com) készíti és tartja karban. ERPNext- és Frappe-szakértők vagyunk: ERPNext-et vezetünk be cégeknek, és Frappe-fejlesztést végzünk. A Frappe-partnerségünk folyamatban van. A Frappe és az ERPNext nevét itt csak a munkánk leírására használjuk; ez a projekt nem kapcsolódik a Frappe Technologies-hoz.

**Továbbiak az ExarLabstől**

- [exoskeleton-integrator](https://github.com/ExarLabs/exoskeleton-integrator): az AI Dev Exoskeleton, kiegészítve egy réteggel azoknak a csapatoknak, amelyek ügyfeleknek Frappe- és ERPNext-oldalakat építenek és módosítanak.
- [paros-advisor](https://github.com/ExarLabs/paros-advisor): tanácsadó, amely a saját jegyzetmappádból személyes rendszert épít, ahol AI-agentek dolgoznak és tanulnak.

Kapcsolat: [exarlabs.com](https://exarlabs.com)
