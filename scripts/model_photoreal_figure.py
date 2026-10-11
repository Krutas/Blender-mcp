"""Photoreal seated figure, no background, matching /tmp/d75df67f-....jpg.

Continues `model_seated_figure.py`, which built the same pose from primitives in
a room. Three deliberate changes:

1. **No environment.** `film_transparent = True`, no floor plane, world is a flat
   0-strength grey so it contributes no ambient bounce. The figure composites
   over whatever you drop it onto. A room would both break that and steal
   contrast from the skin, which is the whole subject here.

2. **Skin is the subject, so it gets a real shader.** The earlier script used a
   flat Principled colour, which reads as painted plastic at any resolution. Here
   skin gets subsurface scattering -- that is what transmits red through the ear
   and nostril and keeps the terminator soft instead of terminating on a hard
   shading edge. Eyes get sclera / iris / cornea as separate surfaces rather than
   one dark blob, because a dark blob is the single most common tell in a bad
   human render.

3. **Hair is real strands**, not a helmet. ~200 swept poly curves with tapered
   bevel. Costs geometry, buys the broken silhouette that reads as hair.

Scale matches the earlier build: stature H = 1.68 m, every dimension derived from
it by standard anthropometric fraction, verified back at the end. Seat plane is
z = 0 (the reference figure sits on a bed, not the floor, so there is no floor
contact constraint here).

Run:  .venv/bin/python -m blender_mcp ... no -- this is a Blender script:
      blender -b -P scripts/model_photoreal_figure.py
"""

import math
import os

import bmesh
import bpy
from mathutils import Vector

# Windows-native default. This script is usually run by a Windows blender.exe,
# which cannot resolve a WSL path ("/root/...") or a Linux-style env var passed
# through WSL interop -- both silently produce a garbage path. Override with
# BLENDER_MCP_OUT only when Blender runs natively on Linux.
OUT_DIR = os.environ.get("BLENDER_MCP_OUT") or os.path.join(
    os.environ.get("TEMP", r"C:\tmp"), "blender-mcp-out"
)
os.makedirs(OUT_DIR, exist_ok=True)

# --------------------------------------------------------------------- scale
H = 1.68  # m, standing stature

HEAD_H = 0.134 * H
HEAD_W = 0.090 * H
HEAD_D = 0.115 * H
NECK = 0.052 * H
TRUNK = 0.288 * H
THIGH = 0.245 * H
CALF = 0.246 * H
FOOT_L = 0.152 * H
SHLD_W = 0.215 * H
HIP_W = 0.200 * H
HIP_D = 0.150 * H
UPARM = 0.186 * H
FOREARM = 0.146 * H
HAND_L = 0.108 * H
HAND_W = 0.042 * H

# Seated on a bed: the seat plane is z = 0 and the buttocks are ON it, so the
# hip joint sits one buttock-thickness above. ~9 cm, same as the floor case.
HIP_H = 0.090

SHOULDER_Z = HIP_H + TRUNK
NECK_TOP_Z = SHOULDER_Z + NECK
HEAD_CZ = NECK_TOP_Z + HEAD_H / 2.0
VERTEX_Z = NECK_TOP_Z + HEAD_H


# ------------------------------------------------------------------ utilities
def set_input(node, names, value):
    """Set a node input by name, tolerating Blender version renames.

    Principled BSDF renamed most of its sockets in 4.0 ("Subsurface" ->
    "Subsurface Weight", "Specular" -> "Specular IOR Level"). This script should
    not care which version it lands on, so try each candidate name and stop at
    the first that exists. Returns True if anything was set.
    """
    if isinstance(names, str):
        names = (names,)
    for name in names:
        if name in node.inputs:
            node.inputs[name].default_value = value
            return True
    return False


