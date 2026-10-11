#!/usr/bin/env python3
"""Render Blender's stock startup scene through the add-on's screenshot path.

The default startup scene (cube + camera + light, correctly framed) is a known
good subject: if this comes back filled and centred, the screenshot pipeline is
sound and any black frame is the caller's scene composition.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from blender_mcp.client import BlenderClient  # noqa: E402

port = int(sys.argv[1]) if len(sys.argv) > 1 else 9877
client = BlenderClient(port=port, timeout=300)

setup = client.call("execute_code", {"code": "import bpy\nbpy.ops.wm.read_homefile(use_empty=False)\nresult = {'objects': [o.name for o in bpy.data.objects], 'camera': bpy.context.scene.camera.name if bpy.context.scene.camera else None, 'engine': bpy.context.scene.render.engine, 'lens': bpy.context.scene.camera.data.lens if bpy.context.scene.camera else None, 'cam_loc': list(bpy.context.scene.camera.location) if bpy.context.scene.camera else None, 'world': bpy.context.scene.world.name if bpy.context.scene.world else None}"})
print("setup:", json.dumps(setup, indent=2))
assert setup["ok"], setup

png, meta = client.screenshot(max_size=512)
print("meta:", json.dumps(meta, indent=2))
out = "/root/blender-mcp/out/startup_scene.png"
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "wb") as fh:
    fh.write(png)
print(f"wrote {out} ({len(png)} bytes)")
