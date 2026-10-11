# Continuous Figure Design

**Date:** 2026-10-11
**Status:** Approved for planning
**Supersedes:** nothing. `scripts/model_photoreal_figure.py` and
`scripts/model_seated_figure.py` stay in the tree unchanged as the historical
procedural builds this work was measured against.

## Problem

`scripts/model_photoreal_figure.py` renders a seated female figure matching
`girl.jpg`. The pose, anthropometric scale and skin shading are sound. The body
does not read as a human.

The cause is structural, not shading. The body is roughly ten separate
intersecting surfaces — `Pelvis`, `Chest`, a `Torso` capsule, `Shoulders`, and one
capsule per limb segment. Each carries its own subdivision modifier. Subsurf
never evaluates across an intersection, so every joint survives as a hard seam,
and the limbs read as beads on a string. No shader change fixes geometry.

The head fails for the same reason at a smaller scale: one ellipsoid plus about
fifteen feature ellipsoids stuck to its surface. The cranial mass is a single
ellipsoid and therefore symmetric front-to-back, which a real skull is not, and
the features sit *on* the surface rather than being part of it.

## Goal

A recognizable human figure in the reference pose and outfit, at still-image
quality, built as one continuous skinned body surface and one continuous head
with real facial structure.

Not photoreal. Not animation-ready. A good stylized figure.

## Non-goals

- Matching the reference photograph's likeness. The photo supplies body shape,
  pose, outfit and hair, nothing more.
- A mesh that is pleasant to sculpt by hand. The topology will be skinned and
  subdivided, which is good enough to look at and not good enough to sculpt.
- Any change to the room or chair work.

## Approach

Replace the intersecting-primitive body with an armature-driven skinned surface,
and rebuild the head as a lofted mesh whose features are sculpted into it.

Two constraints follow from the repo's conventions and shape everything else:

1. **All geometry math is plain Python.** No `mathutils.Vector`, no `bmesh`, in
   any module that can be imported outside Blender. Vectors are 3-tuples and the
   vector helpers are module-local functions. This is what lets the loft, weight
   and pose math be unit-tested under `pytest` with no Blender present, matching
   how `tests/` already works.

2. **One source of truth for numbers.** Every anthropometric fraction and every
   joint target lives in one module. The current script hardcodes them at their
   point of use; that is the thing that let hand-tuned limb lengths drift
   -12%/+15% before they were solved.

## Architecture

```
scripts/figure/
  anatomy.py    Scale fractions and joint targets. Pure data and pure math.
  vector.py     Minimal 3-vector helpers. Plain tuples in, plain tuples out.
  rig.py        Bone hierarchy, rest placement, analytic pose solve.
  body.py       Torso and limb lofts, skin weights, Skin modifier.
  head.py       Cranial loft, eye sockets, nose, cheekbones, jaw, lips, ears.
  materials.py  SSS skin, eye stack, hair, cloth.
  verify.py     Silhouette and limb-length assertions.
scripts/build_figure.py   Entry point: assemble, light, camera, render.
```

`scripts/build_figure.py` is run by Blender with `-b -P` and is the only file
that touches `bpy`. It adds its own directory to `sys.path` before importing the
package, since `-P` executes the entry point as `__main__` and siblings are not
otherwise importable.

Modules are split by responsibility because each has a distinct, checkable
contract: `anatomy` holds numbers, `rig` turns numbers into a posed skeleton,
`body` and `head` turn a posed skeleton into geometry, `verify` says whether the
result is right. `body` and `head` are kept apart because they are the two
largest pieces of work and they can be iterated on independently.

### Skeleton

Twenty-one bones, rotation only, never scaled:

```
root → hips → spine → chest → neck → head
chest → clavicle.L/R → upperarm.L/R → forearm.L/R → hand.L/R
hips  → thigh.L/R    → shin.L/R     → foot.L/R
```

Rest positions come from the fractions in `anatomy.py`. The pose is then solved,
not authored: for each chain, compute the bone rotations that place each child
bone's head on its target coordinate. Two-bone chains (thigh→shin,
upperarm→forearm) get the same analytic solve.

**The target coordinates do not change.** `HIP`, `KNEE`, `ANKLE`, `SHOULDER`,
`ELBOW`, `WRIST` and `HEAD` are carried over from `model_photoreal_figure.py`
unchanged. Those values already place the elbow on a sphere of radius `UPARM`
around the shoulder and the wrist at `FOREARM` along the line to the knee, which
is why they verified to +0.07%/+0.04%. The pose conversion changes how those
coordinates are reached, not what they are.

### Body surface

One `Body` object, assembled from lofts and then joined and welded.

- **Torso** — lofted from elliptical cross-sections at hip, waist, ribcage and
  shoulder, so width and depth vary continuously along the trunk. This replaces
  the capsule-plus-chest-sphere pair, which is what produced the bead at the
  waist.
- **Limbs** — tapered chains along each bone pair.
- **Neck** — skinned across `neck` and `head`.

