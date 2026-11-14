# atomic-skills

Az Atomi ügyfeleinek szánt Claude Code skillek. Minden skill a saját mappájában él (`skills/<név>/`), a közös részek (tesztek, tiltólista, dokumentáció) ebben a repóban vannak.

Ez a repó nyilvános: belső tartalom nem kerülhet bele. A kiadás előtti ellenőrzés (`scripts/tiltolista.py`) ezt kényszeríti ki.

## Skillek

- **feature-felmero**: fejlesztési igény kikérdezése az Atomi portálra. Telepítés: [docs/telepites.md](docs/telepites.md).

## Gyors telepítés

Lásd: [docs/telepites.md](docs/telepites.md).

## Fejlesztés

```
python3 -m unittest
python3 scripts/tiltolista.py
```

Vagy egy paranccsal: `sh scripts/ellenorzes.sh`. Új skill: [docs/uj-skill.md](docs/uj-skill.md).

A karbantartók gépén van egy helyi kiegészítő tiltólista (`scripts/tiltolista.local.txt`, nincs a repóban); a CI csak az általános listát (`scripts/tiltolista.txt`) futtatja.

---

Atomic skills for Atomi clients (Claude Code). Currently: feature-felmero. Setup: docs/telepites.md. Licence: MIT.
