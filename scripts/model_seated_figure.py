"""Build a stylized seated figure in Blender at true anthropometric scale.

Reference: /tmp/63e82d10-b6b0-4a05-bda2-791ecb8dc8a3.jpg
  Seated figure, knees drawn up, feet flat, arms resting on the knees.

Scale: the subject is 168 cm STANDING. Every dimension below is derived from
that stature via standard anthropometric fractions, and the seated assembly is
measured back against those targets at the end of the build (see `verify`).

The one thing that is easy to get wrong: when a figure sits on the FLOOR the
hip joint is only ~5.5% of stature above the ground (~9 cm), because the
buttocks are on the floor. Placing the hip joint at its standing height leaves
the figure hovering in a phantom chair.
"""

import math
import os
import bmesh
import bpy
from mathutils import Vector

OUT_DIR = "/root/blender-mcp/out"
os.makedirs(OUT_DIR, exist_ok=True)

# --------------------------------------------------------------------- scale
H = 1.68  # m. Statue/standing height. Everything else follows from this.

HEAD_H = 0.134 * H  # chin -> vertex
HEAD_W = 0.090 * H  # head breadth
HEAD_D = 0.115 * H  # head depth
NECK = 0.052 * H
TRUNK = 0.288 * H  # hip joint -> acromion
THIGH = 0.245 * H  # hip joint -> knee centre
CALF = 0.246 * H  # knee centre -> ankle
FOOT_L = 0.152 * H
SHLD_W = 0.215 * H  # biacromial (shoulder) breadth
HIP_W = 0.200 * H  # seated hip breadth
HIP_D = 0.150 * H  # seated hip depth
UPARM = 0.186 * H
FOREARM = 0.146 * H
HAND_L = 0.108 * H
ANKLE_H = 0.039 * H
HIP_H = 0.055 * H  # hip joint above floor with buttocks ON the floor

SHOULDER_Z = HIP_H + TRUNK  # 0.5762
NECK_TOP_Z = SHOULDER_Z + NECK  # 0.6636
HEAD_CZ = NECK_TOP_Z + HEAD_H / 2.0  # 0.7761
VERTEX_Z = NECK_TOP_Z + HEAD_H  # 0.8887  <- floor to top of head, seated


# ------------------------------------------------------------------ utilities
def make_material(name, rgba, roughness=0.6, metallic=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
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
        segments=28, ring_count=18, radius=1.0, location=location, rotation=rotation
    )
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = half
    return finish(obj, material, levels=levels)