**Weights are computed in-script.** Blender's automatic envelope weights are
unusable on a posed human: they ignore joint bend, so a bent elbow weights the
upper arm almost down to the wrist. Instead each vertex is bound to its two
nearest bones in the chain, weighted by distance, with explicit blend zones at
the shoulder and hip. The Skin modifier runs in dual-quaternion preserve-volume
mode, which is the single largest lever against collapse at a bent joint.

Outfit — white top, socks — becomes a second lofted copy of the same torso and
limb profiles, scaled outward by a named offset per profile (`TOP_OFFSET`,
`sock_offset`), then solidified to a shell. Reusing the profiles rather than
fitting new ones is what keeps the cloth on the body when the pose changes.
Hair stays curves, parented to the head bone.

### Head

One continuous mesh, built in this order. The order is the design; each step
depends on the previous surface existing.

1. **Cranial mass.** Cross-sections down the head axis, each an ellipse whose
   width, depth and offset are driven by named fractions in `anatomy.py` —
   `HEAD_W`, `HEAD_D`, `HEAD_H`, plus a parietal-to-temple taper and a
   jaw-to-chin taper, both explicit ratios rather than eyeballed constants.
   Widest at the parietal, narrowing at the temples, jaw tapering to the chin.
   Lofted, capped, smooth-shaded.
2. **Brow ridge and eye sockets.** Sockets are cut into the front of the cranial
   mass with a boolean; the ridge is added back above them. A face reads from the
   three-quarter camera because of the socket-plus-ridge relationship. An eyeball
   resting on a smooth surface does not read at all.
3. **Nose.** Bridge, tip and nostril wings lofted as one continuous form along
   the profile. The nose profile is the highest-value silhouette in a face and
   the one the three-quarter shot shows best.
4. **Cheekbones and jaw.** The zygomatic arch and mandible are part of the same
   lofted surface, so there is no seam where a cheek sphere used to meet the head.
5. **Mouth.** Lips as a raised rim on a shallow depression, with the cavity
   behind. The reference has the mouth open and the tongue forward, so interior
   and tongue are real geometry.
6. **Ears.** Attached to the cranial surface, not floating beside it.

The existing sclera / iris / pupil / cornea stack is reused unchanged. It was
already correct — the cornea's low roughness is what produces the catchlight —
and it only needs to move into sockets.

### Rendering

Unchanged from `model_photoreal_figure.py`: `film_transparent`, zero-strength
world so the world contributes no bounce, the three-lamp rig, and the same two
cameras (side and three-quarter). Background stays transparent because the figure
is the subject and a room would steal contrast from the skin.

## Data flow

```
anatomy (numbers)
    → rig (posed skeleton, via analytic solve)
        → body (one continuous skinned surface)
        → head (one continuous mesh with sculpted features)
            → materials (SSS skin, eye stack, hair, cloth)
                → verify (silhouette + limb length, before any render)
                    → build_figure (light, camera, render)
```

## Error handling

There is no user input at runtime and nothing to recover from, so this is about
failing loudly rather than gracefully. Three checks, all of which abort the build
before rendering:

- `verify` asserts limb lengths against the anthropometric targets within 1%. A
  failure means the pose solve is wrong, and a render would hide that.
- `verify` measures the body's width profile at fixed heights along the stature
  and compares it against the anthropometric table. This catches proportion
  errors in seconds, before spending a minute on a render, and it is the check
  that catches a torso lofted to the wrong cross-sections.
- `verify` asserts the skin weights are normalized per vertex and that no vertex
  has zero total weight. An unbound vertex shows up as a detached shell in the
  render and is otherwise very hard to trace.
- `verify` asserts every loft has consistent winding and non-degenerate faces. A
  flipped normal in a boolean socket shades black and reads as a modelling bug.

A boolean that produces an empty or inverted result raises rather than returning
a silently wrong mesh, because the socket step is the one place where a partial
failure still yields a renderable object.

## Testing

`pytest`, no Blender required, matching the existing `tests/` convention.

- `test_anatomy.py` — the scale fractions and joint targets are the numbers the
  current script verified; assert the limb lengths they imply.
- `test_rig.py` — the pose solve puts each child bone head on its target, and
  two-bone chains keep both segments at their exact lengths.
- `test_weights.py` — normalized weights, two bones per vertex, no zero-total
  vertex, and that a vertex at the elbow blends across the joint rather than
  sitting fully on one bone.
- `test_loft.py` — consistent winding, no degenerate faces, closed caps.
- `test_vector.py` — the tuple helpers, including degenerate and zero-length
  cases.

Acceptance is visual and yours, not mine:

- Body reads continuous under raking light. A visible joint line means the
  weights or the preserve-volume mode is wrong.
- Head reads as a face from both cameras.
- Limb lengths still verify within 1%.

## Risks

**Boolean sockets on a smooth-shaded mesh leave shading seams.** The socket
region gets its own tight edge loops instead of relying on the boolean's
topology. This is the most likely thing to need a second pass.

**The lofted head is the fiddliest code in the project.** It is where to expect
iteration on renders.

**Analytic weights may need per-joint tuning.** The shoulder and hip blend zones
are parameters, not derived values, and will probably need adjusting by eye
against renders.

**Performance.** Voxel remesh is not used in this design, so there is no
CPU-time cliff. Lofts are cheap.
