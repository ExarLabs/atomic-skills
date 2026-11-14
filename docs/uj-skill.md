# Új skill hozzáadása

1. Hozz létre mappát: `skills/<név>/`, benne `SKILL.md` a kötelező fejléccel (`name`, `description`).
2. Ha a skillhez CLI tartozik, a tiszta részeit egységtesztekkel fedd le a `tests/` alatt.
3. Futtasd `sh scripts/ellenorzes.sh`: tesztek, tiltólista, és a `tests/test_szerkezet.py` ellenőrzi a fejlécet és a parancsokat.
4. A skill nevét vedd fel a README listájába.

## Plugin-forma (nyitott kérdés)

A `.claude-plugin/` szerkezet (plugin.json, marketplace.json) a Claude Code aktuális dokumentációja szerint még nincs ellenőrizve. Amíg nincs, a telepítési útmutató tartalék útja (másolás a `~/.claude/skills/` alá) az elsődleges.
