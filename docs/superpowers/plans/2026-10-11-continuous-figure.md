# Continuous Figure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the intersecting-primitive body of `scripts/model_photoreal_figure.py` with one continuous armature-skinned surface, and rebuild the head as one lofted mesh with real facial structure, in the reference pose and outfit.

**Architecture:** A pure-Python package `scripts/figure/` holds every number and every piece of geometry math, with no `bpy`, `bmesh` or `mathutils` import anywhere in it — which is what lets the whole thing be tested under `pytest` with no Blender present. `scripts/build_figure.py` is the only file that touches `bpy`; it assembles the package's output into objects, adds modifiers, lights and cameras, and renders. The mesh is authored directly in the final pose and the armature bones are placed in that same pose, so there is no forward-kinematics solve to get wrong.

**Tech Stack:** Python >=3.10, `pytest` (no Blender needed for tests), Blender 5.2.2 LTS driven headless via `blender.exe -b -P` through WSL interop. No new dependencies.

**Spec:** [docs/superpowers/specs/2026-10-11-continuous-figure-design.md](../specs/2026-10-11-continuous-figure-design.md). Read it and `AGENTS.md` before executing.

## Global Constraints

- Every module begins with `from __future__ import annotations` and a docstring explaining the *why*, per `AGENTS.md`.
- `scripts/figure/*.py` imports only the Python standard library. No `bpy`, no `bmesh`, no `mathutils`. Vectors are 3-tuples of float.
- All anthropometric fractions and joint targets live in `scripts/figure/anatomy.py` and nowhere else.
- The seven joint target coordinates carry over from `scripts/model_photoreal_figure.py` **unchanged**. Values are given in Task 2.
- `scripts/model_photoreal_figure.py` and `scripts/model_seated_figure.py` are not modified. This work is a new build alongside them.
- The pose is asymmetric (head tilt `(0.05, 0.08, 0.05)`, one eye closed, tongue forward). Only the paired limb targets are mirrored by side. Nothing else may be.
- Materials, lighting, cameras and render settings are unchanged from `model_photoreal_figure.py`. Values are given in Task 12.
- Run tests with `.venv/bin/python -m pytest tests/ -q` from the repo root. Run the build with the Blender invocation in Task 7.
- Each task ends with a commit. Do not batch commits.

## Review Focus

Five failure modes the spec implies that no task's happy-path test covers. Each has a test, in the task named.

1. **A body vertex beyond the end of its chain** — a hand vertex past the wrist, or a foot vertex past the ankle. Weighting must clamp to the terminal bone, never extrapolate into negative weights or a division by zero.
2. **Coincident joints.** If two targets land on the same point (a degenerate pose edit), chain length is zero and every arc-length parameter divides by zero. The rig must reject it with a named error, not produce NaN weights that render as an invisible or exploded body.
3. **Whole-figure mirroring.** The obvious shortcut for side `L`/`R` is to negate `x` on every coordinate. That also negates the head tilt, the wink and the tongue, producing a subtly wrong figure that still renders plausibly and is easy to miss.
4. **A ring whose cap radius is zero**, or a loft with a single-ring path. This yields degenerate faces with zero area and duplicated verts, which shade as black spikes under Cycles SSS.
5. **A boolean that returns an empty or inverted mesh.** The eye-socket cut is the one place where a partial failure still yields a renderable object, so it must raise rather than return a wrong mesh that only shows up as an unlit face in the final render.

---

### Task 1: Tuple vector helpers

**Files:**
- Create: `scripts/figure/__init__.py`
- Create: `scripts/figure/vector.py`
- Test: `tests/figure/test_vector.py`

**Interfaces:**
- Consumes: nothing.
- Produces, all in `figure.vector`: `add(a, b) -> tuple`, `sub(a, b) -> tuple`, `scale(a, s) -> tuple`, `dot(a, b) -> float`, `cross(a, b) -> tuple`, `length(a) -> float`, `norm(a) -> tuple`, `lerp(a, b, t) -> tuple`, `closest_point_on_segment(p, a, b) -> tuple`, `dist(a, b) -> float`, `lerp_chain(points, t) -> tuple` where `points` is a list of 3-tuples of **arc lengths** and `t` is a normalized position along the whole polyline.

- [ ] **Step 1: Write the failing tests**

```python
def test_norm_of_zero_vector_returns_unit_x():
    assert vector.norm((0.0, 0.0, 0.0)) == (1.0, 0.0, 0.0)

def test_closest_point_on_segment_clamps_to_endpoints():
    a, b = (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)
    assert vector.closest_point_on_segment((-1.0, 2.0, 0.0), a, b) == (0.0, 0.0, 0.0)
    assert vector.closest_point_on_segment((2.0, 2.0, 0.0), a, b) == (1.0, 0.0, 0.0)

def test_closest_point_on_segment_projects_interior_point():
    a, b = (0.0, 0.0, 0.0), (2.0, 0.0, 0.0)
    assert vector.closest_point_on_segment((1.0, 5.0, 0.0), a, b) == (1.0, 0.0, 0.0)

def test_closest_point_on_degenerate_segment_returns_that_point():
    a = b = (0.3, 0.4, 0.5)
    assert vector.closest_point_on_segment((9.0, 9.0, 9.0), a, b) == a

def test_lerp_chain_interpolates_within_a_segment():
    pts = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 4.0, 0.0)]
    assert vector.lerp_chain(pts, 0.25) == (1.0, 0.0, 0.0)
    assert vector.lerp_chain(pts, 0.5) == (2.0, 0.0, 0.0)
    assert vector.lerp_chain(pts, 0.75) == (2.0, 2.0, 0.0)

def test_lerp_chain_clamps_outside_zero_to_one():
    pts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    assert vector.lerp_chain(pts, -0.5) == (0.0, 0.0, 0.0)
    assert vector.lerp_chain(pts, 2.0) == (1.0, 0.0, 0.0)
```

