"""Blender executable script: create a NEW demo scene and save to a NEW file.

blender --background --factory-startup --python examples/create_blender_demo.py -- --output leg_demo.blend
No photorealistic assets: this is a millimetre/coordinate/geometry test fixture.
"""
import argparse
import math
import sys
from pathlib import Path
import bpy


def create_demo(output):
    output=Path(output).resolve()
    if output.exists(): raise RuntimeError('output exists; choose a new filename')
    if bpy.data.objects.get('ZC_ChairLeg'): raise RuntimeError('demo object names already exist')
    scene=bpy.data.scenes.new('ZoneCoordDemo')
    if not bpy.context.window: raise RuntimeError('Blender context has no active window')
    bpy.context.window.scene=scene
    scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=1.0
    scene.unit_settings.length_unit='MILLIMETERS'
    room=bpy.data.objects.new('ZC_RoomOrigin',None);scene.collection.objects.link(room)
    room.empty_display_type='PLAIN_AXES';room.empty_display_size=0.2
    chair=bpy.data.objects.new('ZC_Chair',None);scene.collection.objects.link(chair)
    chair.parent=room;chair.location=(2.388,4.790,0)
    chair.rotation_euler[2]=math.radians(25)
    chair.empty_display_type='PLAIN_AXES';chair.empty_display_size=0.1
    count=32;rings=226;vertices=[];triangles=[]
    for j in range(rings):
        z=j*0.450/(rings-1)
        radius=0.006
        for i in range(count):
            angle=2*math.pi*i/count
            vertices.append((radius*math.cos(angle),radius*math.sin(angle),z))
    for j in range(rings-1):
        for i in range(count):
            a=j*count+i;b=j*count+(i+1)%count;c=b+count;d=a+count
            triangles.extend([(a,b,c),(a,c,d)])
    bottom=len(vertices);vertices.append((0,0,0))
    top=len(vertices);vertices.append((0,0,0.45))
    for i in range(count):
        triangles.append((bottom,(i+1)%count,i))
        a=(rings-1)*count+i;b=(rings-1)*count+(i+1)%count
        triangles.append((top,a,b))
    mesh=bpy.data.meshes.new('ZC_LegMesh');mesh.from_pydata(vertices,[],triangles);mesh.update()
    leg=bpy.data.objects.new('ZC_ChairLeg',mesh);scene.collection.objects.link(leg)
    leg.parent=chair
    for p in mesh.polygons: p.use_smooth=True
    material=bpy.data.materials.new('ZC_OakPlaceholder');material.diffuse_color=(0.35,0.16,0.055,1)
    leg.data.materials.append(material)
    scene.camera=None
    bpy.context.view_layer.update()
    bpy.context.view_layer.objects.active=leg;leg.select_set(True)
    output.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output),check_existing=False)
    print('Created:',output,'Chair world origin (mm):',(2388,4790,0))
    return leg


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--output',required=True)
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    create_demo(p.parse_args(argv).output)
