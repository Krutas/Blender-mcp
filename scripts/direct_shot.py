#!/usr/bin/env python3
"""Ask the live add-on for a screenshot and print the metadata + save the PNG."""
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from blender_mcp.client import BlenderClient  # noqa: E402

port = int(sys.argv[1]) if len(sys.argv) > 1 else 9877
png, meta = BlenderClient(port=port, timeout=300).screenshot(max_size=512)
print(json.dumps(meta, indent=2))
out = "/root/blender-mcp/out/direct_shot.png"
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "wb") as fh:
    fh.write(png)
print(f"wrote {out} ({len(png)} bytes)")
