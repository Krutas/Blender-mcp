#!/usr/bin/env python3
"""End-to-end smoke test: spawn the real MCP server over stdio and call every tool.

This is exactly how Hermes consumes the server, so it exercises the whole chain:
stdio MCP handshake -> tool dispatch -> TCP add-on socket -> bpy on Blender's
main thread -> render -> JSON back.

    python scripts/e2e_smoke.py [--port 9877]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

BUILD_SCENE = """
import math

import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)

# A world is not optional: read_factory_settings(use_empty=True) leaves the
# scene with no world, so everything renders against pure black.
world = bpy.data.worlds.new("SmokeWorld")
world.use_nodes = True
background = world.node_tree.nodes["Background"]
background.inputs["Color"].default_value = (0.05, 0.06, 0.09, 1.0)
background.inputs["Strength"].default_value = 1.0
bpy.context.scene.world = world

bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 0.0))
cube = bpy.context.active_object
cube.name = "SmokeCube"

mat = bpy.data.materials.new("SmokeMat")
mat.use_nodes = True
mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.1, 0.4, 0.9, 1.0)
cube.data.materials.append(mat)

bpy.ops.object.light_add(type="SUN", location=(4.0, -4.0, 6.0))
sun = bpy.context.active_object
sun.data.energy = 4.0
sun.rotation_euler = (0.7, 0.3, 0.5)  # angled, so faces are not all in shadow

# Aim the camera at the cube's centre, not at the origin under it.
location = (4.5, -4.5, 3.2)
bpy.ops.object.camera_add(location=location)
cam = bpy.context.active_object
dx, dy, dz = location
cam.rotation_euler = (math.atan2(math.hypot(dx, dy), dz), 0.0, math.atan2(dy, dx) + math.pi / 2)
cam.data.lens = 50.0
bpy.context.scene.camera = cam

bpy.context.scene.render.engine = "CYCLES"
bpy.context.scene.cycles.samples = 16
bpy.context.scene.render.resolution_x = 960
bpy.context.scene.render.resolution_y = 540

