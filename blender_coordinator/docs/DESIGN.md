# Vietinių zonų koordinatorius — v0.1

Patvirtintas pokalbio tikslas: vietinis 4B modelis detalizuoja tik vieną sritį;
visa scena lieka Blender. Naujai zonai naujas kontekstas. RTX 2070 8 GB,
pradinis 8192 tokenų langas, nuoseklus vykdymas.

Branduolio pusė 10.77*s mm, tik skaitomas buferis 2*s mm; matoma pusė
12.77*s mm. Tai vartotojo patvirtinti suapvalinti dydžiai, ne tiksliai 10 cm³.
Centras nurodomas objekto vietinėje sistemoje milimetrais, nepriklausomai nuo
objekto pasukimo ir perkėlimo kambaryje. Vietinių ašių pasukimas pasirenkamas.
Mastelis s didina darbo zoną ir leistinus poslinkius, o ne patį objektą.

Architektūra: Python CLI + SQLite užduočių eilė + OpenAI-compatible vietinio
modelio klientas + MCP stdio/HTTP klientas. MCP transportui izoliuota v1 SDK
priklausomybė. Modelis grąžina ribotą JSON deformacijų receptą, ne Python kodą.
Patikrintas koordinatoriaus kodas Blender viduje tikrina ir pritaiko receptą.

v0.1 operacija: kompaktiškai palaikomi deformavimo šepečiai esamame vientisame
trikampių tinklelyje. Topologija, UV, medžiagos, objektų transformacijos nekinta.
Tinklelis iš anksto turi būti pakankamai tankus; topologijos tankinimas,
retopologija, naujų objektų kūrimas ir tekstūrų generavimas į šią versiją neįeina.
Fiksuojamos ir trikampių, kertančių branduolį, viršūnės: paviršius buferyje nekinta.
Viduje poslinkis glotniai nyksta ties riba. Ribojamas judėjimas ir kraštinių
tempimas, atmetami normalės apsivertimai ir degeneracija. Savikirtimų pilno
aptikimo v0.1 nežada. Fotorealizmas yra žmogaus vizualinio priėmimo kriterijus,
ne automatinės geometrinės patikros išvada.

Prieš ir po pakeitimo .blend kontrolinės kopijos, tikslinių viršūnių atkūrimas
klaidos atveju, scenos/paviršiaus hash prieš įrašymą, patvarus įsipareigojimo
kvitas objekte. Nutraukto running ciklo pakartotinai automatiškai nevykdyti:
reconcile perskaito kvitą; kai jo nėra reikia peržiūrėti/atkurti kopiją.
Vienas procesas vienai DB (OS užraktas). DB konfigūracijos hash neleidžia tęsti
su tyliai pakeistomis zonos taisyklėmis.

Modeliui siunčiama vietinė santrauka, iki 64 mėginių ir vietinio fragmento
techninis trijų projekcijų vaizdas. Kambario vaizdas ir pilnas tinklelis
nepatenka į modelio kontekstą. Nuotraukos crop galima pridėti atskirai.

Pavyzdys: kėdės atrama kambaryje (2388,4790,0) mm, kojos fragmento centras
objekto atžvilgiu; kaimyninių branduolių žingsnis 21.54*s mm.

Patikros: vienetai ir pasukimai, tiksli buferio invariancija (ir kertantys
trikampiai), neleistinas JSON, NaN, stale snapshot, rollback, restart/resume,
modelio HTTP testas, MCP transporto testas ir tikras bpy scenos testas jei
prieinamas. Jokių fotorealizmo ar RTX greičio pažadų be realaus eksperimento.
