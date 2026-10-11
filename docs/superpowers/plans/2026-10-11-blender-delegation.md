# Blender Coordinator Delegation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Keep Blender writes and local-model requests sequential; no parallel scene writers.

**Goal:** Delegate small local surface jobs to the available 9B model while a coordinator builds, validates and presents a complete photorealistic room with a table and chair.

**Architecture:** Retain this repository as the MCP execution layer. Port the earlier `zonecoord` core into an optional coordinator package, adapt it to the actual MCP contract, and add explicit scene stages and review gates. The model proposes JSON; trusted code applies it.

**Tech Stack:** Python >=3.10, existing MCP SDK, stdlib SQLite/HTTP/JSON, Blender `bpy`, optional Pillow for technical previews, local OpenAI-compatible model server.

**Spec:** [Blender delegation specification](../specs/2026-10-11-blender-delegation.md). Read this and `AGENTS.md` before execution.

## Global Constraints

- Exactly one task, one local-model request and one scene writer at a time.
- Initial 9B profile: 4096 context, 768 output, 0.2 temperature, 2 attempts, 4 brushes, 32 samples, text-only.
- Physical fragment bounds: core ±10.77*s mm, visible ±12.77*s mm, read-only buffer 2*s mm, inner guard 1*s mm; stride 21.54*s mm.
- Full room stays at real scale in Blender; `scale` changes the work region only.
- Model responses are data, never executable Python. Photo quality requires visual acceptance.
- Preserve lazy/bounded MCP connections, readable error values and stdlib-only add-on dependencies.
- No unapproved object deletion or scene resets; no unattended mutations until the main-thread gate passes.
- Preserve prior checkpoint/receipt recovery; do not replay uncertain writes.
- Keep private endpoint configuration and generated scenes/runs out of Git.

## Review Focus

1. Timer stalled or task expired: no `bpy` work on socket thread or late execution of a cancelled queued call (Task 1).
2. MCP error envelopes and escaped stdout: show the real error; never accept a marker inside an error string as success (Task 2).
3. Context overflow/truncated JSON/unsupported vision: no scene write and bounded retry (Task 3).
4. Lost reply after commit, stale scene or duplicate coordinator: reconcile or stop, never double deformation (Task 4).
5. Scaled/rotated objects, sparse mesh or boundary-crossing triangles: correct units or explicit rejection; no silent seams (Tasks 2 and 5).

## File and dependency map

All paths below are **planned** except the existing repository files explicitly marked “modify.”

| Files | Responsibility |
|---|---|
| Modify `blender_mcp/addon.py`, `tests/test_addon_logic.py` | Main-thread dispatch and queued-call lifecycle |
| `blender_mcp/coordinator/{__init__,core,blender_runtime,mcp_client}.py` | Port archive geometry/runtime; adapt MCP envelopes |
| `blender_mcp/coordinator/{model,preview}.py` | Bounded worker proposals and optional local previews |
| `blender_mcp/coordinator/{store,runner,__main__}.py` | Durable state, orchestration, CLI and review |
| `blender_mcp/coordinator/{scene,evidence}.py` | Scene stages, construction scripts and milestone artifacts |
| `examples/coordinator/local.example.json`, `examples/coordinator/room-chair.example.json` | Endpoint placeholders, model profile, explicit prototype dimensions |
| `tests/test_coordinator_{geometry,mcp,model,recovery,scene,evidence}.py` | Isolated regression tests |
| `scripts/e2e_delegation.py` | Opt-in live disposable-scene acceptance run |
| Modify `pyproject.toml`, `.gitignore`, `README.md`; add `docs/COORDINATOR_LT.md` | Optional dependencies, artifact exclusions and operating instructions |

Dependency order: **1 → 2 → 3 → 4 → 5 → 6**. Each task ends with tests and a
small commit. The coordinator may prepare manifests while idle, but no local
worker receives downstream work before prerequisite review passes.

### Task 1: Make main-thread execution a reliable prerequisite

