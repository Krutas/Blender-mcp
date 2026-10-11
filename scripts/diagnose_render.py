#!/usr/bin/env python3
"""Diagnose why the screenshot path returns a black frame.

Compares the two render strategies the add-on can use, with pixel statistics,
by running directly inside the live Blender session.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from blender_mcp.client import BlenderClient  # noqa: E402

PROBE = r'''
import bpy, os, tempfile

bpy.ops.wm.open_mainfile(filepath="%s")
scene = bpy.context.scene
scene.render.image_settings.file_format = "PNG"
scene.render.resolution_x = 256
scene.render.resolution_y = 144
scene.render.resolution_percentage = 100

def stats(path, label):
    if not os.path.exists(path):
        return {"label": label, "exists": False}
    img = bpy.data.images.load(path, check_existing=False)
    try:
        px = list(img.pixels)          # flat RGBA floats
        n = len(px) // 4
        nonblack = 0
        total = 0.0
        for i in range(0, len(px), 4):
            v = px[i] + px[i+1] + px[i+2]
            total += v
            if v > 0.05:
                nonblack += 1
        return {"label": label, "exists": True, "size": list(img.size),
                "pixels": n, "nonblack": nonblack,
                "nonblack_pct": round(100.0*nonblack/max(1,n), 2),
                "mean_luma": round(total/max(1,n)/3, 5)}
    finally:
        bpy.data.images.remove(img)

out = {}
tmp = tempfile.gettempdir()

full = os.path.join(tmp, "mcpdiag_full.png")
scene.render.filepath = full
try:
    bpy.ops.render.render(write_still=True)
    out["render"] = stats(full, "bpy.ops.render.render")
except Exception as e:
    out["render"] = {"label": "bpy.ops.render.render", "error": repr(e)}

gl = os.path.join(tmp, "mcpdiag_gl.png")
scene.render.filepath = gl
try:
    bpy.ops.render.opengl(write_still=True, view_context=False)
    out["opengl_view_context_false"] = stats(gl, "render.opengl(view_context=False)")
except Exception as e:
    out["opengl_view_context_false"] = {"label": "opengl(view_context=False)", "error": repr(e)}

gl2 = os.path.join(tmp, "mcpdiag_gl2.png")
scene.render.filepath = gl2
try:
    bpy.ops.render.opengl(write_still=True, view_context=True)
    out["opengl_view_context_true"] = stats(gl2, "render.opengl(view_context=True)")
except Exception as e:
    out["opengl_view_context_true"] = {"label": "opengl(view_context=True)", "error": repr(e)}

out["scene"] = {
    "engine": scene.render.engine,
    "camera": scene.camera.name if scene.camera else None,
    "cam_loc": list(scene.camera.location) if scene.camera else None,
    "world": scene.world.name if scene.world else None,
    "background": bpy.app.background,
    "objects": [o.name for o in bpy.data.objects],
}
result = out
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9877)
    parser.add_argument("--blend", default="/root/blender-mcp/out/smoke_scene.blend")
    args = parser.parse_args()

    client = BlenderClient(port=args.port, timeout=300)
    result = client.call("execute_code", {"code": PROBE % args.blend})
    if not result.get("ok"):
        print("PROBE FAILED")
        print(result.get("error"))
        print(result.get("stdout"))
        return 1
    print(json.dumps(json.loads(result["result"]), indent=2))
    if result.get("stdout"):
        print("--- stdout ---")
        print(result["stdout"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
