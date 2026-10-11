"""Geometry for the continuous figure build.

Imported by ``scripts/build_figure.py`` under Blender's ``-P``, and by the test
suite without Blender. Nothing here may import ``bpy``, ``bmesh`` or
``mathutils`` -- keeping the math in plain Python is what makes the loft,
weighting and pose logic testable in a suite that has no Blender to talk to.
"""
