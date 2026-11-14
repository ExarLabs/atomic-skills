# Változásnapló

## 0.2.0 (előzetes)

- Új név: a plugin `erp-plan`, a repó és a marketplace `atomic-skills`.
- Hét skill: `erp-plan` (belépő), `erp-plan-munkak`, `erp-plan-felmeres`, `erp-plan-ellenorzes`, `erp-plan-frappe`, `erp-plan-kapcsolat`, `erp-plan-paros`.
- A `erp_plan.py` CLI új parancsai: `munkak`, `kovetkezo`, `ellenorzes`, `frappe-kerdesek`, `frappe-lap`, `context-vazlat`, `kapcsolat`, `kulcs-igenyles`, `paros-allapot`. A `felmero.py` alias marad.
- Kézi telepítő: `scripts/telepit.py` a `~/.claude/skills/` alá.
- A `feature-felmero` skill megszűnt; a `/felmero` parancs az `erp-plan-felmeres` skillre mutat.

## 0.1.0 (kiadás előtt, prototípus)

- A repó váza: skillek, CLI, tiltólista-ellenőrzés, tesztek.
- `feature-felmero` skill és `felmero.py` CLI, a `proto` (demó) adapterrel. Az `atomi` adapter váz.
