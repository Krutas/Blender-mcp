# Patikros — 2026-10-10

## Vykdyta

- Python 3.12, `python -m unittest discover -s tests -v`: **25 testai, visi praėjo**.
- Naudota MCP 1.12.4, Pydantic 2.11.7 ir pydantic-settings 2.10.1.
- Core: pasukimas/perkėlimas, zonos mastelis, nekintantis buferis ir jį kertantys
  trikampiai, neleistini receptai, per dideli poslinkiai, lokalios santraukos.
- Faktinių float32 koordinačių apvalinimo regresija: po Blender tipo apvalinimo
  per didelis poslinkis atmetamas bendru invariantų tikrintuvu.
- Eilė: tęstinumas, dublikatai, konfigūracijos pasikeitimas, nutrūkęs commit
  atsakymas, reconcile, seni/rankomis pakeisti scenos duomenys, momentinis
  pakeitimas tarp resume patikros ir snapshot, faktinio after hash auditas.
- Post-commit snapshot klaida išsaugo needs_review ir nekartoja deformacijos.
- Konfigūracijos netaisyklingas retry skaičius atmetamas iki DB sukūrimo.
- Tikras HTTP klientas su vietiniu testiniu API serveriu; įrodyta, kad modeliui
  nesiunčiama kambario pozicija ar tikro objekto vardas.
- Tikras MCP stdio SDK session, initialize/list_tools/call_tool su testiniu serveriu.
- CLI vykdymas atskiruose procesuose: pakartotinis startas nekeičia atliktų zonų.
- `compileall` sintaksės patikra.

## Nevykdyta šioje aplinkoje

- Tikras Blender: čia nėra Blender/bpy. Paruoštas `tests/blender_smoke.py`, kuris
  Blender aplinkoje tikrina tikrą geometriją, transformacijas, kontrolines kopijas,
  dublikato atmetimą ir rollback po imituotos įrašymo klaidos.
- Tikras Qwen3.5-4B / LM Studio / RTX 2070 bandymas.
- MCP Streamable HTTP adapterio end-to-end bandymas (stdio patikrintas).
- Fotorealistinė kokybė, PBR medžiagos, svetainės GLB eksportas ar našumas.

## Nepriklausoma kodo peržiūra

Atlikta atskira read-only kodo peržiūra. Keturi reikšmingi radiniai ištaisyti:
faktinių float32 koordinačių patikra, resume/snapshot tarpas, klaidingas before
hash after artefakte ir trupmeninis max_attempts. Pataisos padengtos regresiniais
testais; visa testų aibė po pataisų praėjo.

## Įgyvendinimo sprendimai

- Pradinis įrankių rinkinys ribotas struktūruotomis deformacijomis: savavališko
  LLM Python vykdymo nėra, todėl buferio taisyklę galima tikrinti programiškai.
  Kaina: sudėtingam formos kūrimui reikės papildomų patikrintų operacijų.
- Nekintanti vidinė siūlės juosta ir kertančių trikampių užrakinimas saugo
  buferio paviršių. Kaina: ties ribomis v0.1 detalizavimas konservatyvus.
- Vienas rašantis procesas, OS užraktas, SQLite DELETE journal ir FULL sync:
  paprastas failais perkeliamas state, nereikia WAL failų.
- Sąmoningai nėra pilnos savikirtimų patikros ar automatinio estetikos balo;
  `needs_review` nevadinamas galutine fotorealistine kokybe.
