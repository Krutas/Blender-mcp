# Blender vietinių zonų koordinatorius — 0.1

Python programa vietiniam 4B modeliui ir Blender MCP. Ji dalina esamo objekto
detalizavimą į zonas, tikrina pakeitimus ir saugo tęsiamą darbų eilę.

**Tai koordinatoriaus MVP, ne ištreniruotas modelis ir ne fotorealistinės scenos
generatorius.** Demonstracija deterministinė, be AI. Tikro Qwen modelio kokybė,
RTX 2070 sparta ir darbas jūsų Blender scenoje turi būti patikrinti atskirai.

## Sutarti dydžiai

| Parametras | Reikšmė |
|---|---|
| Vietinis centras | `(0,0,0)` fragmento centre |
| Branduolys | kiekviena ašimi `[-10.77*s,+10.77*s]` mm |
| Buferis | papildomi `2*s` mm kiekvienoje pusėje, tik skaitymui |
| Matoma sritis | kiekviena ašimi `[-12.77*s,+12.77*s]` mm |
| Kaimyninių branduolių žingsnis | `21.54*s` mm |
| Pradinis kontekstas | 8192 tokenai, atsakymui iki 2048 |
| Vykdymas | viena užduotis vienu metu |

Dydžiai suapvalinti pagal pokalbį. Tiksliai 10 cm³ kubo kraštinė būtų
21.5443469 mm. `scale` keičia zonos dydį ir leistiną judėjimą, ne objektą.

`center_mm` yra objekto vietinės koordinatės fiziniais milimetrais.
`rotation_deg` yra fragmento ašių pasukimas objekto atžvilgiu, XYZ Euler laipsniais
(matrica Rz·Ry·Rx). Modelis gauna tik vietines koordinates; pasaulio pozicija,
kambario vaizdas ir pilnas tinklelis į modelio užklausą nepatenka.
Objekto ir jo tėvų perkėlimas bei pasukimas palaikomi. Mastelį prieš darbą reikia
pritaikyti (Apply Scale), kad world matricoje nebūtų scaling/shear/reflection.

## Kas veikia šioje versijoje

- Nuosekli SQLite eilė, žurnalas ir kiekvienos užduoties JSON artefaktai.
- Vietinio OpenAI-compatible API klientas (pvz., atitinkamai sukonfigūruotas LM Studio).
- MCP stdio ir Streamable HTTP adapteriai, įrankio schemos patikra.
- Modelio JSON deformavimo receptas: iki 16 kompaktiškų, glotnių šepečių.
- Bendras vientisas tinklelis, fiksuota topologija, UV, medžiagų priskyrimas.
- Buferis ir dar papildoma 1*s mm vidinė siūlės juosta nekinta. Trikampiai,
  kertantys branduolio ribą, taip pat užrakinami, kad nekistų paviršius buferyje.
- Poslinkio, kraštinių tempimo, trikampio degeneracijos ir normalės apsivertimo patikros.
- Scenos fingerprint palyginimas prieš commit; senos scenos resume atmetimas.
- `.blend` kopijos prieš ir po priimto pakeitimo, koordinatinis rollback įvykus klaidai.
- Patvarus commit kvitas Blender objekte: nutrūkęs atsakymas negali sukelti tylaus
  pakartotinio deformavimo.
- Vietinio fragmento trijų projekcijų PNG. Tai **techninis vaizdas be tekstūrų**, ne renderis.

**Apribojimai:** tik esamo tankaus trikampių tinklelio deformacija. Naujų objektų,
skylių, subdivision/retopologijos, PBR tekstūrų generavimo, pilnos savikirtimų
patikros ir automatinio fotorealizmo vertintojo nėra. Matomo buferio dydis negarantuoja,
kad paviršius bus pakankamai tankus. Jei zonoje nėra redaguojamų viršūnių,
koordinatorius sustoja. Medžiagos ir tekstūrų koordinatės paveldimos; neatkuriamos
atskirai kiekvienam kubeliui. Šiai versijai vienas objektas iki 200 000 viršūnių.

## 1. Greitas bandymas be Blender ir be modelio

Reikia Python 3.10 ar naujesnio. Išarchyvuokite ir terminale pereikite į projekto katalogą.

```bash
python -m zonecoord demo --state runs/demo
python -m zonecoord status --state runs/demo
```

