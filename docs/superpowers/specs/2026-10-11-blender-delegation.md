# Blender delegation specification

Status: agreed workflow consolidated into a proposed integration; not implemented by this documentation change.

## Goal and evidence

Build a room with windows, a table and a chair beside it, then refine local chair
surfaces with the existing small local model. The coordinator owns the scene;
the 9B worker receives one bounded fragment at a time. Photorealistic output is
the final acceptance requirement, not a claim made by a geometry check.

Sources inspected on 2026-10-11:

- `Krutas/Blender-mcp` at `d3aaf0d`: `AGENTS.md`, `README.md`,
  `blender_mcp/{server,client,addon}.py`, tests and `scripts/e2e_smoke.py`.
- Earlier `blender_koordinatorius_v0.1.zip`, SHA-256
  `2e73bafdff844f5f927b9e6a1b108106c9b0136d05605c8a2c69f69e9bf9166e`:
  `README_LT.md`, `docs/DESIGN.md`, `zonecoord/{core,model,mcp_client,runner}.py`.
- Later conversation decisions supersede the archive's 4B / 8192-token example:
  use the available 9B model gently, one request at a time; 4096-token initial
  context was reported in the previous delegation session. Reconfirm actual
  server settings during preflight. No live endpoint was tested for this plan.

## What exists and what is missing

| Component | Verified source behavior | Work required |
|---|---|---|
| This repository | Eight MCP tools over stdio; lazy TCP client; inspection, Python execution, screenshots, saves | Keep as execution/inspection layer |
| Archived coordinator | SQLite queue, bounded JSON brushes, geometry validation, scene hashes, before/after saves, commit receipts | Port into this package and adapt the MCP response contract |
| Room and furniture construction | Not provided by the archived deformation worker | Coordinator-controlled, parameterized construction scripts |
| Photo quality | Technical previews and lit-pixel warnings only | Shared PBR materials, lighting, final renders and visual review |
| Recovery | Archive has `running`, `uncertain`, `needs_review`, `reviewed`, `failed`, `rejected` states | Preserve receipts and make review a dependency gate |

Two concrete integration gaps must be addressed:

1. The archive calls `execute_blender_code`; this repo exposes
   `blender_execute_code(code, timeout_s=0.0)`. Its text block contains JSON
   `{ok, result, stdout, duration_ms}`. The archive searches raw text for a
   `ZC_RESULT:` marker; JSON-escaped stdout is not that raw marker stream.
   Prefer setting `result = zc_dispatch(...)` in trusted coordinator code and
   decoding the outer JSON before reading its `result` dictionary.
2. `addon.run_on_main_thread()` currently falls back to `call.run_once()` on
   the socket thread if the timer stalls. The lock prevents duplicate calls,
   but does not make `bpy` thread-safe. `MAIN_THREAD_ONLY` is empty and its
   handler branch also invokes inline. Resolve this before unattended writes.

## Ownership and execution route

| Role | Owns | Must not do |
|---|---|---|
| User | Brief, references, final photo quality acceptance | Re-enter the full brief for each fragment |
| Coordinator | Room coordinates, object placement, task queue, validation, execution, recovery and global renders | Treat a worker's prose as proof of success |
| Local 9B worker | One local surface proposal expressed as strict JSON data | Move furniture, redesign the room, change topology or submit executable Python |
| Blender MCP | Execute trusted coordinator scripts; return measurements and images | Plan the scene or judge photorealism |

Run the coordinator on the authorized WSL/control host that can reach both
the model API and Blender. Remote control is a way to launch/manage that host,
not an additional Blender protocol. Use existing Tailscale connectivity when
hosts differ; keep actual endpoints in local configuration. Do not publish
private addresses, credentials or absolute personal filesystem paths.

The model speaks OpenAI-compatible HTTP (`/v1/models`, `/v1/chat/completions`).
The coordinator starts **this repository's** `python -m blender_mcp serve` via
MCP stdio; that server connects to the Blender add-on's TCP port. The model API,
MCP stdio transport and add-on TCP socket are three different interfaces.
Default add-on port is 9876; the repository's prior host used 9877. Preflight
must inspect configuration, not assume either listener is the correct scene.

## Coordinates: scene first, local detail second

Establish `RoomRoot` at the room's floor origin, with Z up. Record room width,
depth, height, window locations, table and chair transforms in a scene manifest.
Use metric scene units; proposed default is one Blender unit = one metre.
Existing scene units must be read before conversion. Unknown room dimensions
may use explicitly labelled prototype values, never measurements inferred as fact.

The complete room remains at real scale in Blender. Never shrink the room to
the worker's cube. For each selected existing mesh fragment:

| Quantity | Agreed rule |
|---|---|
| Local origin | Fragment centre `(0,0,0)` |
| Editable core | `[-10.77*s, +10.77*s]` mm on each axis |
| Read-only outer buffer | `2*s` mm on each side |
| Visible region | `[-12.77*s, +12.77*s]` mm on each axis |
| Inner seam guard | Additional `1*s` mm inside the core remains fixed |
| Adjacent core centres | `21.54*s` mm apart |
| Initial displacement cap | `0.3*s` mm, an initial tuning value |
| Scale meaning | Changes the working region and allowed displacement, not object scale |