**Files:** modify `blender_mcp/addon.py`, `tests/test_addon_logic.py`, relevant threading paragraphs in `README.md`.

**Interfaces:** retain `run_on_main_thread(fn, timeout: float = 30.0)` and `pump_once() -> int`; extend `_Call` with atomic queued/running/completed/cancelled lifecycle. No wire-protocol change.

- [ ] Add `test_stalled_timer_never_executes_on_socket_thread`: worker thread submits a callable, no main-thread pump occurs, timeout is reported and callable never runs.
- [ ] Add `test_expired_queued_call_is_skipped_by_later_pump` and `test_started_call_timeout_is_not_replayed`: an expired queued call is cancelled atomically; already-running work may finish once and is reported as uncertain to the caller.
- [ ] Run `.venv/bin/python -m pytest tests/test_addon_logic.py -q`; new stalled-timer test must fail against the current fallback.
- [ ] Remove inline `bpy` execution, including the misleading `MAIN_THREAD_ONLY` branch. Execute directly only when already on the real main thread; otherwise enqueue. Make cancellation and claiming mutually exclusive. Keep the headless launcher's main-thread `pump_once()` loop.
- [ ] Replace obsolete inline-fallback expectations, run `.venv/bin/python -m pytest tests/ -q`, and verify all tests pass. Main-thread test records thread identity, not merely call count.
- [ ] Commit: `fix: enforce main-thread Blender command dispatch`. Reinstall the changed add-on only during the later live run; record running add-on version/source revision.

### Task 2: Port geometry and adapt the real MCP contract

**Files:** create coordinator `__init__.py`, `core.py`, `blender_runtime.py`, `mcp_client.py`; create `tests/test_coordinator_geometry.py`, `tests/test_coordinator_mcp.py`; modify `pyproject.toml` only if packaging requires it.

**Interfaces:** retain archive `validate_task(raw) -> dict`, `summarize(snapshot, task) -> dict`, `apply_recipe(snapshot, task, recipe) -> tuple[dict, dict]`, `zc_dispatch(request) -> dict`. Retain async `BlenderMCP.probe()`, `.snapshot(task)`, `.commit(task, recipe, expected, token)`, `.receipt(task, token)`; add `decode_execution_result(reply) -> dict` and async `.call_tool(name: str, arguments: dict)` for evidence tools.

- [ ] Recover the owner-held v0.1 archive named and hashed in the spec; verify its hash before porting source and its regression cases. Keep its geometry rules, receipts and unit conversion. Add module docstrings/future imports without blindly concatenating future imports inside generated code.
- [ ] Test `decode_execution_result`: native dictionary under outer `result` survives; `isError`/`is_error`, `ok:false`, malformed JSON and unexpected result types fail with the actual error text. Escaped `stdout` is not interpreted as a success payload.
- [ ] Run `.venv/bin/python -m pytest tests/test_coordinator_mcp.py tests/test_coordinator_geometry.py -q`; confirm new tests fail before the adapter exists.
- [ ] Configure stdio to use this repo's interpreter with `-m blender_mcp serve`, discover `blender_execute_code`, verify the `code` schema, and emit trusted code ending in `result = zc_dispatch(ZC_REQUEST)`. Decode outer JSON, then its `result`. Do not launch `uvx mcp-for-blender` or downgrade the repo to the archive's pinned SDK.
- [ ] Port geometry cases: exact buffer invariance including crossing triangles; round-trip rotated/translated parent transforms; non-unit scene scale conversion; rejected shear/reflection/unapplied object scale; sparse mesh, flipped normals, degenerate triangles and combined displacement overflow. Assert original UV/material/topology/transform preservation.
- [ ] Run both test files and the complete suite. Verify discovery with a dead add-on still completes without connecting. Commit: `feat: integrate local-zone coordinator with Blender MCP`.

### Task 3: Bound the 9B model workload

**Files:** create coordinator `model.py`, `preview.py`, `tests/test_coordinator_model.py`, `examples/coordinator/local.example.json`; modify `pyproject.toml` for an optional `coordinator` extra containing Pillow if needed.