Demo veikia be papildomų paketų; PNG peržiūroms reikia Pillow. Bus apdirbtos dvi
gretimos tos pačios kojos paviršiaus zonos ir būsena `needs_review: 2`.
Pakartojus komandą jos nebus dar kartą deformuojamos. Tai nėra fotorealizmo testas.

## 2. Priklausomybės tikram darbui

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m zonecoord --help
```

Linux / WSL:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m zonecoord --help
```

Toliau `python` reiškia šios virtualios aplinkos Python. MCP SDK ir Pydantic
versijos fiksuotos dėl suderinamumo. Į šią aplinką nereikia diegti PyTorch ar
modelio svorių: modelis veikia atskirame serveryje. Blender pusėje papildomų
Python paketų nereikia.

## 3. Blender scena ir MCP

Reikia įdiegto ir paleisto Blender MCP priedo bei su juo suderinamo serverio.
Oficialus šio bendruomenės projekto šaltinis:
https://github.com/ahujasid/mcp-for-blender

`examples/local.json` numato `uvx mcp-for-blender`. Jei turimas paketas vadinasi
`blender-mcp`, konfigūracijoje pakeiskite `args`. Vykdomo įrankio vardas numatytas
`execute_blender_code`; `doctor` patikrina jo schemą. Naudokite vieną suderintą
serverio/priedo versiją. MCP priedą paleiskite tame kompiuteryje, kur veikia Blender.

Pirmai scenai galima sugeneruoti bandymo koją, kurios kėdės tėvinis objektas yra
kambario `(2388,4790,0)` mm taške ir pasuktas 25°:

```bash
blender --background --factory-startup --python examples/create_blender_demo.py -- --output leg_demo.blend
```

Atidarykite `leg_demo.blend` Blender programoje ir įjunkite MCP ryšį.
Tai koordinatinis testas, ne pilna kėdė ar kambarys. Skriptas neperrašo esamo
to paties pavadinimo failo. Jei `blender` nėra PATH, naudokite pilną programos kelią.

Savo objektui: dirbkite su išsaugota projekto kopija; Object Mode; vienam objektui
atskiras mesh; Apply Scale; pritaikyti modifieriai; nėra shape keys; trianguliuota,
pakankamai tanki geometrija. Globalių transformacijų vykdymo metu nekeiskite.

## 4. Modelis ir pirmas gyvas ciklas

Paleiskite Qwen3.5-4B Q4 modelį su vaizdų palaikymu vietiniame serveryje.
Serveryje nustatykite 8192 kontekstą, vieną vienalaikę užklausą. Modelio API
ir Blender adresai konfigūruojami, prie konkretaus produkto nepririšti.

Redaguokite `examples/local.json`:

- `model.base_url`: API bazė su `/v1`, pvz. `http://127.0.0.1:1234/v1`.
- `model.name`: **tikslus** jūsų serverio `/v1/models` grąžinamas id.
- `model.send_preview`: siųsti lokalų techninį vaizdą; be vision palaikymo `false`.
- `model.disable_thinking`: siunčia `chat_template_kwargs.enable_thinking=false`.
  Jei serveris šio lauko nepriima, nustatykite `false`, o samprotavimą išjunkite
  pačiame serveryje. Taip pat galima išjungti `json_mode`, jei serveris nepalaiko
  `response_format`; atsakymo JSON patikra vis tiek privaloma.
- `tasks`: objektas, jo fragmento centras, pasukimas, mastelis, instrukcija.
- `reference_image`: pasirenkama tik šiam fragmentui skirta nuotraukos iškarpa;
  kelias skaičiuojamas nuo konfigūracijos failo. Visos kambario nuotraukos nesiųsti.

```bash
python -m zonecoord doctor --config examples/local.json
python -m zonecoord run --config examples/local.json --state runs/chair01 --limit 1
python -m zonecoord status --state runs/chair01
```

`doctor` tik skaito sceną ir tikrina jungtis; API pateikia modelių vardus.
`run` jau keičia nurodyto objekto geometriją. Pirmą kartą naudokite `--limit 1`.
Konteksto tokenų sąnaudos tik apytiksliai ribojamos užklausos ilgiu ir vaizdų
dydžiu; tikras tokenizatorius ir konteksto paskyrimas priklauso nuo serverio.
Nutrauktas/nebaigtas modelio atsakymas atmetamas. 8 GB tinkamumas čia neišmatuotas.