Let `c` be the fragment centre in object-local millimetres and `R` the
fragment rotation `Rz @ Ry @ Rx`. The archive uses physical local millimetres:
`p_fragment_mm = R.T @ (p_object_mm - c)` and
`p_object_mm = c + R @ p_fragment_mm`. If displaying normalized coordinates,
divide by `s`; do not feed normalized coordinates into the physical-mm recipe.
Let `k = 1000 * scene.unit_settings.scale_length` mm per Blender unit.
Use `p_object_mm = k * p_object_BU`; for world placement, compute
`p_world_BU = matrix_world @ (p_object_mm / k)` with homogeneous translation.
Do not apply a Blender-unit translation directly to millimetre coordinates. Require rigid world
transforms; apply scale on a working copy before detail work. Reject shear,
reflection and unsupported scale rather than silently deforming proportions.

The initial worker preserves topology, UVs, material slots and transforms.
It needs a prepared, sufficiently dense triangulated mesh, with no unsupported
modifiers or shape keys. Lock triangles crossing the core boundary, not only
vertices outside it. Use the archive limit of 200,000 vertices per object;
do not promise arbitrary dense-scene processing or full self-intersection detection.

## Small-model contract

Start with concurrency 1, context 4096, output cap 768 tokens, temperature 0.2,
and at most two proposal attempts per task. These are conservative initial
settings, not measured optimal values. Discover the exact model ID; do not
assume a Qwen variant or vision support from parameter count alone.

Each request starts fresh: short fixed instructions, task ID, local bounds,
material description, up to 32 local samples, and only the last concise error.
No global room image, world position, complete mesh, conversation history or
large tool catalogue. Start text-only. Add at most one local crop after vision
support and its token cost are verified. Cap brushes at 4 for this profile
(archive supports up to 16). Reject truncated output, tool-call output, unknown
fields, NaN/Infinity, wrong task ID and out-of-bounds operations.

Accepted response example (data only; values still require geometric validation):

```json
{"task_id":"chair-leg-001","brushes":[{"center_mm":[0,0,0],"radius_mm":4,"displacement_mm":[0,0,0.1]}],"note":"Smooth local curvature"}
```

The server's tokenizer/usage is authoritative. A character limit alone cannot
prove a 4096-token bound. Reserve 768 output tokens plus a 256-token margin;
reject requests above the remaining 3072 input tokens when a tokenizer is
available. Without one, keep the compact text-only profile, record usage,
handle context errors by shrinking the task, and make no hard token guarantee.

## Sequential scene workflow and acceptance gates

| Stage | Coordinator action | Evidence required before dependants start |
|---|---|---|
| 0: preflight | Probe model, MCP discovery, Blender status/versions, open file and units | Correct scene identified; baseline `.blend` saved; no writes on failure |
| 1: room | Build floor, walls, large windows and camera from manifest | Dimensions/axes checked; room checkpoint and preview |
| 2: furniture | Build table, then a chair beside it; keep stable names | Placement, floor contact and obvious collisions checked; first chair-part screenshot sent to user |
| 3: preparation | Prepare only selected chair mesh for local detail | Dense triangles, rigid transforms, consistent UV/material mapping |
| 4: detail | Snapshot → small-model JSON → validate → commit → read back | Buffer unchanged, no normal flips/degenerate triangles, receipt and checkpoint match |
| 5: appearance | Apply shared materials, window lighting and camera settings | Whole-scene preview plus chair/detail close-up reviewed |
| 6: final | Render accepted camera views; save scene and report | No visible seams, wrong proportions, floating objects, obvious intersections or texture-scale errors; user accepts photo quality |

Inspect existing scene objects before building anything. Construction must
touch only its job-owned collection and never call factory reset on the user's
scene. The first chair-part screenshot remains a milestone even when the room
is built first. Send one screenshot at the end of a task/milestone, not after
every modelling instruction. Archive technical projections are diagnostic;
they do not replace a real Blender render. Start previews at 768 pixels on the
long axis; final resolution and render budget are separately configured.

`needs_review` means geometry was committed but acceptance is pending. A
reviewed task may unlock its dependants. A rejection blocks them; marking
rejected does not undo geometry. Restore the recorded checkpoint, verify the
scene hash, and create a revised task/run before attempting different geometry.

Persist task ID, dependencies, parameters, config hash, scene/object hashes,
attempt count, stable commit token, receipt and artifact paths in SQLite plus
JSON reports. Save before/after `.blend` files on the Blender machine; save PNGs
and reports on the coordinator host and record which host owns each path.
Only one coordinator and one writer may own a scene. Stop if the scene changes
outside that writer's control.

A detail task retains the archive fields `id`, `object`, `center_mm`,
`rotation_deg`, `scale`, `max_move_mm`, `material`, `instruction`; add `kind`
(`detail` or `scene-stage`) and `depends_on` (task IDs). The coordinator also
stores `expected_scene_hash`, `commit_token` and checkpoint paths. Only the
local summary and task ID enter the model prompt. Unknown dependency IDs,
cycles and duplicate task IDs are configuration errors, detected before writes.

Timeout after submission means **uncertain**, not “nothing happened.” Reconcile
the persistent receipt and current scene before any retry. Never automatically
repeat a mutation after lost output. Unreachable Blender pauses the queue;
do not retry it in a tight loop. Surface actual MCP errors and render warnings.

## Completion boundary

The requested deliverable now is this specification and its delegation plan in
GitHub. Runtime integration, remote installation and live modelling are future
execution tasks. Passing repository tests does not prove 9B modelling quality,
GPU performance or photorealism. Those require the staged live acceptance run.
