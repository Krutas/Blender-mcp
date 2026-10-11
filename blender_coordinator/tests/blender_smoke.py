"""Real Blender integration check; run separately, not regular unittest.

blender --background --factory-startup --python tests/blender_smoke.py
Requires Blender's own bpy. This file tests actual scene commits and checkpoints.
"""
import json
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'examples'))
import bpy
from create_blender_demo import create_demo
from zonecoord.core import validate_task,local_point
from zonecoord.mcp_client import build_script


with tempfile.TemporaryDirectory() as folder:
    leg=create_demo(Path(folder)/'test.blend')
    namespace={}
    exec(compile(build_script({'action':'probe'}),'coordinator_bridge','exec'),namespace)
    dispatch=namespace['zc_dispatch']
    task=validate_task(json.loads((ROOT/'examples/local.json').read_text())['tasks'][0])
    before=dispatch({'action':'snapshot','task':task})
    assert 'error' not in before,before
    originals=[v.co.copy() for v in leg.data.vertices]
    recipe=dict(task_id=task['id'],brushes=[dict(center_mm=[0,0,0],radius_mm=8,
                                               displacement_mm=[0.1,0,0])],note='Smoke test')
    payload=dict(action='commit',task=task,recipe=recipe,expected=before['fingerprint'],token='a'*24)
    receipt=dispatch(payload)
    assert 'error' not in receipt,receipt
    assert Path(receipt['before_blend']).is_file()
    assert Path(receipt['after_blend']).is_file()
    assert receipt['checks']['changed_vertices']>0
    assert any(v.co!=p for v,p in zip(leg.data.vertices,originals))
    for v,p in zip(leg.data.vertices,originals):
        local=local_point([x*1000 for x in p],task)
        if max(map(abs,local))>=10.77: assert v.co==p,'buffer changed'
    repeat=dispatch(payload)
    assert 'error' in repeat and 'already exists' in repeat['error'],repeat
    check=dispatch(dict(action='receipt',task=task,token='a'*24))
    assert check['receipt']['current_matches']
    # Runtime error after coordinate mutation must roll back both coordinates and receipt.
    originals=[v.co.copy() for v in leg.data.vertices]
    snapshot=dispatch({'action':'snapshot','task':task})
    original_save=namespace['zc_save']
    saves=[]
    def fail_second_save(path):
        saves.append(path)
        if len(saves)==2: raise OSError('intentional simulated disk failure')
        original_save(path)
    namespace['zc_save']=fail_second_save
    failed=dispatch(dict(action='commit',task=task,recipe=recipe,expected=snapshot['fingerprint'],token='b'*24))
    assert 'error' in failed,failed
    assert all(v.co==p for v,p in zip(leg.data.vertices,originals))
    assert '_zonecoord_'+'b'*24 not in leg
    print('BLENDER_SMOKE_PASS: real geometry, transforms, buffer, checkpoints, duplicate protection, rollback')
