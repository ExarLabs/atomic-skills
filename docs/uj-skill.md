# Új skill hozzáadása

1. Hozz létre mappát: `skills/<név>/`, benne `SKILL.md` a kötelező fejléccel.
2. Ha a skillhez CLI tartozik, a tiszta részeit egységtesztekkel fedd le a `tests/` alatt.
3. Futtasd `sh scripts/ellenorzes.sh`: tesztek, tiltólista, és a `tests/test_szerkezet.py` ellenőrzi a fejlécet, a parancsokat és a közös blokkot.
4. Ellenőrizd a plugint: `claude plugin validate --strict .`. Figyelmeztetés nélkül kell átmennie.
5. A skill nevét vedd fel a README listájába.

## Fejléc-szabály

- Pontosan két kulcs van a fejlécben: `name` és `description`.
- A `name` egyezik a mappa nevével.
- A `description` egyetlen sor, kettős idézőjelben. A belsejében nincs kettős idézőjel és visszaper, legfeljebb 1000 karakter. A legfontosabb használati eset az elején áll, a magyar leírást az „English:” szó követi.

## Közös blokk

Ha a skill az ERP Plan szabályait használja, a törzsbe a közös szabályok blokkja (a `## Közös szabályok` címsortól a következő címsorig) szó szerint kerül, a `skills/erp-plan/SKILL.md`-ből. A blokkot nem fogalmazod át. A tesztek ellenőrzik, hogy minden skillben bájtra azonos, és hogy a kulcsmondatai benne vannak.

## Plugin és kézi telepítés

A `.claude-plugin/` szerkezet (plugin.json, marketplace.json) a Claude Code plugin-ellenőrzőjén átmegy. Új skill a `skills/` alá kerülve a plugin részévé válik. A kézi telepítő (`scripts/telepit.py`) a `skills/erp-plan*` mappákat másolja, ezért a nevüknek ezzel a prefixszel kell kezdődniük, ha a kézi telepítésben is látszanak.