**Interfaces:** retain async `LocalModel.probe() -> dict`, `LocalModel.propose(task, summary, images, error) -> dict`; add `build_messages(task, summary, images, error) -> list[dict]`. Config carries `model.name`, `context_tokens`, `max_output_tokens`, `send_preview`, `max_attempts`; exact model ID is operator-supplied from `/v1/models`.

- [ ] Add fake-HTTP tests asserting fresh two-message context, 768 output cap, 0.2 temperature, no room/global transforms, ≤32 samples and ≤4 brushes. Assert no concurrent requests, malformed/truncated replies never commit, and unsupported model IDs fail preflight.
- [ ] Add overflow test: with a tokenizer, >3072 input tokens is rejected before request; without one, server context error stops/reduces the fragment within two attempts and is not reported as a guaranteed token bound. Vision remains disabled unless explicitly capability-checked.
- [ ] Run `.venv/bin/python -m pytest tests/test_coordinator_model.py -q` and observe the missing behavior.
- [ ] Port the archive's data-only prompt/JSON validation. Implement the smaller profile and concise retry error. Keep model-family-specific thinking flags opt-in; preserve strict parsing when JSON response mode is unsupported. Log token usage, duration and rejection reason without secrets.
- [ ] Add example local-only endpoint placeholders, configured Blender port and 4-second connect timeout; no real remote addresses. Coordinate model/MCP/client/add-on deadlines explicitly: a client timeout never implies mutation cancellation.
- [ ] Run model tests and full suite; commit: `feat: add conservative 9B delegation profile`.

### Task 4: Persist review-gated tasks and recovery

**Files:** create coordinator `store.py`, `runner.py`, `__main__.py`, `tests/test_coordinator_recovery.py`; modify `.gitignore` for `runs/`, local endpoint config and generated Blender artifacts.

**Interfaces:** port archive async `run_queue(config, store, backend, model, root, limit=None) -> dict`, `reconcile(store, backend, task_id) -> dict`; retain task/config hashes and tokens. CLI: `python -m blender_mcp.coordinator {doctor,run,status,review,reconcile,retry}`; `run` supports `--config`, `--state`, `--limit`; `review` supports task ID and `--approve/--reject --note`.

- [ ] Test dependency blocking: `needs_review` does not unlock a dependent task; `reviewed` does. Reject duplicate IDs, dependency cycles and missing prerequisites before writes. Test rejection blocks dependants without pretending geometry was restored.
- [ ] Test lost commit response: one commit occurs, state becomes `uncertain`, restart does not call model/commit, matching receipt reconciles to `needs_review`. Missing receipt or mismatching scene requires inspection/restoration, not automatic replay.
- [ ] Test single-owner locking, config-hash mismatch, stale external edits, old checkpoint opened on resume and interrupted artifact writes. Each must stop or preserve the last durable state.
- [ ] Run `.venv/bin/python -m pytest tests/test_coordinator_recovery.py -q`; observe missing behavior, then port SQLite/write-ahead/receipt flow and add explicit dependency/review checks.
- [ ] Keep `retry --verified-scene` an explicit recovery action. A rejected shape needs a restored checkpoint and new revision/run; retain all evidence. Status output distinguishes applied geometry, pending review and accepted result.
- [ ] Run recovery tests and full suite; commit: `feat: add review-gated delegation and recovery`.

### Task 5: Build the room and chair under coordinator control

**Files:** create coordinator `scene.py`, `tests/test_coordinator_scene.py`, `examples/coordinator/room-chair.example.json`; extend `runner.py` to route trusted scene stages before local detail.

**Interfaces:** `validate_manifest(raw: dict) -> dict`, `build_stage_script(stage: str, manifest: dict, expected_scene_hash: str, token: str) -> str`, `plan_detail_tasks(manifest: dict, snapshot: dict) -> list[dict]`. Stage IDs: `room`, `table`, `chair-part-1`, `chair-complete`, `prepare-detail`, `appearance`; coordinator supplies these scripts, never the model. Stage commits use the same expected-scene hash/token/receipt discipline as detail commits.

