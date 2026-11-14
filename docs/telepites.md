# Telepítés

1. **Előfeltétel:** Claude Code telepítve és bejelentkezve; Python 3.9 vagy újabb (`python3 --version`); git.
2. **A skill letöltése:** `git clone https://github.com/ExarLabs/atomic-skills ~/atomic-skills`, majd `mkdir -p ~/.claude/skills && cp -R ~/atomic-skills/skills/feature-felmero ~/.claude/skills/`.
3. **Beállítás a terminálban (nem a Claude-beszélgetésben):** `python3 ~/.claude/skills/feature-felmero/felmero.py beallit --url <a portál címe>`. A program kérdezi a belépési adataidat, a jelszó nem látszik a képernyőn és nem kerül a parancssori előzményekbe.
4. **Ellenőrzés:** `python3 ~/.claude/skills/feature-felmero/felmero.py kivagyok`.
5. **Használat:** Claude Code-ban írd: "Új feature-t szeretnék felmérni", vagy `/felmero`.
6. **Másik gép:** ugyanez a 2-4. lépés. A beszélgetés a szerverről folytatódik.
7. **Frissítés:** `git pull` a klónozott mappában, majd a másolást ismételd meg.
8. **Eltávolítás:** a `~/.config/felmero` mappa és a `~/.claude/skills/feature-felmero` mappa törlése. A belépési adatokat a portálon is lehet visszavonni.