result = {"objects": [o.name for o in bpy.data.objects], "engine": bpy.context.scene.render.engine}
"""


async def run(port: int, max_size: int) -> int:
    env = {
        **{k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "TMPDIR")},
        "BLENDER_MCP_PORT": str(port),
        "BLENDER_MCP_TIMEOUT": "180",
    }
    params = StdioServerParameters(
        command=PYTHON,
        args=["-m", "blender_mcp", "serve"],
        env=env,
        cwd=str(REPO),
    )

    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'ok ' if ok else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
        if not ok:
            failures.append(name)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_tools()
            names = sorted(t.name for t in listed.tools)
            print(f"discovered {len(names)} tools: {', '.join(names)}")
            expected = {
                "blender_status",
                "blender_get_scene_info",
                "blender_list_objects",
                "blender_get_object_info",
                "blender_execute_code",
                "blender_screenshot",
                "blender_save_file",
                "blender_get_versions",
            }
            check("tool discovery", expected.issubset(set(names)), f"missing {sorted(expected - set(names))}" if not expected.issubset(set(names)) else "")

            def is_error(result) -> bool:
                # Field is `is_error` in mcp 2.x, `isError` in 1.x.
                return bool(getattr(result, "is_error", None) or getattr(result, "isError", False))

            async def call(tool, **kwargs):
                result = await session.call_tool(tool, kwargs)
                if is_error(result):
                    raise RuntimeError(f"{tool} failed: {result.content}")
                return result

            def text_of(result):
                for block in result.content:
                    text = getattr(block, "text", None)
                    if text is not None:
                        return text
                return ""

            print("\n-- blender_status --")
            status = json.loads(text_of(await call("blender_status")))
            check("status connected", status.get("connected") is True, str(status.get("blender_version")))
            print(json.dumps(status, indent=2))

            print("\n-- blender_get_versions --")
            versions = json.loads(text_of(await call("blender_get_versions")))
            check("versions reported", bool(versions.get("blender")), versions.get("blender"))
            print(json.dumps(versions, indent=2))

            print("\n-- blender_execute_code (build a scene) --")
            built = json.loads(text_of(await call("blender_execute_code", code=BUILD_SCENE)))
            check("scene built", built.get("ok") is True, built.get("error", ""))
            print(json.dumps(built, indent=2))
            assert built.get("ok"), built.get("error")

            print("\n-- blender_get_scene_info --")
            scene = json.loads(text_of(await call("blender_get_scene_info")))
            check("cube in scene", "SmokeCube" in [o["name"] for o in scene["objects"]])
            check("engine is CYCLES", scene["render_engine"] == "CYCLES", scene["render_engine"])
            check("camera found", len(scene["cameras"]) == 1, str(scene["cameras"]))
            print(f"  scene={scene['scene']} engine={scene['render_engine']} counts={scene['object_counts']}")

            print("\n-- blender_list_objects (filtered) --")
            meshes = json.loads(text_of(await call("blender_list_objects", kind="MESH")))
            check("mesh filter works", [o["name"] for o in meshes["objects"]] == ["SmokeCube"], json.dumps(meshes["objects"]))
            lights = json.loads(text_of(await call("blender_list_objects", kind="LIGHT")))
            check("light filter works", lights["count"] == 1)

            print("\n-- blender_get_object_info --")
            info = json.loads(text_of(await call("blender_get_object_info", name="SmokeCube")))
            check("mesh stats present", info["mesh"]["vertices"] == 8, str(info["mesh"]))
            check("material slot present", info["materials"] == ["SmokeMat"], str(info["materials"]))
            check("tris computed", info["mesh"].get("triangles") == 12, str(info["mesh"].get("triangles")))
            print(json.dumps({k: info[k] for k in ("name", "type", "location", "dimensions", "mesh", "materials")}, indent=2))

            print("\n-- error path: unknown object --")
            err = await session.call_tool("blender_get_object_info", {"name": "DoesNotExist"})
            check("unknown object surfaces as tool error", is_error(err))
            message = text_of(err)
            check("error message is the real reason, not a generic wrapper", "no object named" in message, message.strip().splitlines()[0][:120])
            check("error carries the Blender-side traceback", "Traceback" in message)
            print("  ", message.strip().splitlines()[0][:140])

            print("\n-- blender_screenshot --")
            shot = await call("blender_screenshot", max_size=max_size)
            images = [b for b in shot.content if getattr(b, "type", None) == "image"]
            texts = [getattr(b, "text", "") for b in shot.content if getattr(b, "type", None) == "text"]
            check("returned an image block", len(images) == 1)
            check("returned a metadata block", any("strategy" in t for t in texts))
            raw = texts[0] if texts else ""
            body = raw.split("\n", 1)[1] if raw.startswith("WARNING") else raw
            meta = json.loads(body) if body.strip().startswith("{") else {}
            check("no empty-frame warning", not raw.startswith("WARNING"), raw[:120])
            check(
                "frame actually has content",
                float(meta.get("lit_fraction") or 0) > 0.2,
                f"strategy={meta.get('strategy')} lit_fraction={meta.get('lit_fraction')}",
            )
            if images:
                import base64

                png = base64.b64decode(images[0].data)
                ok_png = png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) > 1000
                check("valid PNG payload", ok_png, f"{len(png)} bytes, mime={images[0].mime_type}")
                out = REPO / "out" / "smoke_render.png"
                out.parent.mkdir(exist_ok=True)
                out.write_bytes(png)
                print(f"  wrote {out} ({len(png)} bytes)")
            print("  ", texts[0].replace("\n", " ") if texts else "")

            print("\n-- blender_save_file --")
            blend = REPO / "out" / "smoke_scene.blend"
            blend.parent.mkdir(exist_ok=True)
            saved = json.loads(text_of(await call("blender_save_file", filepath=str(blend))))
            check("saved", saved.get("saved") is True, saved.get("filepath", ""))

    print()
    if failures:
        print(f"SMOKE TEST FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("SMOKE TEST PASSED - all checks green")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("BLENDER_MCP_PORT", "9877")))
    parser.add_argument("--max-size", type=int, default=512)
    args = parser.parse_args()
    return asyncio.run(run(args.port, args.max_size))


if __name__ == "__main__":
    raise SystemExit(main())