- [ ] Add tests asserting RoomRoot `(0,0,0)`, metre-to-mm conversion, room → table → chair ordering, stable job-owned object names, duplicate-stage token reconciliation and preservation of unrelated objects.
- [ ] Add `test_region_scale_does_not_resize_room_or_chair`, boundary/mesh-preparation checks and rejection of contradictory dimensions or chair placement outside the manifest's room. Prototype dimensions must be explicitly marked as such.
- [ ] Run `.venv/bin/python -m pytest tests/test_coordinator_scene.py tests/test_coordinator_geometry.py -q`; confirm missing stage behavior.
- [ ] Implement parameterized floor/wall/window/table/chair scripts. Record a baseline save; use a job-owned collection, inspect existing objects and avoid factory reset. Define chair-part-1 as the seat/leg assembly so the first requested progress image has a stable milestone.
- [ ] Prepare only selected existing chair surfaces for the fixed-topology worker on a copy. Record transforms, material mapping and dense triangulation, then produce tasks using the spec's coordinate contract. Microtexture belongs in shared materials rather than arbitrary large mesh dents.
- [ ] Run scene/geometry tests and full suite; commit: `feat: add staged room and chair delegation`.

### Task 6: Deliver visual evidence and run live acceptance

**Files:** create coordinator `evidence.py`, `tests/test_coordinator_evidence.py`, `scripts/e2e_delegation.py`, `docs/COORDINATOR_LT.md`; extend `runner.py`, update `README.md` with actual supported commands after implementation.

**Interfaces:** async `capture_milestone(backend, task_id: str, output_dir: str, max_size: int = 768) -> dict` returns PNG path, render metadata, checkpoint path/host and status; `write_report(state_dir: str) -> dict` includes review decisions and incomplete stages.

- [ ] Test PNG and text-block handling, missing images, black-frame warnings and failed screenshots after successful geometry commit. No image failure may cause a repeated mutation or mark photo quality accepted. The chair-part-1 evidence must precede later scene work.
- [ ] Run `.venv/bin/python -m pytest tests/test_coordinator_evidence.py -q`; observe missing behavior, then implement persistence of MCP image bytes and metadata. Emit a user-visible milestone path; external message delivery is a separate explicitly authorized action.
- [ ] Provide Lithuanian operating/recovery instructions, example config and live script with required `--confirm-disposable-scene`. The existing `scripts/e2e_smoke.py` resets its target scene; never aim it at the user's unsaved production scene.
- [ ] Run `.venv/bin/python -m pytest tests/ -q`; all tests must pass before the live gate.
- [ ] On the authorized host, reinstall Task 1's add-on, run read-only doctor, and confirm the exact open disposable file/endpoint. Run `python -m blender_mcp.coordinator run --config <local-config> --state <new-run> --limit 1`; inspect and approve each required milestone before dependants execute.
- [ ] Exercise room → table → chair-part-1 screenshot → complete chair → one detail zone → two adjacent zones → shared materials/lighting. Test disconnect/reconcile on the disposable scene; confirm no duplicate deformation.
- [ ] Capture one whole-room image and one chair/detail close-up; inspect proportions, floor contact, visible seams, normals, shared texture scale, window lighting and render noise. Save final `.blend`, PNGs and run report. Leave photo quality pending until user review.
- [ ] Record actual model ID, context, versions, hardware, latency, usage and acceptance results; do not invent a performance target from 9B size alone. Commit: `feat: add delegation evidence and live acceptance workflow`.

## Handoff and definition of done

The implementation is ready only when all six task gates pass, restart/timeout
recovery is demonstrated, the first chair-part image is delivered, and the
full-scene/detail renders meet the user's visual requirement. If a live service
is unavailable, record the exact blocked gate; do not report live acceptance.

This commit publishes planning documents only. No coordinator has been
installed, no remote model has been called, and no Blender scene has been
modified as part of writing this plan.
