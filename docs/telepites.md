# Telepítés

Két út van. Mindkettőhöz kell: Claude Code, bejelentkezve; Python 3.9 vagy újabb (`python3 --version`); és git a letöltéshez.

## 1. út: plugin

A Claude Code beszélgetésmezőjébe írd:

```
/plugin marketplace add ExarLabs/atomic-skills
/plugin install erp-plan@atomic-skills
```

A skillek nevei ekkor: `/erp-plan:erp-plan`, `/erp-plan:erp-plan-munkak` és így tovább. Frissítés: a `/plugin` menüben.

## 2. út: kézi másolás

```
git clone https://github.com/ExarLabs/atomic-skills ~/atomic-skills
python3 ~/atomic-skills/scripts/telepit.py
```

A program a hét `erp-plan*` mappát a `~/.claude/skills/` alá másolja, és JSON-ban kiírja, mit tett. Egy meglévő, azonos nevű mappát felülír. Másik célmappa: `--cel MAPPA`. A skillek nevei ekkor: `/erp-plan`, `/erp-plan-munkak` és így tovább.

A régi `feature-felmero` mappát a program csak a `--torol-regi` kapcsolóval törli; enélkül figyelmeztet.

Ne használd egyszerre a két utat: ekkor minden skill kétszer jelenik meg.

Frissítés kézi telepítésnél:

```
git -C ~/atomic-skills pull --ff-only
python3 ~/atomic-skills/scripts/telepit.py
```

## Kapcsolódás első alkalommal

Claude Code-ban írd: `ERP Plan`. A varázsló végigvezet a lépéseken: megnézi a beállítást, a hozzáférést, a belépést és a gép kulcsát. A jelszót a beszélgetésben nem kéri és nem írja be. A belépési adatot a terminálban adod meg a `beallit` paranccsal; a varázsló megmondja a pontos parancsot.

Az eszközkódos belépés (a gépre kért kulcs egy rövid kóddal) a szerver oldalán még nincs élesítve. A jelenlegi próbán a tőlünk kapott belépési adatot a terminálban adod meg.

## Másik gép

Ugyanaz a telepítés, és `ERP Plan` a kapcsolódással. A munkák a szerverről folytatódnak.

## Eltávolítás

- Plugin: a `/plugin` menüben a plugin eltávolítása.
- Kézi telepítés: `rm -rf ~/.claude/skills/erp-plan ~/.claude/skills/erp-plan-*`, és a `~/.config/felmero` mappa törlése.

Ha a hozzáférésed visszavonását is kéred, írj a `contact@exar.ro` címre.

Az adatkezelésről: [adatkezeles.md](adatkezeles.md).
