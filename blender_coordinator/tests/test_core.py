import copy
import math
import unittest
from zonecoord.core import validate_task, local_point, object_point, apply_recipe, summarize, validate_change


def task(**overrides):
    value = dict(id='leg-001', object='ChairLeg', center_mm=[0, 0, 0],
                 rotation_deg=[0, 0, 0], scale=1, instruction='Round surface',
                 material='oak', max_move_mm=0.5)
    value.update(overrides)
    return validate_task(value)


def grid():
    vertices = [[x, y, 0] for y in range(-15, 16) for x in range(-15, 16)]
    triangles = []
    for y in range(30):
        for x in range(30):
            i = y*31+x
            triangles.extend([[i,i+1,i+32],[i,i+32,i+31]])
    return dict(vertices=vertices, triangles=triangles, fingerprint='initial')


def recipe(t=None, **brush):
    return dict(task_id=(t or task())['id'], brushes=[dict(
        center_mm=[0,0,0], radius_mm=8, displacement_mm=[0,0,0.2], **brush)],
        note='Small curvature refinement')


class CoreTests(unittest.TestCase):
    def test_local_rotation_and_translation_roundtrip(self):
        t=task(center_mm=[120,45,200],rotation_deg=[17,32,90])
        p=[123,51,207]
        q=object_point(local_point(p,t),t)
        self.assertTrue(all(abs(a-b)<1e-9 for a,b in zip(p,q)))

    def test_buffer_and_boundaries_unchanged(self):
        t=task(); before=grid(); after,report=apply_recipe(before,t,recipe())
        self.assertGreater(report['changed_vertices'],0)
        for p,q in zip(before['vertices'],after['vertices']):
            if max(map(abs,p))>=10:
                self.assertEqual(p,q)
        self.assertEqual(before['triangles'],after['triangles'])
        self.assertEqual(before,grid())

    def test_cross_boundary_triangle_is_frozen(self):
        s=dict(vertices=[[0,0,0],[12,0,0],[0,2,0]],triangles=[[0,1,2]])
        with self.assertRaisesRegex(ValueError,'editable|changed'):
            apply_recipe(s,task(),recipe())

    def test_scale_changes_zone_not_object(self):
        t=task(scale=2)
        self.assertEqual(t['core_half_mm'],21.54)
        self.assertEqual(t['outer_half_mm'],25.54)
        self.assertEqual(local_point([2,3,4],t),[2,3,4])

    def test_rejects_nonfinite_and_unknown_operations(self):
        for patch in [dict(scale=float('nan')),dict(scale=0),dict(center_mm=[0,1])]:
            with self.assertRaises(ValueError): task(**patch)
        r=recipe();r['python']='delete everything'
        with self.assertRaises(ValueError): apply_recipe(grid(),task(),r)

    def test_rejects_excessive_or_outside_brush(self):
        for key,value in [('displacement_mm',[0,0,99]),('center_mm',[20,0,0]),('radius_mm',float('inf'))]:
            r=recipe();r['brushes'][0][key]=value
            with self.assertRaises(ValueError): apply_recipe(grid(),task(),r)

    def test_summary_local_only_and_bounded(self):
        s=grid();s['vertices'].append([2388,4790,100])
        result=summarize(s,task())
        self.assertLessEqual(len(result['samples_mm']),64)
        self.assertTrue(all(max(map(abs,p))<=12.77 for p in result['samples_mm']))

    def test_rejects_wrong_task(self):
        r=recipe();r['task_id']='wrong'
        with self.assertRaises(ValueError): apply_recipe(grid(),task(),r)

    def test_actual_float32_rounding_exceeding_limit_rejected(self):
        import struct
        t=task(center_mm=[1000000,0,0],max_move_mm=0.1)
        source={'vertices':[[0,0,0],[0,1,0],[0,0,1]],'triangles':[[0,1,2]]}
        r=recipe();r['brushes'][0]['displacement_mm']=[0.1,0,0]
        after,_=apply_recipe(source,t,r)
        actual=copy.deepcopy(after)
        for i,p in enumerate(after['vertices']):
            obj=object_point(p,t)
            obj=[struct.unpack('f',struct.pack('f',x/1000))[0]*1000 for x in obj]
            actual['vertices'][i]=local_point(obj,t)
        with self.assertRaisesRegex(ValueError,'displacement'):
            validate_change(source,actual,t)

    def test_actual_buffer_change_rejected(self):
        source=grid();after=copy.deepcopy(source);after['vertices'][0][0]+=0.001
        with self.assertRaisesRegex(ValueError,'locked|buffer'):
            validate_change(source,after,task())


if __name__=='__main__': unittest.main()