HTTP MCP konfigūracijos alternatyva (`mcp` blokas):

```json
{
  "transport": "http",
  "url": "http://127.0.0.1:8000/mcp",
  "token_env": "BLENDER_MCP_TOKEN",
  "execute_tool": "execute_blender_code",
  "timeout_seconds": 180
}
```

Tai **MCP Streamable HTTP adresas**, ne Blender priedo TCP socket adresas.
API slaptažodžiai skaitomi tik iš `LOCAL_MODEL_API_KEY` ir `BLENDER_MCP_TOKEN`
aplinkos kintamųjų; nelaikykite jų konfigūracijoje. Paprastą HTTP naudokite tik
patikimame vietiniame/tunelio ryšyje.

## 5. Rezultato priėmimas ir tęsimas

`needs_review` reiškia: geometrija patikrinta ir pritaikyta, vizualinė kokybė dar
nepatvirtinta. Atidarykite objekto zoną Blender, tikrinkite jos paviršių, bendrą
medžiagą ir renderį. Techniniai PNG nerodo fotorealistinės kokybės.

```bash
python -m zonecoord review leg-001 --state runs/chair01 --approve --note "Patikrintas paviršius ir renderis"
python -m zonecoord run --config examples/local.json --state runs/chair01 --limit 1
```

Be `--limit` eilė gali tęsti geometriškai priimtas zonas, nors jų vizualinė būsena
dar `needs_review`. `--reject` pažymi atmetimą ir blokuoja tęsimą, tačiau **neatšaukia
jau įrašytos geometrijos**. Norint perdaryti po atmetimo, atkurkite tinkamą kopiją
ir pradėkite naują state katalogą su pakoreguota užduotimi.

Kopijos `zc-<token>-before.blend` ir `zc-<token>-after.blend` saugomos šalia
atidaryto Blender failo **Blender kompiuteryje**. Pradinis failas neperrašomas.
Po Blender perkrovimo atidarykite paskutinę teisingą `after.blend` kopiją;
atidarius seną pradinę sceną koordinatorius atsisakys tęsti. Kol Blender veikia,
jo atmintyje jau yra priimti pakeitimai.

`running` po avarijos arba `uncertain` po ryšio klaidos:

```bash
python -m zonecoord reconcile leg-001 --config examples/local.json --state runs/chair01
```

Jeigu objekte yra atitinkamas commit kvitas ir hash sutampa, būsena atkuriama į
`needs_review`. Jei kvito nėra, patikrinkite sceną ir kontrolines kopijas.
Tik įsitikinę, kad saugu kartoti:

```bash
python -m zonecoord retry leg-001 --state runs/chair01 --verified-scene
```

Nepavykęs receptas automatiškai bandomas iki `max_attempts` kartų, perduodant
trumpą klaidą. Kiekvienas naujas bandymas gauna šviežią kontekstą. Po `failed`
vykdymas sustoja ties ta zona. Pakeitus konfigūraciją reikia naujo state katalogo:
taip nepakeičiamos tęsiamo eksperimento taisyklės nepastebimai.

## Testai

```bash
python -m unittest discover -s tests -v
blender --background --factory-startup --python tests/blender_smoke.py
```

Pirma komanda: tikra vietinė HTTP užklausa, tikras MCP stdio testinis serveris,
geometrijos ir būsenų testai. MCP testas praleidžiamas, jei SDK neįdiegtas.
Antra komanda: tikras Blender testas atskiroje laikinoje scenoje, įskaitant
kopijas, užrakintą buferį ir rollback. Ji reikalauja įdiegto Blender.
Patikrų būklė pateikta `docs/VALIDATION.md`.

## Plėtra fotorealizmui

Tolimesni moduliai gali pridėti realias izoliuoto fragmento Blender renderio
peržiūras, parametrinius bevel/jungčių receptus ir bendrų PBR medžiagų biblioteką.
Kiekvienai naujai operacijai būtina ribų ir geometrijos patikra. Savavališko
modelio Python kodo vykdymas nepakeičia ribų kontrolės ir čia nenaudojamas.

Techniniai šaltiniai (tikrinta 2026-10-10):
- https://github.com/ahujasid/mcp-for-blender
- https://github.com/modelcontextprotocol/python-sdk/tree/v1.12.4
- https://huggingface.co/Qwen/Qwen3.5-4B