`test_norm_of_zero_vector_returns_unit_x` is a deliberate choice, not an oversight: normalizing must never raise or return NaN, because a zero-length difference vector is reachable from any degenerate input and the callers have no way to distinguish it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/figure/test_vector.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'figure'`.

- [ ] **Step 3: Add `tests/figure/helpers.py`**

Several tasks' tests need the same measurement helpers, and defining them once
avoids four subtly different copies of "area of a face". Create
`tests/figure/helpers.py` with `polygon_area_3d(face, verts) -> float` (magnitude
of the summed cross products, so it is correct for faces that are not planar),
`mean_ring_radius(row) -> float`, `ring_rows(part) -> list[list[tuple]]` (groups a
part's verts into rings using its recorded `ts`), and
`mesh_manifold_edge_count(mesh) -> int` (edges shared by exactly two faces).

- [ ] **Step 4: Add `tests/conftest.py` so the package is importable**

The package lives under `scripts/`, which is not on `sys.path` and is not the repo root. Create `tests/conftest.py` inserting the repo's `scripts` directory onto `sys.path`:

```python
"""Put ``scripts/`` on the path so ``figure`` imports from tests.

The figure package deliberately lives under ``scripts`` because it is loaded by
Blender's ``-P``, which runs the entry point as ``__main__``. pytest's rootdir
is the repo root, so without this the package would be unimportable from tests.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
```

`scripts/figure/__init__.py` holds a docstring only, no imports, so that importing the package never drags in a submodule a given test does not want.

- [ ] **Step 4: Re-run to confirm the failure is now about the missing functions**

Run: `.venv/bin/python -m pytest tests/figure/test_vector.py -q`
Expected: `AttributeError: module 'figure.vector' has no attribute 'norm'`.

- [ ] **Step 5: Implement `scripts/figure/vector.py`**

Every function takes and returns 3-tuples. `norm` returns `(1.0, 0.0, 0.0)` when `length(a) == 0.0`. `closest_point_on_segment` returns `a` unchanged when `a == b` rather than dividing by zero. `lerp_chain` precomputes cumulative segment lengths, clamps `t` to `[0.0, 1.0]` before use, and walks the segment list once; it does not binary-search, because the chains are short (four bones) and a linear walk keeps the arithmetic obvious.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/figure/test_vector.py -q`
Expected: PASS, 7 tests.

- [ ] **Step 7: Run the full suite to confirm nothing broke**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: the existing 45 tests still pass.

- [ ] **Step 8: Commit**

```bash
git add scripts/figure/__init__.py scripts/figure/vector.py tests/conftest.py tests/figure/helpers.py tests/figure/test_vector.py
git commit -m "feat: add tuple vector helpers for Blender-free figure math"
```

---

### Task 2: Anatomy constants and joint targets

**Files:**
- Create: `scripts/figure/anatomy.py`
- Test: `tests/figure/test_anatomy.py`

**Interfaces:**
- Consumes: nothing.
- Produces, in `figure.anatomy`, all as module-level floats: `H`, `HEAD_H`, `HEAD_W`, `HEAD_D`, `NECK`, `TRUNK`, `THIGH`, `CALF`, `FOOT_L`, `SHLD_W`, `HIP_W`, `HIP_D`, `UPARM`, `FOREARM`, `HAND_L`, `HAND_W`, `HIP_H`, `SHOULDER_Z`, `NECK_TOP_Z`, `HEAD_CZ`, `VERTEX_Z`, `CHIN_Z`; and these 3-tuples: `HIP`, `KNEE`, `ANKLE`, `SHOULDER`, `ELBOW`, `WRIST`, `HEAD`, `HEAD_TILT`. Also `SIDE_SIGN = {"L": 1.0, "R": -1.0}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_stature_and_limb_fractions_match_the_existing_build():
    assert anatomy.H == 1.68
    assert anatomy.THIGH == 0.245 * anatomy.H
    assert anatomy.CALF == 0.246 * anatomy.H
    assert anatomy.UPARM == 0.186 * anatomy.H
    assert anatomy.FOREARM == 0.146 * anatomy.H

def test_derived_heights_are_consistent():
    assert anatomy.SHOULDER_Z == pytest.approx(anatomy.HIP_H + anatomy.TRUNK)
    assert anatomy.NECK_TOP_Z == pytest.approx(anatomy.SHOULDER_Z + anatomy.NECK)
    assert anatomy.VERTEX_Z == pytest.approx(anatomy.NECK_TOP_Z + anatomy.HEAD_H)

def test_chin_sits_below_the_neck_top():
    assert anatomy.CHIN_Z < anatomy.NECK_TOP_Z

def test_solved_limb_lengths_hold():
    for side, sx in anatomy.SIDE_SIGN.items():
        hip = anatomy.hip_joint(side)
        knee = anatomy.knee_joint(side)
        ankle = anatomy.ankle_joint(side)
        shoulder = anatomy.shoulder_joint(side)
        elbow = anatomy.elbow_joint(side)
        wrist = anatomy.wrist_joint(side)
        assert dist(hip, knee) == pytest.approx(anatomy.THIGH, rel=0.001)
        assert dist(knee, ankle) == pytest.approx(anatomy.CALF, rel=0.001)
        assert dist(shoulder, elbow) == pytest.approx(anatomy.UPARM, rel=0.001)
        assert dist(elbow, wrist) == pytest.approx(anatomy.FOREARM, rel=0.001)
```

`rel=0.001` is the 0.1% the commit message records as the achieved accuracy. This test is the regression guard for the whole design: if a later edit perturbs any target, the figure silently loses correct limb proportions and the render will not show it clearly.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/figure/test_anatomy.py -q`
Expected: `ModuleNotFoundError: No module named 'figure.anatomy'`.

- [ ] **Step 3: Implement `scripts/figure/anatomy.py`**

Copy the fractions and derived heights verbatim from `scripts/model_photoreal_figure.py` lines 48-73. Copy the seven joint targets verbatim from lines 252-267. Add `CHIN_Z = NECK_TOP_Z - 0.030`.

Add the per-side accessors the test uses. Each multiplies only the `x` component of the unsided target by the side sign and leaves `y` and `z` alone — this is the fix for Review Focus item 3, and it lives here so no later task can get it wrong:

```python
def hip_joint(side: str) -> tuple[float, float, float]:
    """Per-side hip. The base HIP is centred at x=0; each side offsets outward
    by a fixed fraction of hip width, matching the existing build."""
```

`SHOULDER` is stored unsided at `SHLD_W / 2.0` on `x`, so `shoulder_joint(side)` multiplies by the sign and the two sides come out at `±0.1806`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/figure/test_anatomy.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/figure/anatomy.py tests/figure/test_anatomy.py
git commit -m "feat: add figure anatomy constants and joint targets"
```

---

### Task 3: Bone hierarchy in the posed position

**Files:**
- Create: `scripts/figure/rig.py`
- Test: `tests/figure/test_rig.py`

**Interfaces:**
- Consumes: `figure.anatomy`, `figure.vector`.
- Produces: `BoneSpec` as a `NamedTuple` with fields `(name: str, head: tuple, tail: tuple, parent: str | None)`, and `bones() -> list[BoneSpec]` returning all 21 bones in parent-before-child order. Also `CHAINS: dict[str, list[str]]` mapping a chain name to its ordered bone names.

**Design note — why there is no forward-kinematics solve.** The spec described solving bone rotations from a rest pose. That turns out to be unnecessary and is the wrong shape for this build. The mesh is authored directly in the final pose, so the bones only need to be *in* that pose to act as a deformation basis; any consistent roll gives the same result. Placing bones at their target coordinates in edit mode removes a whole class of quaternion-arithmetic bugs and the need for `mathutils` in the package. Rest-pose FK would only pay for itself if the figure were going to be re-posed later, which this build is not.

- [ ] **Step 1: Write the failing tests**

```python
def test_bone_count_is_twenty_one():
    assert len(rig.bones()) == 21

def test_every_parent_appears_before_its_children():
    names = [b.name for b in rig.bones()]
    for bone in rig.bones():
        if bone.parent is not None:
            assert names.index(bone.parent) < names.index(bone.name)

def test_no_bone_is_connected_to_a_parent_it_does_not_touch():
    for bone in rig.bones():
        if bone.parent is None:
            continue
        parent = next(b for b in rig.bones() if b.name == bone.parent)
        assert dist(parent.tail, bone.head) == pytest.approx(0.0, abs=1e-9)

def test_bone_tail_is_not_equal_to_its_head():
    for bone in rig.bones():
        assert dist(bone.head, bone.tail) > 1e-6

def test_mirroring_negates_x_only():
    left = rig.thigh_bone("L")
    right = rig.thigh_bone("R")
    assert right.head[0] == pytest.approx(-left.head[0])
    assert right.head[1] == pytest.approx(left.head[1])
    assert right.head[2] == pytest.approx(left.head[2])

def test_head_bone_is_not_mirrored():
    assert rig.head_bone().head == rig.head_bone().head
    assert rig.head_bill().head == anatomy.HEAD
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/figure/test_rig.py -q`
Expected: `ModuleNotFoundError: No module named 'figure.rig'`.

- [ ] **Step 3: Implement `scripts/figure/rig.py`**

Build each bone as head→tail between consecutive joint targets:

| Bone | head | tail |
|---|---|---|
| `root` | `(0, 0, 0)` | `(0, 0, HIP_H)` |
| `hips` | `hip_joint(side)` averaged over both sides | `spine` base, `(0, 0.018, 0.155)` |
| `spine` | hips tail | `(0, 0.006, 0.335)` |
| `chest` | spine tail | `neck` base, `(0, -0.016, SHOULDER_Z + 0.004)` |
| `neck` | chest tail | `(0, -0.022, NECK_TOP_Z)` |
| `head` | neck tail | `HEAD` |

Then per side: `clavicle.X` from chest tail to `shoulder_joint(side)`; `upperarm.X` shoulder→elbow; `forearm.X` elbow→wrist; `hand.X` wrist to the existing build's hand centre `wrist + (0.030*sx, -0.020, -0.018)`; `thigh.X` from `hip_joint(side)` to `knee_joint(side)`; `shin.X` knee→ankle; `foot.X` ankle to the existing foot centre `(0.164*sx, -0.372, 0.034)`.

`hips` is the one bone that spans both sides: its head is the midpoint of the two hip joints and its tail sits on the spine axis. A single per-side hip bone would need a duplicate spine on both sides and would put a seam down the middle of the pelvis.

`CHAINS` maps: `"arm.L"` → `[clavicle.L, upperarm.L, forearm.L, hand.L]`, `"arm.R"` likewise, `"leg.L"` → `[thigh.L, shin.L, foot.L]`, `"leg.R"` likewise, `"spine"` → `[hips, spine, chest, neck, head]`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/figure/test_rig.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/figure/rig.py tests/figure/test_rig.py
git commit -m "feat: add posed figure bone hierarchy"
```

---

### Task 4: Loft construction

**Files:**
- Create: `scripts/figure/loft.py`
- Test: `tests/figure/test_loft.py`

**Interfaces:**
- Consumes: `figure.vector`.
- Produces: `ring(center, half_x, half_y, half_z, segments) -> list[tuple]` returning one CCW ring in the plane normal to `+z`; `loft_rings(rings, cap_start=True, cap_end=True) -> dict` returning `{"verts": list[tuple], "faces": list[tuple[int, int, int, int]]}` with consistent winding and optional n-gon caps.

- [ ] **Step 1: Write the failing tests**

```python
def test_ring_returns_requested_segment_count_and_is_planar():
    pts = loft.ring((0.0, 0.0, 1.0), 0.5, 0.25, 0.1, 12)
    assert len(pts) == 12
    assert all(abs(p[2] - 1.0) < 1e-9 for p in pts)

def test_loft_quad_faces_have_positive_area():
    mesh = loft.loft_rings([loft.ring((0, 0, z), 0.5, 0.5, 0.5, 16) for z in (0.0, 0.2, 0.4)])
    for face in mesh["faces"]:
        assert abs(polygon_area_3d(face, mesh["verts"])) > 1e-9

def test_loft_with_single_ring_and_no_caps_produces_no_faces():
    mesh = loft.loft_rings([loft.ring((0, 0, 0), 1, 1, 1, 8)], cap_start=False, cap_end=False)
    assert mesh["faces"] == []

def test_cap_is_an_ngon_of_the_ring_size():
    mesh = loft.loft_rings([loft.ring((0, 0, z), 1, 1, 1, 8) for z in (0.0, 1.0)])
    start, end = mesh["faces"][0], mesh["faces"][-1]
    assert len(start) == 8 and len(end) == 8

def test_ring_degenerate_axis_does_not_produce_zero_area_faces():
    flat = loft.ring((0, 0, 0), 0.5, 0.5, 0.0, 16)
    mesh = loft.loft_rings([flat, flat], cap_start=False, cap_end=False)
    for face in mesh["faces"]:
        assert abs(polygon_area_3d(face, mesh["verts"])) > 1e-9
```

The last test pins Review Focus item 4. A zero `half_z` makes the ring collapse to a line segment; the faces become degenerate and shade as black spikes under SSS. `ring` must expand a zero-axis half-extent to a small positive epsilon rather than emitting coincident verts.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/figure/test_loft.py -q`
Expected: `ModuleNotFoundError: No module named 'figure.loft'`.

- [ ] **Step 3: Implement `scripts/figure/loft.py`**

Wind side faces so the outward normal points away from the ring axis: for rings `a` (lower) and `b` (upper), emit `(a[j], a[k], b[k], b[j])` with `k = (j + 1) % segments`. Wind the start cap in reverse and the end cap forward. Do not add a centre vertex to caps — the n-gon subsurfs cleanly and a triangle fan pinches visibly at the pole.

`ring` clamps each half-extent to a floor of `1e-4` before generating, which is what makes `test_ring_degenerate_axis_does_not_produce_zero_area_faces` pass for free.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/figure/test_loft.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/figure/loft.py tests/figure/test_loft.py
git commit -m "feat: add ring and loft construction with winding guarantees"
```

---

### Task 5: Analytic skin weights

**Files:**
- Create: `scripts/figure/weights.py`
- Test: `tests/figure/test_weights.py`

**Interfaces:**
- Consumes: `figure.vector`, `figure.rig`.
- Produces: `chain_weights(points, t) -> dict[str, float]` mapping bone name to weight for a vertex at normalized arc-length position `t` along a chain's joint polyline, where `points` is the polyline of joint positions in chain order and the number of bones is `len(points) - 1`. Also `blend_zone_weights(t, root_bone, chain_bones, blend) -> dict[str, float]`, where the first `blend` fraction of the chain is owned by `root_bone` and cross-fades into `chain_bones[0]`.

**Design note — why arc length, not 3D distance.** Weighting each vertex to its two nearest bones by 3D distance looks reasonable on a straight limb and fails at the shoulder: torso vertices are geometrically closer to the clavicle than to `chest`, so they get sucked onto the arm and the shoulder caves in. Parameterizing each chain by arc length along its own joints makes the blend position a property of the pose rather than of the surrounding geometry, so it is predictable and directly testable.

- [ ] **Step 1: Write the failing tests**

```python
def test_vertex_at_chain_start_belongs_entirely_to_the_first_bone():
    w = weights.chain_weights([(0, 0, 0), (1, 0, 0), (2, 0, 0)], 0.0)
    assert w == {"bone0": pytest.approx(1.0)}

def test_vertex_at_the_joint_splits_evenly_between_neighbours():
    w = weights.chain_weights([(0, 0, 0), (1, 0, 0), (2, 0, 0)], 0.5)
    assert w["bone0"] == pytest.approx(0.5)
    assert w["bone1"] == pytest.approx(0.5)

def test_vertex_past_the_end_clamps_to_the_terminal_bone():
    w = weights.chain_weights([(0, 0, 0), (1, 0, 0)], 5.0)
    assert w == {"bone0": pytest.approx(1.0)}

def test_weights_always_sum_to_one():
    for i in range(0, 101):
        t = i / 100.0
        w = weights.chain_weights([(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)], t)
        assert sum(w.values()) == pytest.approx(1.0)
        assert all(v >= 0.0 for v in w.values())

def test_degenerate_chain_raises_rather_than_producing_nan():
    with pytest.raises(weights.ChainError, match="zero length"):
        weights.chain_weights([(1, 1, 1), (1, 1, 1)], 0.5)

def test_blend_zone_transfers_ownership_to_the_root_bone():
    w = weights.blend_zone_weights(0.0, "chest", ["clavicle.L", "upperarm.L"], 0.25)
    assert w["chest"] == pytest.approx(1.0)
    w = weights.blend_zone_weights(0.25, "chest", ["clavicle.L", "upperarm.L"], 0.25)
    assert w["chest"] == pytest.approx(0.5)
    assert w["clavicle.L"] == pytest.approx(0.5)

def test_blend_zone_past_its_end_does_not_mention_the_root_bone():
    w = weights.blend_zone_weights(0.5, "chest", ["clavicle.L", "upperarm.L"], 0.25)
    assert "chest" not in w
```

`test_degenerate_chain_raises_rather_than_producing_nan` pins Review Focus item 2. NaN weights do not raise in Blender; they propagate into the Skin modifier and surface as an invisible or exploded body, hours later, in a render.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/figure/test_weights.py -q`
Expected: `ModuleNotFoundError: No module named 'figure.weights'`.

- [ ] **Step 3: Implement `scripts/figure/weights.py`**

Define `ChainError(ValueError)`.

`chain_weights` walks the polyline accumulating segment lengths; if the total is zero, raise `ChainError` naming the zero-length chain. Clamp `t` to `[0, 1]`. With `n = len(points) - 1` bones, the normalized parameter spans `n` segments, so bone `i` owns `t` in `[i/n, (i+1)/n]` and cross-fades linearly to bone `i+1` over the last half of its span — that keeps the widest influence centred on the joint rather than at the segment boundary. Omit zero-weight bones from the returned dict.

`blend_zone_weights` is the shoulder fix: for `t < blend`, `w[root_bone] = 1 - t/blend` and `w[chain_bones[0]] = t/blend`; for `t >= blend`, delegate to `chain_weights` with `t` rescaled to the remainder of the chain.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/figure/test_weights.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/figure/weights.py tests/figure/test_weights.py
git commit -m "feat: add arc-length skin weights with explicit joint blend zones"
```

---

### Task 6: Body mesh assembly

**Files:**
- Create: `scripts/figure/body.py`
- Test: `tests/figure/test_body.py`

**Interfaces:**
- Consumes: `figure.anatomy`, `figure.vector`, `figure.rig`, `figure.loft`, `figure.weights`.
- Produces: `BodyPart` as a `NamedTuple` `(name: str, verts: list[tuple], faces: list[tuple], chain: str, ts: list[float])`, and `parts() -> list[BodyPart]` for the torso, neck, both arms, both legs and both feet. `ts` holds one normalized arc-length position per vertex, parallel to `verts`, so a part's weights are derivable without re-deriving geometry.

- [ ] **Step 1: Write the failing tests**

```python
def test_body_has_one_part_per_chain():
    assert sorted(p.name for p in body.parts()) == [
        "Arm.L", "Arm.R", "Foot.L", "Foot.R", "Leg.L", "Leg.R", "Neck", "Torso",
    ]

def test_every_vertex_has_a_t_value():
    for part in body.parts():
        assert len(part.ts) == len(part.verts)

def test_t_values_are_within_the_unit_interval():
    for part in body.parts():
        assert all(0.0 <= t <= 1.0 for t in part.ts)

def test_torso_tapers_from_shoulder_to_waist():
    torso = next(p for p in body.parts() if p.name == "Torso")
    widths = [max(v[0] for v in row) for row in ring_rows(torso)]
    assert widths[0] > widths[len(widths) // 2]
    assert widths[-1] > widths[len(widths) // 2]

def test_every_part_face_index_is_in_range():
    for part in body.parts():
        assert all(0 <= i < len(part.verts) for f in part.faces for i in f)

def test_left_and_right_limbs_are_mirror_images_in_x_only():
    left = next(p for p in body.parts() if p.name == "Leg.L")
    right = next(p for p in body.parts() if p.name == "Leg.R")
    assert len(left.verts) == len(right.verts)
    for a, b in zip(left.verts, right.verts):
        assert b[0] == pytest.approx(-a[0], abs=1e-9)
        assert b[1] == pytest.approx(a[1], abs=1e-9)
        assert b[2] == pytest.approx(a[2], abs=1e-9)

def test_limb_radii_taper_from_proximal_to_distal():
    thigh = next(p for p in body.parts() if p.name == "Leg.L")
    radii = [mean_ring_radius(row) for row in ring_rows(thigh)]
    assert radii[0] > radii[-1]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/figure/test_body.py -q`
Expected: `ModuleNotFoundError: No module named 'figure.body'`.

- [ ] **Step 3: Implement `scripts/figure/body.py`**

**Torso** — loft cross-sections at hip, waist, ribcage, armpit and shoulder, using the existing build's radii so proportions do not shift: hip `±HIP_W/2` by `HIP_D/2`, waist tapering to `±0.108` by `±0.058`, ribcage `±0.148` by `±0.066`, armpit `±0.163` by `±0.070`, shoulder `±SHLD_W/2` by `±0.072`. Chain `spine`, `t_range` `(0.0, 1.0)` of the chain's bone span.

**Limbs** — ring chains along each bone pair. Radii from the existing build: thigh `0.116 → 0.088`, calf `0.088 → 0.052`, upper arm `0.068 → 0.052`, forearm `0.052 → 0.043`. The knee sphere and elbow sphere from the old build are *not* reproduced — a continuous loft through the joint is what removes the bead.

**Feet** — chain `foot`, a rounded wedge from the ankle to the existing foot centre.

**Neck** — chain `spine`, occupying only the `neck` and `head` bone span, radii `0.058 → 0.050`.

Each part's vertices record the `t` they sit at along their chain, so Task 7 can hand them straight to `weights.chain_weights` without re-deriving anything.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/figure/test_body.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/figure/body.py tests/figure/test_body.py
git commit -m "feat: add continuous lofted body parts"
```

---

### Task 7: Blender assembly, verification and first render

**Files:**
- Create: `scripts/figure/verify.py`
- Create: `scripts/build_figure.py`
- Test: `tests/figure/test_verify.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6, plus `figure.materials` (Task 12) — but for *this* task, `build_figure.py` renders with the plain Principled skin from `model_photoreal_figure.py` so the geometry can be judged before shading is a variable.
- Produces: `verify.check_limb_lengths() -> list[tuple[str, float, float, float]]` and `verify.check_silhouette(widths_by_height) -> list[tuple[str, float, float, float]]`, each returning `(label, actual, target, percent_error)`. `verify.check_weights(parts) -> list[str]` returns the names of parts containing an unbound vertex, empty when there are none. `build_figure.py` raises `SystemExit(1)` if any check exceeds 1% or `check_weights` returns anything.

- [ ] **Step 1: Write the failing tests**

```python
def test_limb_length_check_passes_for_the_shipped_pose():
    for label, actual, target, err in verify.check_limb_lengths():
        assert abs(err) <= 1.0, f"{label} off by {err}%"

def test_silhouette_check_flags_a_too_narrow_torso():
    rows = verify.check_silhouette({0.30: 0.20})
    assert any(abs(err) > 1.0 for _, _, _, err in rows)

def test_check_weights_finds_no_unbound_vertex_in_the_real_body():
    assert verify.check_weights(body.parts()) == []

def test_check_weights_names_a_part_with_an_unbound_vertex():
    broken = body.parts()[0]._replace(ts=[0.0] * len(body.parts()[0].verts))
    assert verify.check_weights([broken]) == [broken.name]

def test_checks_report_the_worst_error_first():
    rows = verify.check_limb_lengths()
    errors = [abs(r[3]) for r in rows]
    assert errors == sorted(errors, reverse=True)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/figure/test_verify.py -q`
Expected: `ModuleNotFoundError: No module named 'figure.verify'`.

- [ ] **Step 3: Implement `scripts/figure/verify.py`**

Port the seven checks from `model_photoreal_figure.py` lines 561-569 unchanged, computing them from `figure.rig` and `figure.anatomy` rather than from Blender object bounding boxes — the joints are already known exactly, so measuring them in the viewport would only add rounding noise.

`check_weights` walks each part's `ts` through `weights.chain_weights` and flags any vertex whose weights sum to zero. This is the check that catches a vertex the Skin modifier would silently leave unbound: Blender does not complain, and the failure surfaces as a shell that detaches at render time, which is a long way from the cause.

`check_silhouette` takes a mapping of height to width and compares against the anthropometric table. Sort all check output by absolute error descending, worst first, so a failing build shows its worst problem on the first line.

- [ ] **Step 4: Implement `scripts/build_figure.py`**

The entry point. It must, in order: prepend its own directory to `sys.path`; import the `figure` package; build the armature in edit mode from `rig.bones()`, setting each bone's head and tail and leaving roll at its default; build `Body` by joining the parts from `body.parts()`, welding with a small merge threshold so the loft seams close; add a `Subdivision` modifier at level 2; create vertex groups from each part's `ts`; add a `Skin` modifier with `use_deform_preserve_volume = True`; run `verify` and `SystemExit(1)` on failure; then render.

Arms and legs must go through `weights.blend_zone_weights`, not `chain_weights` directly: `blend_zone_weights(t, "chest", ["clavicle.L", "upperarm.L", "forearm.L", "hand.L"], 0.25)` for each arm, and the equivalent with `"hips"` for each leg. Without the blend zone the shoulder and hip collapse — torso vertices sit geometrically closer to the clavicle than to `chest`, so pure chain weighting pulls them onto the arm. `0.25` is the fraction of the arm chain owned by the root bone before the cross-fade completes.

`use_deform_preserve_volume = True` is the single most important line in the file. Without dual-quaternion skinning the shoulder and elbow collapse visibly at this pose, and the figure looks worse than the primitives did.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/figure/test_verify.py -q`
Expected: PASS.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all tests pass, including the original 45.

- [ ] **Step 7: Build and render in Blender**

```bash
"/mnt/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b -P scripts/build_figure.py
```

Expected: a `VERIFY` block with every line within ±1.00%, then `RESULT` with two PNG paths. `OUT_DIR` keeps the existing `%TEMP%/blender-mcp-out` default — a Windows `blender.exe` cannot resolve a WSL path, which is why the earlier build wrote to a garbage location.

- [ ] **Step 8: Look at both renders and report honestly**

This is the first visual gate. Read both PNGs and state plainly whether the body reads continuous under raking light. If a joint line is visible, the blend zones in Task 5 are wrong — do not proceed to the head until the body is right, because the head is skinned to the same rig and will inherit the same error.

- [ ] **Step 9: Commit**

```bash
git add scripts/figure/verify.py scripts/build_figure.py tests/figure/test_verify.py
git commit -m "feat: assemble skinned body in Blender with pre-render verification"
```

---

### Task 8: Cloth shells

**Files:**
- Create: `scripts/figure/cloth.py`
- Test: `tests/figure/test_cloth.py`

**Interfaces:**
- Consumes: `figure.body`, `figure.loft`, `figure.anatomy`.
- Produces: `garments() -> list[BodyPart]` returning the `Top.L`, `Top.R` and `Sock.L`, `Sock.R` parts, each carrying `chain` and `ts` exactly like any body part so it weights identically.

- [ ] **Step 1: Write the failing tests**

```python
def test_garments_are_the_four_expected_pieces():
    assert sorted(g.name for g in cloth.garments()) == ["Sock.L", "Sock.R", "Top.L", "Top.R"]

def test_top_sits_outside_the_body_by_a_positive_offset():
    body_arm = next(p for p in body.parts() if p.name == "Arm.L")
    top_arm = next(g for g in cloth.garments() if g.name == "Top.L")
    assert mean_ring_radius(ring_rows(top_arm)[0]) > mean_ring_radius(ring_rows(body_arm)[-1])

def test_garment_t_values_stay_inside_the_unit_interval():
    for g in cloth.garments():
        assert all(0.0 <= t <= 1.0 for t in g.ts)

def test_garment_faces_are_in_range():
    for g in cloth.garments():
        assert all(0 <= i < len(g.verts) for f in g.faces for i in f)

def test_left_and_right_sleeves_mirror_in_x_only():
    left = next(g for g in cloth.garments() if g.name == "Top.L")
    right = next(g for g in cloth.garments() if g.name == "Top.R")
    for a, b in zip(left.verts, right.verts):
        assert b[0] == pytest.approx(-a[0], abs=1e-9)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/figure/test_cloth.py -q`
Expected: `ModuleNotFoundError: No module named 'figure.cloth'`.

- [ ] **Step 3: Implement `scripts/figure/cloth.py`**

Reuse the arm and leg lofts from `body.parts()` and scale each ring outward by a named offset — `TOP_OFFSET = 0.006`, `SOCK_OFFSET = 0.005`. Reusing the profiles rather than fitting new ones is what keeps the cloth on the body when the pose changes; a separately authored sleeve drifts the moment a bone moves.

Cover the same ranges the existing build does: the top spans the upper arm from the shoulder to mid-bicep and bunches at `z ≈ 0.47`, and the socks run from just above the ankle down over the foot. Give each garment part a `Solidify` modifier thickness of `0.004` so it has a visible edge rather than reading as a decal.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/figure/test_cloth.py -q`
Expected: PASS.

- [ ] **Step 5: Render and confirm the garment tracks the arm**

Run the Blender command from Task 7 step 7. Inspect the three-quarter render: the sleeve must sit on the upper arm with no gap at the shoulder and no intersection at the bicep.

- [ ] **Step 6: Commit**

```bash
git add scripts/figure/cloth.py tests/figure/test_cloth.py
git commit -m "feat: add top and sock shells bound to the body profiles"
```

---

### Task 9: Cranial loft

**Files:**
- Create: `scripts/figure/head.py`
- Test: `tests/figure/test_head.py`

**Interfaces:**
- Consumes: `figure.anatomy`, `figure.vector`, `figure.loft`, `figure.weights`.
- Produces: `STATIONS` — the ordered head cross-section table — and `cranium() -> dict` in the `{"verts", "faces"}` shape `loft.loft_rings` returns.

- [ ] **Step 1: Write the failing tests**

```python
def test_cranium_spans_chin_to_vertex():
    mesh = head.cranium()
    zs = [v[2] for v in mesh["verts"]]
    assert min(zs) == pytest.approx(anatomy.CHIN_Z, abs=1e-6)
    assert max(zs) == pytest.approx(anatomy.VERTEX_Z, abs=1e-6)

def test_head_is_wider_at_the_parietal_than_at_the_chin():
    widths = head.width_profile(head.cranium())
    assert max(widths) > widths[0]

def test_head_depth_exceeds_width_as_in_a_real_skull():
    assert anatomy.HEAD_D > anatomy.HEAD_W

def test_head_is_asymmetric_front_to_back():
    mesh = head.cranium()
    face_y = [v[1] for v in mesh["verts"] if v[2] > anatomy.CHIN_Z + 0.4 * anatomy.HEAD_H]
    back_y = [v[1] for v in mesh["verts"] if v[2] < anatomy.CHIN_Z + 0.4 * anatomy.HEAD_H]
    assert min(face_y) < max(back_y)

def test_cranium_faces_all_have_positive_area():
    mesh = head.cranium()
    for face in mesh["faces"]:
        assert abs(polygon_area_3d(face, mesh["verts"])) > 1e-9
```

`test_head_is_asymmetric_front_to_back` is the direct test of the defect in the old build: a single ellipsoid is symmetric about its own centre in `y`, which is why the old head had no forehead.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/figure/test_head.py -q`
Expected: `ModuleNotFoundError: No module named 'figure.head'`.

- [ ] **Step 3: Implement the station table in `scripts/figure/head.py`**

`t` runs 0 at the chin to 1 at the vertex. `hw` and `hd` are half-width and half-depth; `y0` shifts the section forward or back along `y`.

| t | hw | hd | y0 |
|---|---|---|---|
| 0.00 | 0.016 | 0.024 | 0.004 |
| 0.10 | 0.038 | 0.052 | 0.002 |
| 0.22 | 0.062 | 0.078 | -0.002 |
| 0.38 | 0.072 | 0.094 | -0.004 |
| 0.55 | 0.0756 | 0.0966 | -0.002 |
| 0.75 | 0.070 | 0.090 | 0.000 |
| 0.90 | 0.050 | 0.062 | 0.000 |
| 1.00 | 0.006 | 0.008 | 0.000 |

Interpolate with `vector.lerp_chain` over the table so intermediate cross-sections are smooth, and emit one ring per table entry at `segments = 32`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/figure/test_head.py -q`
Expected: PASS.

- [ ] **Step 5: Render and look at the bare cranium**

Run the Blender command from Task 7 step 7. Before adding any features, confirm the head reads as a skull from the side: there must be a forehead, a brow shelf and a jaw, not an egg. If it does not, fix the station table before continuing — every feature in Task 10 is positioned relative to it.

- [ ] **Step 6: Commit**

```bash
git add scripts/figure/head.py tests/figure/test_head.py
git commit -m "feat: add lofted cranial mass with front-to-back asymmetry"
```

---

### Task 10: Sockets, brow ridge and nose

**Files:**
- Modify: `scripts/figure/head.py`
- Test: `tests/figure/test_head_features.py`

**Interfaces:**
- Consumes: `figure.head.cranium`, `figure.loft`, `figure.anatomy`.
- Produces: `sockets() -> dict` (cranium with the two eye sockets cut), `brow_ridge(sockets) -> dict`, `nose(sockets) -> dict`, each in the `{"verts", "faces"}` shape. Also `EYE_CENTRES` as a pair of 3-tuples and `SOCKET_RADIUS`.

- [ ] **Step 1: Write the failing tests**

```python
def test_socket_centres_are_symmetric_about_the_head_axis():
    assert head.EYE_CENTRES[0][0] == pytest.approx(-head.EYE_CENTRES[1][0])

def test_sockets_remove_vertices_inside_the_socket_radius():
    mesh = head.sockets()
    solid = head.cranium()
    assert len(mesh["verts"]) > len(solid["verts"])

def test_socket_boolean_failure_raises():
    with pytest.raises(head.SocketError):
        head._boolean_difference(head.cranium(), head.cranium())

def test_nose_extends_further_forward_than_the_brow():
    brow = min(v[1] for v in head.brow_ridge(head.sockets())["verts"])
    tip = min(v[1] for v in head.nose(head.sockets())["verts"])
    assert tip < brow

def test_nose_bridge_to_tip_is_a_single_continuous_surface():
    mesh = head.nose(head.sockets())
    assert len(mesh["faces"]) > 0
    assert len({len(f) for f in mesh["faces"]}) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/figure/test_head_features.py -q`
Expected: FAIL — `figure.head` has no attribute `sockets`.

- [ ] **Step 3: Define `SocketError` and the socket cut**

`class SocketError(RuntimeError)`. `_boolean_difference(base, cutter)` must raise `SocketError` when the result has no faces or when its signed volume is negative — the empty-mesh case is Review Focus item 5. Log the failure with the cutter's position so a bad edit is traceable.

Eye centres at `(±0.033, face_y + 0.006, CHIN_Z + 0.46 * HEAD_H)`; `SOCKET_RADIUS = 0.0195`.

- [ ] **Step 4: Implement the brow ridge and nose**

Brow ridge: a lofted band above the sockets, from `x = -0.052` to `x = +0.052`, peaking at `CHIN_Z + 0.55 * HEAD_H`, offset forward `0.006` from the cranial surface.

Nose: loft bridge→tip→nostril wings as one continuous ring chain down the profile. Bridge from `CHIN_Z + 0.55 * HEAD_H`, tip at `CHIN_Z + 0.36 * HEAD_H` projecting forward of the brow, wings at `±0.016`. Do **not** build the nose from three ellipsoids — that is exactly what the old build did and it is why the nose read as a lump. One lofted surface is what gives it a profile silhouette.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/figure/test_head_features.py -q`
Expected: PASS.

- [ ] **Step 6: Render from both cameras and check for socket shading seams**

Run the Blender command from Task 7 step 7. The known risk here is a shading seam where the boolean cut meets the smooth-shaded cranium. If one appears, add a tight edge loop ring around each socket boundary rather than reaching for auto-smooth.

- [ ] **Step 7: Commit**

```bash
git add scripts/figure/head.py tests/figure/test_head_features.py
git commit -m "feat: add eye sockets, brow ridge and lofted nose"
```

---

### Task 11: Jaw, mouth, ears and eyes

**Files:**
- Modify: `scripts/figure/head.py`
- Test: `tests/figure/test_head_features.py` (extend)

**Interfaces:**
- Consumes: `figure.head` from Task 10.
- Produces: `assemble_head() -> dict` returning the single complete head mesh — cranium with sockets, plus ridge, nose, cheekbones, jaw, lips, mouth interior, tongue and ears — in the `{"verts", "faces"}` shape. Also `EYE_PARTS` describing the sclera/iris/pupil/cornea stack.

- [ ] **Step 1: Write the failing tests**

```python
def test_assembled_head_is_one_continuous_surface():
    mesh = head.assemble_head()
    assert mesh_manifold_edge_count(mesh) == 0

def test_jaw_tapers_to_the_chin():
    widths = head.width_profile(head.assemble_head())
    assert widths[0] < widths[len(widths) // 4]

def test_ear_is_attached_not_floating():
    mesh = head.assemble_head()
    assert any(f in mesh["faces"] for f in head.ear_faces(mesh))

def test_eye_stack_has_four_surfaces():
    assert sorted(head.EYE_PARTS) == ["Cornea", "Iris", "Pupil", "Sclera"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/figure/test_head_features.py -q`
Expected: FAIL — `figure.head` has no attribute `assemble_head`.

- [ ] **Step 3: Implement cheekbones, jaw, lips, mouth, ears**

Cheekbones and jaw are lofted bands joined into the cranium surface rather than placed as separate blobs — this is the seam the old build had where a cheek sphere met the head.

Mouth: a shallow depression with a raised lip rim, following the existing build's geometry (upper torus `major 0.017`, `minor 0.0055` at `CHIN_Z + 0.24 * HEAD_H`; lower torus `major 0.016`, `minor 0.0060` at `CHIN_Z + 0.18 * HEAD_H`), plus the mouth interior and the forward tongue, because the reference has the mouth open.

Ears: attached to the cranial surface at the ear-canal station (`t = 0.38`), protruding `0.021` in `y`.

Eyes: the existing sclera/iris/pupil/cornea stack, unchanged — the cornea's low roughness is what produces the catchlight. It only moves into the sockets.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/figure/test_head_features.py -q`
Expected: PASS.

- [ ] **Step 5: Render and judge the face from both cameras**

Run the Blender command from Task 7 step 7. The acceptance bar: the head reads as a face from the three-quarter camera. If it does not, the station table from Task 9 is the first thing to revisit — features positioned on the wrong skull will never resolve.

- [ ] **Step 6: Commit**

```bash
git add scripts/figure/head.py tests/figure/test_head_features.py
git commit -m "feat: assemble continuous head with jaw, mouth, ears and eyes"
```

---

### Task 12: Materials, hair and final render

**Files:**
- Create: `scripts/figure/materials.py`
- Test: `tests/figure/test_materials.py`
- Modify: `scripts/build_figure.py`

**Interfaces:**
- Consumes: `figure.anatomy`, all prior tasks.
- Produces: `skin_values() -> dict` holding the SSS skin parameters as plain data; `materials() -> dict[str, dict]` holding every material's parameters; `build_hair(count=220) -> dict` and `ponytail() -> dict`, both in the `{"verts", "faces"}` shape. No function here touches `bpy`.

- [ ] **Step 1: Write the failing tests**

```python
def test_every_material_in_the_existing_build_is_reproduced():
    assert sorted(materials.materials()) == sorted([
        "Chain_Metal", "Eye_Cornea", "Eye_Iris", "Eye_Pupil", "Eye_Sclera",
        "Hair_Blonde", "Nostril", "Skin", "Skin_Brow", "Skin_Lip",
        "Socks_White", "Top_White",
    ])

def test_skin_enables_subsurface():
    assert materials.skin_values()["subsurface_weight"] == 0.28

def test_hair_is_deterministic():
    assert materials.build_hair() == materials.build_hair()

def test_ponytail_is_present():
    assert len(materials.ponytail()["verts"]) > 0
```

`test_hair_is_deterministic` matters more than it looks: the old build's hair used a golden-angle distribution with no random seed, and any change to iteration order silently changes every render, making regressions impossible to spot.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/figure/test_materials.py -q`
Expected: `ModuleNotFoundError: No module named 'figure.materials'`.

- [ ] **Step 3: Implement `scripts/figure/materials.py`**

Port the material definitions from `model_photoreal_figure.py` lines 94-127 and 233-247 unchanged, including `set_input`'s version-tolerant socket lookup — Principled BSDF renamed most sockets in Blender 4.0, and the script must not be pinned to one version. Return values as plain dicts so the material layer stays testable without `bpy`; `build_figure.py` is what turns a dict into a node tree.

Port `build_hair` from lines 340-404, including the face-exclusion test `if sy < -0.30 * sin(phi) and sz < 0.55: continue` — without it strands grow across the eyes and mouth. Port the ponytail from lines 409-411.

- [ ] **Step 4: Update `scripts/build_figure.py` to finish the render**

Add, carrying every value over unchanged from `model_photoreal_figure.py` lines 511-618: the three area lights (`Key` `(1.15, -1.15, 1.18)` 90.0 W size 1.05; `Fill` `(-1.40, -0.85, 0.66)` 18.0 W size 1.60; `Rim` `(-0.40, 1.40, 1.10)` 130.0 W size 0.95; all aimed at `(0.0, -0.10, 0.46)`), both cameras at 85 mm (`Camera` `(1.95, -1.95, 0.82)`, `Camera_Side` `(2.60, -0.10, 0.72)`, both aimed at `(0.0, -0.10, 0.50)`), Cycles CPU at 192 samples with denoising, `max_bounces = 12`, `transmission_bounces = 8`, 900x1150 RGBA PNG, `exposure = -1.6`, `film_transparent = True`, and a zero-strength world.

Write to `continuous_three_quarter.png` and `continuous_side.png` under `OUT_DIR`, so they do not overwrite the existing photoreal renders.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/figure/test_materials.py -q`
Expected: PASS.

- [ ] **Step 6: Render and compare against the reference**

Run the Blender command from Task 7 step 7. Read both PNGs and compare against `girl.jpg` on pose and outfit. Report honestly: the goal was a good stylized figure, not a likeness match, and the result should be judged against that.

- [ ] **Step 7: Run the full suite and commit**

```bash
.venv/bin/python -m pytest tests/ -q
git add scripts/figure/materials.py tests/figure/test_materials.py scripts/build_figure.py
git commit -m "feat: add SSS materials, hair and final render pass"
```

## Handoff and Definition of Done

The work is done when the full suite passes, `verify` reports every check within ±1.00%, and the user judges both renders to show a figure that reads as human — continuous body under raking light, a face that reads from the three-quarter camera, and the reference pose and outfit intact.

Two gates are deliberately hard. Task 7 is the first: if the body does not read continuous there, Tasks 8-12 are building on a broken rig and will inherit the same fault. Task 9 is the second: every head feature in Tasks 10 and 11 is positioned relative to the station table, so a wrong skull cannot be rescued downstream.

If Blender cannot be reached, record exactly which gate is blocked. Do not report a live render that did not happen.