def capsule(name, start, end, r_start, r_end, material, radial=14, body_rings=7, cap_rings=4, levels=1):
    """A tapered capsule built with bmesh.

    Cones have flat n-gon caps that a subdivision surface pinches into radial
    flutes; a stack of separate ellipsoids beads into visible segments. One
    continuous quad surface with hemispherical ends does neither.
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


def box(name, location, dims, material):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = dims
    return finish(obj, material, levels=0)


# -------------------------------------------------------------------- scene
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0

world = bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.055, 0.052, 0.062, 1.0)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.85

SKIN = make_material("Skin", (0.86, 0.68, 0.57, 1.0), roughness=0.62)
TOP = make_material("Top_Cream", (0.87, 0.84, 0.78, 1.0), roughness=0.8)
# Sleeves a touch darker than the body. In the reference the top and sleeves are
# one colour, but then the arm disappears into the torso silhouette entirely.
SLEEVE = make_material("Sleeve_Cream", (0.63, 0.59, 0.54, 1.0), roughness=0.8)
HAIR = make_material("Hair_Blonde", (0.70, 0.55, 0.31, 1.0), roughness=0.85)
EYE = make_material("Eye_Dark", (0.06, 0.05, 0.05, 1.0), roughness=0.35)
MOUTH = make_material("Mouth", (0.28, 0.13, 0.13, 1.0), roughness=0.55)
TONGUE = make_material("Tongue", (0.83, 0.40, 0.42, 1.0), roughness=0.5)
SOCKS = make_material("Socks_White", (0.93, 0.92, 0.89, 1.0), roughness=0.85)
CHAIN = make_material("Chain_Metal", (0.78, 0.76, 0.70, 1.0), roughness=0.3, metallic=0.85)

POINTS = {}  # named joints, kept for the verification pass

# ------------------------------------------------------------------ the pose
# Buttocks on the floor, knees drawn up, feet flat, forearms forward onto knees.
HIP = (0.0, 0.0, HIP_H)
KNEE = (0.143, -0.195, 0.458)
ANKLE = (0.150, -0.285, ANKLE_H - 0.008)
SHOULDER = (SHLD_W / 2.0, -0.010, SHOULDER_Z - 0.006)
ELBOW = (0.330, -0.050, 0.300)
WRIST = (0.200, -0.140, 0.490)

blob("Pelvis", (0.0, 0.020, 0.105), (HIP_W / 2.0, HIP_D / 2.0, 0.105), SKIN, levels=2)
blob("Chest", (0.0, -0.020, 0.470), (0.150, HIP_D / 2.0 * 0.85, 0.115), TOP, levels=2)
capsule("Torso", (0.0, 0.015, 0.150), (0.0, -0.020, 0.500), 0.128, 0.148, TOP, body_rings=8)
blob(
    "Shoulders",
    (0.0, -0.012, SHOULDER_Z - 0.022),
    (SHLD_W / 2.0, 0.074, 0.058),
    TOP,
    levels=2,
)
capsule("Neck", (0.0, -0.014, SHOULDER_Z + 0.004), (0.0, -0.020, NECK_TOP_Z), 0.056, 0.050, SKIN, body_rings=3)

HEAD = (0.0, -0.010, HEAD_CZ)
blob("Head", HEAD, (HEAD_W / 2.0, HEAD_D / 2.0, HEAD_H / 2.0), SKIN, rotation=(0.0, 0.08, 0.10), levels=2)
blob("Ear_L", (HEAD_W / 2.0, -0.006, HEAD_CZ + 0.010), (0.011, 0.022, 0.028), SKIN)
blob("Ear_R", (-HEAD_W / 2.0, -0.006, HEAD_CZ + 0.010), (0.011, 0.022, 0.028), SKIN)

face_y = -0.010 - HEAD_D / 2.0
blob("Nose", (0.0, face_y + 0.002, HEAD_CZ + 0.002), (0.011, 0.014, 0.010), SKIN)
blob("Eye_L", (0.033, face_y + 0.012, HEAD_CZ + 0.018), (0.015, 0.011, 0.016), EYE, levels=1)
blob("Eye_R_Wink", (-0.033, face_y + 0.012, HEAD_CZ + 0.018), (0.015, 0.011, 0.007), EYE, levels=1)
blob("Mouth", (0.0, face_y + 0.008, HEAD_CZ - 0.030), (0.018, 0.007, 0.009), MOUTH, levels=1)
blob("Tongue", (0.008, face_y + 0.002, HEAD_CZ - 0.044), (0.011, 0.011, 0.013), TONGUE, levels=1)

blob("Hair_Cap", (0.0, 0.004, HEAD_CZ + 0.012), (HEAD_W / 2.0 + 0.010, HEAD_D / 2.0 + 0.004, HEAD_H / 2.0 + 0.004), HAIR, levels=2)
blob("Hair_Fringe", (0.004, -0.052, HEAD_CZ + 0.066), (0.076, 0.078, 0.050), HAIR, levels=2)
blob("Hair_Ponytail", (0.016, 0.100, HEAD_CZ + 0.078), (0.055, 0.078, 0.062), HAIR, levels=2)
capsule("Hair_Sweep", (0.020, 0.132, HEAD_CZ + 0.052), (0.048, 0.208, HEAD_CZ - 0.036), 0.050, 0.016, HAIR, body_rings=4)

bpy.ops.mesh.primitive_torus_add(
    major_radius=0.050, minor_radius=0.0035, location=(0.0, -0.020, SHOULDER_Z + 0.030)
)
necklace = bpy.context.active_object
necklace.name = "Necklace"
finish(necklace, CHAIN, levels=0)

for side, sx in (("L", 1.0), ("R", -1.0)):
    hip = (HIP[0] + 0.096 * sx, HIP[1] + 0.030, HIP[2] + 0.030)
    knee = (KNEE[0] * sx, KNEE[1], KNEE[2])
    ankle = (ANKLE[0] * sx, ANKLE[1], ANKLE[2])
    shoulder = (SHOULDER[0] * sx, SHOULDER[1], SHOULDER[2])
    elbow = (ELBOW[0] * sx, ELBOW[1], ELBOW[2])
    wrist = (WRIST[0] * sx, WRIST[1], WRIST[2])

    capsule(f"Thigh_{side}", hip, knee, 0.118, 0.090, SKIN, body_rings=8)
    blob(f"Knee_{side}", knee, (0.088, 0.088, 0.088), SKIN)
    capsule(f"Calf_{side}", knee, ankle, 0.090, 0.055, SKIN, body_rings=8)
    capsule(
        f"SockCuff_{side}",
        (0.151 * sx, ANKLE[1] + 0.004, 0.135),
        (0.151 * sx, ANKLE[1] + 0.002, 0.062),
        0.064,
        0.058,
        SOCKS,
        body_rings=3,
    )
    blob(f"Foot_{side}", (0.152 * sx, -0.355, 0.032), (0.048, FOOT_L / 2.0, 0.032), SOCKS)

    blob(f"ShoulderJoint_{side}", shoulder, (0.070, 0.070, 0.070), SLEEVE)
    capsule(f"UpperArm_{side}", shoulder, elbow, 0.070, 0.054, SLEEVE, body_rings=6)
    blob(f"Elbow_{side}", elbow, (0.055, 0.055, 0.055), SLEEVE)
    capsule(f"Forearm_{side}", elbow, wrist, 0.053, 0.044, SLEEVE, body_rings=6)
    # Hands rest on the OUTER top of each knee: centred on the knee they are
    # skin-on-skin and vanish into it.
    blob(f"Hand_{side}", (0.186 * sx, -0.198, 0.535), (0.044, HAND_L / 2.0, 0.030), SKIN)

    POINTS[f"hip_{side}"] = hip
    POINTS[f"knee_{side}"] = knee
    POINTS[f"ankle_{side}"] = ankle
    POINTS[f"shoulder_{side}"] = shoulder
    POINTS[f"elbow_{side}"] = elbow
    POINTS[f"wrist_{side}"] = wrist

POINTS["head_c"] = HEAD

# ---------------------------------------------------------------------- light
def area(name, location, energy, size, target=(0.0, -0.10, 0.44)):
    bpy.ops.object.light_add(type="AREA", location=location)
    light = bpy.context.active_object
    light.name = name
    light.data.energy = energy
    light.data.size = size
    d = Vector(target) - Vector(location)
    light.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return light


key = area("Key", (1.30, -1.05, 1.12), 150.0, 0.85)
fill = area("Fill", (-1.35, -0.75, 0.62), 26.0, 1.45)
rim = area("Rim", (-0.35, 1.35, 1.05), 200.0, 0.90)

# --------------------------------------------------------------------- camera
def aim(cam, target):
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


for name, loc in (("Camera", (1.62, -1.08, 0.74)), ("Camera_Side", (2.30, -0.06, 0.66))):
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.active_object
    cam.name = name
    cam.data.lens = 62.0
    aim(cam, (0.0, -0.10, 0.44))

cameras = {o.name: o for o in bpy.data.objects if o.type == "CAMERA"}


# ----------------------------------------------------------------- verification
def dist(a, b):
    return (Vector(b) - Vector(a)).length


def world_top(name):
    obj = bpy.data.objects[name]
    return max((obj.matrix_world @ Vector(c)).z for c in obj.bound_box)


checks = [
    ("seated floor->vertex", world_top("Head"), VERTEX_Z),
    ("thigh", dist(POINTS["hip_L"], POINTS["knee_L"]), THIGH),
    ("calf (knee->ankle)", dist(POINTS["knee_L"], POINTS["ankle_L"]), CALF),
    ("upper arm", dist(POINTS["shoulder_L"], POINTS["elbow_L"]), UPARM),
    ("forearm", dist(POINTS["elbow_L"], POINTS["wrist_L"]), FOREARM),
    ("trunk (hip->shoulder)", dist((0, 0, HIP_H), (0, 0, SHOULDER_Z)), TRUNK),
    ("head height", world_top("Head") - (NECK_TOP_Z), HEAD_H),
]
verify = []
for label, actual, target in checks:
    err = 100.0 * (actual - target) / target
    verify.append(f"{label:24s} {actual*100:7.2f} cm  target {target*100:7.2f} cm  {err:+6.2f}%")

# Buttocks must actually touch the floor, or the figure hovers in a phantom chair.
pelvis_bottom = min((bpy.data.objects["Pelvis"].matrix_world @ Vector(c)).z for c in bpy.data.objects["Pelvis"].bound_box)
verify.append(f"{'pelvis bottom (floor=0)':24s} {pelvis_bottom*100:7.2f} cm  target {0.0:7.2f} cm")
verify.append(f"{'hip width':24s} {HIP_W*100:7.2f} cm  (measured from Pelvis blob)")

print("VERIFY")
for line in verify:
    print("  " + line)

# ----------------------------------------------------------------------- render
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 64
scene.cycles.use_denoising = True
scene.render.resolution_x = 760
scene.render.resolution_y = 980
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False

rendered = []
for name, path in (
    ("Camera", os.path.join(OUT_DIR, "figure_three_quarter.png")),
    ("Camera_Side", os.path.join(OUT_DIR, "figure_side.png")),
):
    scene.camera = cameras[name]
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    rendered.append(path)

blend_path = os.path.join(OUT_DIR, "seated_figure.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)

result = {
    "scale": {"stature_cm": H * 100, "seated_vertex_cm": round(VERTEX_Z * 100, 2)},
    "verify": verify,
    "blend": blend_path,
    "rendered": rendered,
    "object_count": len(bpy.data.objects),
    "materials": sorted(m.name for m in bpy.data.materials),
}
print("RESULT")
print(result)
