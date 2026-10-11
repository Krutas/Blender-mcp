"""Trusted Blender-side adapter, appended after core.py by mcp_client.

This file is not a Blender add-on. It runs through execute_blender_code.
It intentionally does not execute LLM code or alter topology/materials.
"""
import bpy
from mathutils import Vector


def zc_object(task):
    obj=bpy.data.objects.get(task['object'])
    if obj is None or obj.type!='MESH': raise ValueError('target mesh object not found')
    if obj.mode!='OBJECT': raise ValueError('target must be in Object Mode')
    if obj.data.users!=1: raise ValueError('make mesh single-user before refining')
    if obj.data.shape_keys: raise ValueError('shape keys are not supported in v0.1')
    if len(obj.modifiers): raise ValueError('apply modifiers to a working copy before refining')
    if len(obj.data.vertices)>200000: raise ValueError('v0.1 limit: 200000 vertices per object')
    if len(obj.data.polygons)>400000: raise ValueError('v0.1 limit: 400000 triangles per object')
    if any(len(p.vertices)!=3 for p in obj.data.polygons):
        raise ValueError('triangulate the working mesh first; topology stays fixed during jobs')
    matrix=obj.matrix_world.to_3x3()
    if any(abs(matrix.col[i].length-1)>1e-5 for i in range(3)) or abs(matrix.determinant()-1)>1e-5:
        raise ValueError('apply object/parent scale and remove shear; translation/rotation are supported')
    if any(abs(matrix.col[i].dot(matrix.col[j]))>1e-5 for i,j in [(0,1),(0,2),(1,2)]):
        raise ValueError('sheared transforms not supported')
    factor=float(bpy.context.scene.unit_settings.scale_length)*1000
    if not math.isfinite(factor) or factor<=0: raise ValueError('invalid scene unit scale')
    return obj,factor


def zc_fingerprint(obj,factor):
    # Actual mesh coordinates, connectivity, unit scale, object/world transform, UV and material mapping.
    return digest(dict(vertices=[list(v.co) for v in obj.data.vertices],
        faces=[list(p.vertices) for p in obj.data.polygons],factor=factor,
        transform=[list(row) for row in obj.matrix_world],
        materials=[m.name if m else None for m in obj.data.materials],
        material_indices=[p.material_index for p in obj.data.polygons],
        uv=[{'name':uv.name,'data':[list(v.uv) for v in uv.data]} for uv in obj.data.uv_layers]))


def zc_snapshot(task):
    obj,factor=zc_object(task)
    snapshot=dict(vertices=[local_point([x*factor for x in v.co],task) for v in obj.data.vertices],
        triangles=[list(p.vertices) for p in obj.data.polygons],fingerprint=zc_fingerprint(obj,factor))
    validate_mesh(snapshot)
    return snapshot


def zc_save(path):
    result=bpy.ops.wm.save_as_mainfile(filepath=path,copy=True,check_existing=False)
    if 'FINISHED' not in result: raise ValueError('checkpoint save did not finish')


def zc_commit(request,task):
    token=request['token']
    if not isinstance(token,str) or len(token)!=24 or any(c not in '0123456789abcdef' for c in token):
        raise ValueError('invalid commit token')
    obj,factor=zc_object(task)
    key='_zonecoord_'+token
    if key in obj: raise ValueError('commit receipt already exists; reconcile instead')
    snap=zc_snapshot(task)
    if snap['fingerprint']!=request['expected']: raise ValueError('stale snapshot; mesh or transform changed')
    after,checks=apply_recipe(snap,task,request['recipe'])
    if not bpy.data.filepath: raise ValueError('save working .blend file before live commit')
    base=bpy.path.abspath('//')+'zc-'+token
    before_path=base+'-before.blend';after_path=base+'-after.blend'
    zc_save(before_path)
    saved=[v.co.copy() for v in obj.data.vertices]
    changed={i for i,(a,b) in enumerate(zip(snap['vertices'],after['vertices'])) if a!=b}
    try:
        for i in changed:
            p=object_point(after['vertices'][i],task)
            obj.data.vertices[i].co=Vector([x/factor for x in p])
        obj.data.update()
        # Verify the actual float32 Blender result, not just the proposed Python numbers.
        for i,v in enumerate(obj.data.vertices):
            if i not in changed and v.co!=saved[i]: raise ValueError('locked vertex unexpectedly changed')
        actual=zc_snapshot(task)
        checks=validate_change(snap,actual,task)
        receipt=dict(token=token,task_id=task['id'],before=snap['fingerprint'],
            after=actual['fingerprint'],before_blend=before_path,after_blend=after_path,
            checks=checks,visual_quality='needs_review',blender_version=bpy.app.version_string)
        obj[key]=json.dumps(receipt)
        zc_save(after_path)
        return receipt
    except BaseException:
        for i,p in enumerate(saved): obj.data.vertices[i].co=p
        obj.data.update()
        if key in obj: del obj[key]
        raise


def zc_dispatch(request):
    try:
        action=request['action']
        if action=='probe':
            return dict(blender_version=bpy.app.version_string,file=bpy.data.filepath,
                        mm_per_blender_unit=bpy.context.scene.unit_settings.scale_length*1000,
                        mode='fixed-topology local deformation')
        task=validate_task(request['task'])
        if action=='snapshot': return zc_snapshot(task)
        if action=='commit': return zc_commit(request,task)
        if action=='receipt':
            obj,factor=zc_object(task)
            raw=obj.get('_zonecoord_'+request['token'])
            receipt=json.loads(raw) if raw else None
            if receipt: receipt['current_matches']=receipt['after']==zc_fingerprint(obj,factor)
            return {'receipt':receipt}
        raise ValueError('unknown coordinator action')
    except Exception as exc:
        return {'error':type(exc).__name__+': '+str(exc)}
