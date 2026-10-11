"""Deterministic test scene/model. This is NOT AI output or photorealism."""
import copy
import json
from pathlib import Path
from .core import apply_recipe, digest, local_point, object_point
from .runner import write_json


def demo_config():
    return dict(max_attempts=2,model={'send_preview':False},tasks=[dict(
        id=f'leg-{i+1:03d}',object='ChairLeg',center_mm=[0,0,z],rotation_deg=[0,0,0],
        scale=1,material='oak',max_move_mm=0.3,
        instruction='Subtle refinement of the existing oak leg surface. Preserve boundary.')
        for i,z in enumerate([0,21.54])])


class DemoBackend:
    def __init__(self,path):
        self.path=Path(path)
        if self.path.exists():
            state=json.loads(self.path.read_text())
            self.vertices=state['vertices'];self.triangles=state['triangles'];self.receipts=state['receipts']
        else:
            # Dense surface strip on the side of a leg, mm. Adjacent zones share mesh.
            self.vertices=[[x,0,z] for z in range(-15,38) for x in range(-15,16)]
            self.triangles=[]
            for z in range(52):
                for x in range(30):
                    i=z*31+x
                    self.triangles.extend([[i,i+32,i+1],[i,i+31,i+32]])
            self.receipts={};self.save()
    def save(self):
        write_json(self.path,dict(vertices=self.vertices,triangles=self.triangles,receipts=self.receipts))
    def fingerprint(self): return digest([self.vertices,self.triangles])
    async def snapshot(self,task):
        return dict(vertices=[local_point(p,task) for p in self.vertices],
                    triangles=copy.deepcopy(self.triangles),fingerprint=self.fingerprint())
    async def commit(self,task,recipe,expected,token):
        if token in self.receipts: raise ValueError('already committed; reconcile instead')
        if expected!=self.fingerprint(): raise ValueError('stale mesh snapshot')
        snap=await self.snapshot(task)
        after,checks=apply_recipe(snap,task,recipe)
        write_json(self.path.with_name(token+'-before.json'),dict(vertices=self.vertices,triangles=self.triangles))
        self.vertices=[object_point(p,task) if p!=q else old for p,q,old in
                       zip(after['vertices'],snap['vertices'],self.vertices)]
        receipt=dict(token=token,before=expected,after=self.fingerprint(),checks=checks,mode='simulation')
        self.receipts[token]=receipt;self.save()
        return receipt
    async def receipt(self,task,token):
        r=copy.deepcopy(self.receipts.get(token))
        if r: r['current_matches']=r['after']==self.fingerprint()
        return r


class DemoModel:
    async def propose(self,task,summary,images,error):
        return dict(task_id=task['id'],brushes=[dict(center_mm=[0,0,0],
                    radius_mm=8*task['scale'],displacement_mm=[0,0.15*task['scale'],0])],
                    note='Deterministic demonstration; not AI-generated')
