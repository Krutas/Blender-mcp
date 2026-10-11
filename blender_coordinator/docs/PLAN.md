# Įgyvendinimo planas

1. core.py: zonos validacija, rigid transformacijos, griežtas JSON receptas,
   fiksuotos topologijos deformacijos. Testai pirmiausia: buferis, mastelis,
   rotation round trip, ribų trikampiai, nebaigtinis skaičius, didelis poslinkis.
2. store.py/runner.py: SQLite schema, viena eilė, patvarūs būsenų perėjimai,
   needs_review atskirai nuo reviewed. Testai: resume ir indeterminate apply.
3. model.py/mcp_client.py/blender_runtime.py: API ir MCP adapteriai,
   snapshot/hash, before/after blend, rollback, receipt. Testai su vietiniu
   HTTP serveriu, SDK stdio serveriu ir bpy (kai prieinamas).
4. CLI, demo, vietinės projekcijos, konfigūracija ir LT README.
5. Vykdyti visus testus, peržiūrėti kodą, supakuoti ZIP su šaltiniais,
   testais, instrukcijomis ir demonstraciniu rezultatu.

Darbas vykdomas čia pagal vartotojo „Paruošk koordinatorių“ ir prieš tai
patvirtintą projektą; papildomas projektavimo patvirtinimas nereikalingas.