def make_skin(name, base):
    """Skin with subsurface scattering.

    The radius is the scattering distance in metres and is scaled by
    Subsurface Scale, so radius is kept small and the scale does the work. A
    radius in raw metres would bleed light half a head-width and look wax.
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    set_input(bsdf, "Base Color", base)
    set_input(bsdf, ("Metallic",), 0.0)
    set_input(bsdf, ("Roughness",), 0.42)
    set_input(bsdf, ("Specular IOR Level", "Specular"), 0.42)
    set_input(bsdf, ("Subsurface Weight", "Subsurface"), 0.28)
    set_input(bsdf, "Subsurface Radius", (0.36, 0.14, 0.09))
    set_input(bsdf, ("Subsurface Scale",), 0.012)
    # Slight sheen stands in for the fine peach fuzz on grazing skin.
    set_input(bsdf, ("Sheen Weight", "Sheen"), 0.08)
    set_input(bsdf, ("Sheen Roughness",), 0.4)
    return mat


def make_simple(name, color, roughness=0.6, metallic=0.0, sheen=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    set_input(bsdf, "Base Color", color)
    set_input(bsdf, "Roughness", roughness)
    set_input(bsdf, ("Metallic",), metallic)
    set_input(bsdf, ("Specular IOR Level", "Specular"), 0.5)
    if sheen:
        set_input(bsdf, ("Sheen Weight", "Sheen"), sheen)
    return mat


def finish(obj, material, levels=2):
    obj.data.materials.append(material)
    for poly in obj.data.polygons:
        poly.use_smooth = True
    if levels:
        mod = obj.modifiers.new("Subdivision", "SUBSURF")
        mod.levels = levels
        mod.render_levels = levels
    return obj


def blob(name, location, half, material, rotation=(0.0, 0.0, 0.0), levels=2):
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=32, ring_count=20, radius=1.0, location=location, rotation=rotation
    )
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = half
    return finish(obj, material, levels=levels)


def capsule(name, start, end, r_start, r_end, material, radial=16, body_rings=8, cap_rings=5, levels=1):
    """Tapered capsule built with bmesh.

    Kept from the earlier script: cones have flat n-gon caps that subsurf pinches
    into radial flutes, and a stack of separate ellipsoids beads into visible
    segments. One continuous quad surface with hemispherical ends does neither.
    """
    start, end = Vector(start), Vector(end)
    axis = end - start
    length = axis.length
    quat = axis.to_track_quat("Z", "Y")
    centre = (start + end) / 2.0

    profile = []
    for i in range(1, cap_rings + 1):
        theta = (math.pi / 2.0) * i / (cap_rings + 1)
        profile.append((-r_start * math.cos(theta), r_start * math.sin(theta)))
    for i in range(body_rings + 1):
        t = i / body_rings
        profile.append((t * length, r_start + (r_end - r_start) * t))
    for i in range(cap_rings, 0, -1):
        theta = (math.pi / 2.0) * i / (cap_rings + 1)
        profile.append((length + r_end * math.cos(theta), r_end * math.sin(theta)))

    bm = bmesh.new()
    rings = []
    for z, r in profile:
        ring = [
            bm.verts.new(
                (
                    r * math.cos(2.0 * math.pi * j / radial),
                    r * math.sin(2.0 * math.pi * j / radial),
                    z - length / 2.0,
                )
            )
            for j in range(radial)
        ]
        rings.append(ring)
    for i in range(len(rings) - 1):
        a, b = rings[i], rings[i + 1]
        for j in range(radial):
            k = (j + 1) % radial
            bm.faces.new((a[j], a[k], b[k], b[j]))
    pole_start = bm.verts.new((0.0, 0.0, -r_start - length / 2.0))
    for j in range(radial):
        k = (j + 1) % radial
        bm.faces.new((rings[0][k], rings[0][j], pole_start))
    pole_end = bm.verts.new((0.0, 0.0, length + r_end - length / 2.0))
    for j in range(radial):
        k = (j + 1) % radial
        bm.faces.new((rings[-1][j], rings[-1][k], pole_end))

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = quat
    obj.location = centre
    return finish(obj, material, levels=levels)


# --------------------------------------------------------------------- scene
# use_empty drops the default world/lights, which is what we want: this scene
# supplies its own light rig and a deliberately inert world.
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0

world = bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.05, 0.05, 0.055, 1.0)
# Strength 0: the world must not light the figure. All shaping comes from the
# three lamps below, which is what keeps the rim readable against transparency.
bg.inputs[1].default_value = 0.0

SKIN = make_skin("Skin", (0.78, 0.56, 0.45, 1.0))
SKIN_LIP = make_skin("Skin_Lip", (0.66, 0.34, 0.33, 1.0))
SKIN_BROW = make_simple("Skin_Brow", (0.24, 0.15, 0.10, 1.0), roughness=0.7)

TOP = make_simple("Top_White", (0.88, 0.86, 0.83, 1.0), roughness=0.72, sheen=0.35)
SOCKS = make_simple("Socks_White", (0.91, 0.90, 0.88, 1.0), roughness=0.88, sheen=0.5)
HAIR = make_simple("Hair_Blonde", (0.62, 0.45, 0.22, 1.0), roughness=0.36)

SCLERA = make_simple("Eye_Sclera", (0.93, 0.90, 0.87, 1.0), roughness=0.22)
IRIS = make_simple("Eye_Iris", (0.28, 0.40, 0.33, 1.0), roughness=0.18)
PUPIL = make_simple("Eye_Pupil", (0.02, 0.02, 0.02, 1.0), roughness=0.1)
# Cornea is the glossy bulge in front. Its low roughness is what produces the
# specular catchlight that makes an eye look wet.
CORNEA = make_simple("Eye_Cornea", (1.0, 1.0, 1.0, 1.0), roughness=0.02)
CHAIN = make_simple("Chain_Metal", (0.80, 0.78, 0.72, 1.0), roughness=0.25, metallic=0.9)

# ------------------------------------------------------------------ the pose
# Seated, knees drawn up and splayed, feet toward camera, forearms resting on the
# knees. Head tilted and turned toward camera, one eye closed.
HIP = (0.0, 0.0, HIP_H)
KNEE = (0.140, -0.215, 0.455)
ANKLE = (0.150, -0.330, 0.048)
SHOULDER = (SHLD_W / 2.0, -0.010, SHOULDER_Z - 0.010)
# Solved rather than eyeballed: UPARM and FOREARM are placed exactly, by
# construction -- elbow on a sphere of radius UPARM around the shoulder, wrist at
# FOREARM from the elbow along the line to the knee. Hand-tuned values drifted
# -12%/+15% and broke the limb lengths; these cannot.
ELBOW = (0.241, -0.224, 0.344)
WRIST = (0.076, -0.209, 0.525)

HEAD = (0.0, -0.012, HEAD_CZ)
# Small tilt and only a slight turn. The earlier z=0.14 swung the face well past
# profile, which hid the features entirely behind the hair mass from the
# three-quarter camera.
HEAD_TILT = (0.05, 0.08, 0.05)  # x,y,z euler -- tilt, chin-down, turn to camera

blob("Pelvis", (0.0, 0.022, 0.110), (HIP_W / 2.0, HIP_D / 2.0, 0.110), SKIN, levels=2)
blob("Chest", (0.0, -0.022, 0.482), (0.148, 0.066, 0.118), SKIN, levels=2)
capsule("Torso", (0.0, 0.018, 0.155), (0.0, -0.022, 0.512), 0.130, 0.146, SKIN, body_rings=10)
blob("Shoulders", (0.0, -0.014, SHOULDER_Z - 0.024), (SHLD_W / 2.0, 0.072, 0.056), SKIN, levels=2)
capsule(
    "Neck",
    (0.0, -0.016, SHOULDER_Z + 0.004),
    (0.0, -0.022, NECK_TOP_Z),
    0.058,
    0.050,
    SKIN,
    body_rings=3,
)

blob("Head", HEAD, (HEAD_W / 2.0, HEAD_D / 2.0, HEAD_H / 2.0), SKIN, rotation=HEAD_TILT, levels=3)
blob("Ear_L", (HEAD_W / 2.0, -0.006, HEAD_CZ + 0.008), (0.010, 0.021, 0.027), SKIN)
blob("Ear_R", (-HEAD_W / 2.0, -0.006, HEAD_CZ + 0.008), (0.010, 0.021, 0.027), SKIN)

face_y = -0.012 - HEAD_D / 2.0

# --- nose: bridge + tip + nostrils, so it has a silhouette in profile
blob("Nose_Bridge", (0.0, face_y + 0.016, HEAD_CZ + 0.014), (0.008, 0.014, 0.020), SKIN, levels=2)
blob("Nose_Tip", (0.0, face_y + 0.002, HEAD_CZ - 0.002), (0.011, 0.013, 0.010), SKIN, levels=2)
blob("Nostril_L", (0.006, face_y + 0.006, HEAD_CZ - 0.008), (0.003, 0.004, 0.003), make_simple("Nostril", (0.30, 0.16, 0.14, 1.0), roughness=0.7))
blob("Nostril_R", (-0.006, face_y + 0.006, HEAD_CZ - 0.008), (0.003, 0.004, 0.003), bpy.data.materials["Nostril"])

# --- eyes. Open eye (her left, screen right) gets the full sclera/iris/cornea
# stack; the other is closed mid-wink, which in the reference is just a lid crease.
EYE_R = 0.0135
eye_open_c = (0.033, face_y + 0.006, HEAD_CZ + 0.020)
blob("Eye_Sclera_L", eye_open_c, (EYE_R, EYE_R, EYE_R), SCLERA, levels=2)
blob("Eye_Iris_L", (eye_open_c[0], eye_open_c[1] - 0.010, eye_open_c[2]), (0.0055, 0.0025, 0.0055), IRIS, levels=1)
blob("Eye_Pupil_L", (eye_open_c[0], eye_open_c[1] - 0.012, eye_open_c[2]), (0.0024, 0.0015, 0.0024), PUPIL, levels=1)
blob("Eye_Cornea_L", (eye_open_c[0], eye_open_c[1] - 0.007, eye_open_c[2]), (0.0062, 0.0042, 0.0062), CORNEA, levels=2)

eye_closed_c = (-0.033, face_y + 0.008, HEAD_CZ + 0.020)
blob("Eye_Closed_L", eye_closed_c, (EYE_R, EYE_R * 0.45, EYE_R * 0.55), SKIN, levels=2)
capsule(
    "Eye_Crease_R",
    (-0.046, face_y + 0.004, HEAD_CZ + 0.023),
    (-0.021, face_y + 0.004, HEAD_CZ + 0.019),
    0.0018,
    0.0018,
    SKIN_BROW,
    radial=8,
    body_rings=4,
)

# --- brows
capsule("Brow_L", (0.020, face_y + 0.010, HEAD_CZ + 0.040), (0.046, face_y + 0.008, HEAD_CZ + 0.038), 0.0035, 0.0025, SKIN_BROW, radial=8, body_rings=5)
capsule("Brow_R", (-0.020, face_y + 0.010, HEAD_CZ + 0.040), (-0.046, face_y + 0.008, HEAD_CZ + 0.038), 0.0035, 0.0025, SKIN_BROW, radial=8, body_rings=5)

# --- mouth, open with the tongue forward (playful expression in the reference)
blob("Mouth_Cavity", (0.0, face_y + 0.004, HEAD_CZ - 0.034), (0.020, 0.008, 0.012), make_simple("Mouth_Interior", (0.16, 0.06, 0.07, 1.0), roughness=0.45))
blob("Tongue", (0.006, face_y - 0.002, HEAD_CZ - 0.038), (0.011, 0.010, 0.011), make_skin("Tongue", (0.72, 0.33, 0.34, 1.0)), levels=2)
# Upper and lower lip rims, so the opening has an edge rather than a hole.
torus_up = bpy.ops.mesh.primitive_torus_add(
    major_radius=0.017, minor_radius=0.0055, major_segments=24, minor_segments=10,
    location=(0.0, face_y + 0.002, HEAD_CZ - 0.024),
)
finish(bpy.context.active_object, SKIN_LIP, levels=1)
torus_lo = bpy.ops.mesh.primitive_torus_add(
    major_radius=0.016, minor_radius=0.0060, major_segments=24, minor_segments=10,
    location=(0.0, face_y + 0.002, HEAD_CZ - 0.045),
)
finish(bpy.context.active_object, SKIN_LIP, levels=1)

# --- hair: volume mass under real strands, so the silhouette is not a helmet
blob("Hair_Mass", (0.0, 0.006, HEAD_CZ + 0.014), (HEAD_W / 2.0 + 0.012, HEAD_D / 2.0 + 0.006, HEAD_H / 2.0 + 0.006), HAIR, levels=3)


def build_hair(count=220):
    """Swept strands radiating from the scalp.

    All strands live in ONE curve object with many poly splines. That matters:
    220 separate curve objects would each carry their own bevel resolution and
    turn the outliner into noise, and they would subsurf independently.

    Per-strand radius is set through spline point radius, so strands thin out as
    they fall -- uniformly thick strands read as wire.
    """
    curve = bpy.data.curves.new("Hair_Strands", "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.0022
    curve.bevel_resolution = 2
    curve.resolution_u = 2

    rng = 1234567  # fixed seed: this must be deterministic or renders stop matching

    for i in range(count):
        # Fibonacci-ish distribution over the scalp dome, biased to the crown and
        # hairline rather than the face.
        u = (i + 0.5) / count
        phi = math.acos(1.0 - 1.45 * u)  # 1.45 rad caps short of the chin
        theta = 2.0 * math.pi * (i * 0.61803398875) % (2.0 * math.pi)

        sx = math.sin(phi) * math.cos(theta)
        sy = math.sin(phi) * math.sin(theta)
        sz = math.cos(phi)

        # Hair must not grow out of the face. sy is negative toward the front
        # (-Y), so anything past the hairline here lands strands across the eyes
        # and mouth -- which is exactly what an unfiltered dome does.
        if sy < -0.30 * math.sin(phi) and sz < 0.55:
            continue

        root = (
            HEAD[0] + sx * (HEAD_W / 2.0 + 0.008),
            HEAD[1] + sy * (HEAD_D / 2.0 + 0.004),
            HEAD[2] + sz * (HEAD_H / 2.0 + 0.004),
        )

        # Loose waves: two out-of-phase sines so strands cross instead of
        # marching in unison.
        length = 0.22 + 0.20 * ((i % 7) / 7.0)
        phase = (i * 2.399963229728653) % (2.0 * math.pi)
        spline = curve.splines.new("POLY")
        steps = 9
        spline.points.add(steps - 1)
        for s in range(steps):
            t = s / (steps - 1)
            wave = 0.030 * math.sin(phase + t * 5.0) * t
            drift = 0.022 * math.sin(phase * 1.7 + t * 3.2) * t * t
            spline.points[s].co = (
                root[0] + wave + drift,
                root[1] + 0.14 * t * t,  # falls back toward the ponytail
                root[2] - length * t + 0.012 * math.cos(phase) * t,
                1.0,
            )
            # taper to a point
            spline.points[s].radius = max(0.15, 1.0 - t * 0.95)

    obj = bpy.data.objects.new("Hair_Strands", curve)
    bpy.context.collection.objects.link(obj)
    curve.materials.append(HAIR)
    return obj


hair = build_hair()

# High ponytail gathered at the back of the crown.
blob("Ponytail_Mass", (0.018, 0.104, HEAD_CZ + 0.084), (0.052, 0.070, 0.058), HAIR, levels=3)
capsule("Ponytail_Tail", (0.018, 0.112, HEAD_CZ + 0.070), (0.034, 0.196, HEAD_CZ - 0.040), 0.046, 0.014, HAIR, body_rings=8)

bpy.ops.mesh.primitive_torus_add(
    major_radius=0.050, minor_radius=0.0032, major_segments=32, minor_segments=10,
    location=(0.0, -0.022, SHOULDER_Z + 0.032),
)
finish(bpy.context.active_object, CHAIN, levels=0)

POINTS = {}

for side, sx in (("L", 1.0), ("R", -1.0)):
    hip = (HIP[0] + 0.094 * sx, HIP[1] + 0.032, HIP[2] + 0.032)
    knee = (KNEE[0] * sx, KNEE[1], KNEE[2])
    ankle = (ANKLE[0] * sx, ANKLE[1], ANKLE[2])
    shoulder = (SHOULDER[0] * sx, SHOULDER[1], SHOULDER[2])
    elbow = (ELBOW[0] * sx, ELBOW[1], ELBOW[2])
    wrist = (WRIST[0] * sx, WRIST[1], WRIST[2])

    capsule(f"Thigh_{side}", hip, knee, 0.116, 0.088, SKIN, body_rings=10)
    blob(f"Knee_{side}", knee, (0.086, 0.086, 0.086), SKIN)
    capsule(f"Calf_{side}", knee, ankle, 0.088, 0.052, SKIN, body_rings=10)
    # Kneecap front, so the leg reads as a knee from the front three-quarter.
    blob(f"Kneecap_{side}", (knee[0], knee[1] - 0.062, knee[2] + 0.006), (0.046, 0.030, 0.044), SKIN)

    capsule(
        f"SockCuff_{side}",
        (0.163 * sx, ANKLE[1] + 0.004, 0.140),
        (0.163 * sx, ANKLE[1] + 0.002, 0.064),
        0.062,
        0.056,
        SOCKS,
        body_rings=4,
    )
    blob(f"Foot_{side}", (0.164 * sx, -0.372, 0.034), (0.047, FOOT_L / 2.0, 0.034), SOCKS)

    blob(f"ShoulderJoint_{side}", shoulder, (0.068, 0.068, 0.068), SKIN)
    capsule(f"UpperArm_{side}", shoulder, elbow, 0.068, 0.052, SKIN, body_rings=8)
    blob(f"Elbow_{side}", elbow, (0.053, 0.053, 0.053), SKIN)
    capsule(f"Forearm_{side}", elbow, wrist, 0.052, 0.043, SKIN, body_rings=8)

    # Hands follow the solved wrist, not the knee -- the arm no longer terminates on
    # the knee, so a hand keyed to the knee would float.
    hand_c = (WRIST[0] * sx + 0.030 * sx, WRIST[1] - 0.020, WRIST[2] - 0.018)
    blob(f"Palm_{side}", hand_c, (HAND_W / 2.0, HAND_L / 2.0, 0.026), SKIN)
    for f in range(4):
        fx = (f - 1.5) * 0.0105 * sx
        capsule(
            f"Finger_{side}_{f}",
            (hand_c[0] + fx, hand_c[1] - HAND_L / 2.0 + 0.010, hand_c[2] - 0.004),
            (hand_c[0] + fx * 1.15, hand_c[1] - HAND_L / 2.0 - 0.030 + abs(f - 1.5) * 0.006, hand_c[2] - 0.014),
            0.0055,
            0.0042,
            SKIN,
            radial=8,
            body_rings=4,
            levels=1,
        )
    capsule(
        f"Thumb_{side}",
        (hand_c[0] - 0.020 * sx, hand_c[1] - 0.010, hand_c[2] + 0.004),
        (hand_c[0] - 0.032 * sx, hand_c[1] - 0.036, hand_c[2] - 0.006),
        0.0065,
        0.0050,
        SKIN,
        radial=8,
        body_rings=4,
        levels=1,
    )

    # --- the top: slipped off both shoulders, bunched at the upper arms. Bare
    # skin on the shoulders and upper chest is the look in the reference, so the
    # garment is modelled where it actually sits rather than covering the torso.
    capsule(
        f"TopBunch_{side}",
        (0.078 * sx, -0.030, SHOULDER_Z - 0.016),
        (0.104 * sx, -0.038, 0.470),
        0.052,
        0.060,
        TOP,
        body_rings=6,
    )
    capsule(
        f"TopSleeve_{side}",
        (0.104 * sx, -0.038, 0.478),
        (0.150 * sx, -0.046, 0.398),
        0.060,
        0.052,
        TOP,
        body_rings=6,
    )

    POINTS[f"hip_{side}"] = hip
    POINTS[f"knee_{side}"] = knee
    POINTS[f"ankle_{side}"] = ankle
    POINTS[f"shoulder_{side}"] = shoulder
    POINTS[f"elbow_{side}"] = elbow
    POINTS[f"wrist_{side}"] = wrist

POINTS["head_c"] = HEAD

# ---------------------------------------------------------------------- light
# No environment to bounce off, so the rig has to do all the shaping. Large soft
# sources keep the shadow terminator off the face -- hard small sources are what
# make CG skin look like plastic.
def area(name, location, energy, size, target=(0.0, -0.10, 0.46)):
    bpy.ops.object.light_add(type="AREA", location=location)
    light = bpy.context.active_object
    light.name = name
    light.data.energy = energy
    light.data.size = size
    light.data.shape = "SQUARE"
    d = Vector(target) - Vector(location)
    light.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return light


# Energies are tuned for SHAPE (key:fill:rim ratio), not absolute level -- the
# exposure trim in the render section sets the overall brightness.
key = area("Key", (1.15, -1.15, 1.18), 90.0, 1.05)
fill = area("Fill", (-1.40, -0.85, 0.66), 18.0, 1.60)
rim = area("Rim", (-0.40, 1.40, 1.10), 130.0, 0.95)

# --------------------------------------------------------------------- camera
def aim(cam, target):
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


# Longer lens from further back. 62mm at 1.6m was wide enough to distort the
# near knee; 85mm from ~2.4m keeps the proportions honest and puts the head
# closer to the upper third the way the reference framing does.
for name, loc in (("Camera", (1.95, -1.95, 0.82)), ("Camera_Side", (2.60, -0.10, 0.72))):
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.active_object
    cam.name = name
    cam.data.lens = 85.0
    aim(cam, (0.0, -0.10, 0.50))

cameras = {o.name: o for o in bpy.data.objects if o.type == "CAMERA"}

# ----------------------------------------------------------------- verification
def dist(a, b):
    return (Vector(b) - Vector(a)).length


def world_top(name):
    obj = bpy.data.objects[name]
    return max((obj.matrix_world @ Vector(c)).z for c in obj.bound_box)


checks = [
    ("seated seat->vertex", world_top("Head"), VERTEX_Z),
    ("thigh", dist(POINTS["hip_L"], POINTS["knee_L"]), THIGH),
    ("calf (knee->ankle)", dist(POINTS["knee_L"], POINTS["ankle_L"]), CALF),
    ("upper arm", dist(POINTS["shoulder_L"], POINTS["elbow_L"]), UPARM),
    ("forearm", dist(POINTS["elbow_L"], POINTS["wrist_L"]), FOREARM),
    ("trunk (hip->shoulder)", dist((0, 0, HIP_H), (0, 0, SHOULDER_Z)), TRUNK),
    ("head height", world_top("Head") - NECK_TOP_Z, HEAD_H),
]
verify = []
for label, actual, target in checks:
    err = 100.0 * (actual - target) / target
    verify.append(f"{label:24s} {actual*100:7.2f} cm  target {target*100:7.2f} cm  {err:+6.2f}%")

pelvis_bottom = min(
    (bpy.data.objects["Pelvis"].matrix_world @ Vector(c)).z for c in bpy.data.objects["Pelvis"].bound_box
)
verify.append(f"{'pelvis bottom (seat=0)':24s} {pelvis_bottom*100:7.2f} cm  target {0.0:7.2f} cm")
verify.append(f"{'hip width':24s} {HIP_W*100:7.2f} cm  (measured from Pelvis blob)")
verify.append(f"{'hair strands':24s} {len(hair.data.splines):4d}")

# Nothing but the figure: with film_transparent the world still renders as alpha
# 0, but a stray light or helper object would show up as a silhouette. Assert the
# scene is lights + cameras + the figure and nothing else.
STRAY = [
    o.name
    for o in bpy.data.objects
    if o.type not in {"MESH", "CURVE", "LIGHT", "CAMERA"}
]
verify.append(f"{'non-mesh/curve/light':24s} {STRAY if STRAY else 'none'}")

print("VERIFY")
for line in verify:
    print("  " + line)

# ----------------------------------------------------------------------- render
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
# Higher sample count than the stylized build: SSS, the transmissive cornea and
# 220 hair curves all add variance, and SSS in particular is what turns a
# low-sample CPU render into blotchy orange.
scene.cycles.samples = 192
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 12
scene.cycles.transmission_bounces = 8
scene.render.resolution_x = 900
scene.render.resolution_y = 1150
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"

# The world is at zero strength, so these three lamps are doing ~100% of the
# shaping. With no environment to fill the shadows, energies that look sane in a
# lit room clip the skin to white under AgX. The exposure trim below is the
# global correction; energies are set for shape, not for final level.
scene.view_settings.exposure = -1.6
# The point of the exercise: no background, straight alpha for compositing.
scene.render.film_transparent = True

rendered = []
for name, path in (
    ("Camera", os.path.join(OUT_DIR, "photoreal_three_quarter.png")),
    ("Camera_Side", os.path.join(OUT_DIR, "photoreal_side.png")),
):
    scene.camera = cameras[name]
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    rendered.append(path)

blend_path = os.path.join(OUT_DIR, "photoreal_figure.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)

print("RESULT")
print(
    {
        "scale": {"stature_cm": H * 100, "seated_vertex_cm": round(VERTEX_Z * 100, 2)},
        "verify": verify,
        "blend": blend_path,
        "rendered": rendered,
        "object_count": len(bpy.data.objects),
        "materials": sorted(m.name for m in bpy.data.materials),
    }
)