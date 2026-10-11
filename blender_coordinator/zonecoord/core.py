"""Dependency-free geometry kernel; the same source executes inside Blender.

All geometry here is in physical millimetres. Task scale changes region size,
never object geometry. Model output is DATA, never executable code.
"""
import copy
import hashlib
import json
import math


def number(x, name):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError(name + ' must be a finite number')
    return float(x)


def vector(v, name):
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise ValueError(name + ' must contain 3 numbers')
    return [number(x, name) for x in v]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def validate_task(raw):
    if not isinstance(raw, dict):
        raise ValueError('task must be an object')
    t = copy.deepcopy(raw)
    for k in ('id', 'object', 'instruction', 'material'):
        if not isinstance(t.get(k), str) or not t[k].strip() or len(t[k]) > 3000:
            raise ValueError(k + ' must be a nonempty bounded string')
    t['center_mm'] = vector(t.get('center_mm'), 'center_mm')
    t['rotation_deg'] = vector(t.get('rotation_deg', [0, 0, 0]), 'rotation_deg')
    t['scale'] = number(t.get('scale', 1), 'scale')
    if not 0.001 <= t['scale'] <= 1000:
        raise ValueError('scale outside [0.001,1000]')
    t['max_move_mm'] = number(t.get('max_move_mm', 0.3), 'max_move_mm')
    if not 0 < t['max_move_mm'] <= 2:
        raise ValueError('max_move_mm must be in (0,2] before task scaling')
    t['core_half_mm'] = 10.77 * t['scale']
    t['outer_half_mm'] = 12.77 * t['scale']
    t['guard_mm'] = 1.0 * t['scale']
    return t


def validate_config(config):
    if not isinstance(config,dict) or not isinstance(config.get('tasks'),list):
        raise ValueError('configuration needs tasks array')
    attempts=config.get('max_attempts',3)
    if type(attempts) is not int or not 1<=attempts<=5:
        raise ValueError('max_attempts must be an integer 1..5')
    tasks=[validate_task(t) for t in config['tasks']]
    if not tasks or len({t['id'] for t in tasks})!=len(tasks):
        raise ValueError('tasks must have unique ids and not be empty')
    return tasks


def rotation(degrees):
    x, y, z = [math.radians(v) for v in degrees]
    a,b,c,d,e,f = math.cos(x),math.sin(x),math.cos(y),math.sin(y),math.cos(z),math.sin(z)
    # Rz @ Ry @ Rx; fragment axes expressed in object axes.
    return [[e*c,e*d*b-f*a,e*d*a+f*b], [f*c,f*d*b+e*a,f*d*a-e*b], [-d,c*b,c*a]]


def mul(m, v):
    return [sum(a*b for a,b in zip(row,v)) for row in m]


def local_point(p, task):
    r = rotation(task['rotation_deg'])
    return mul(list(zip(*r)), [a-b for a,b in zip(p,task['center_mm'])])


def object_point(p, task):
    return [a+b for a,b in zip(mul(rotation(task['rotation_deg']),p),task['center_mm'])]


def inside(p, half):
    return max(abs(x) for x in p) <= half


def length(v):
    return math.sqrt(sum(x*x for x in v))


def sub(a, b):
    return [x-y for x,y in zip(a,b)]


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]


def normal(vertices, tri):
    a,b,c = [vertices[i] for i in tri]
    return cross(sub(b,a),sub(c,a))


def editable_vertices(vertices, triangles, task):
    h = task['core_half_mm']
    # Freeze all vertices on triangles which extend out of the working cube.
    # Moving an inside vertex of a straddling triangle would change the buffer surface.
    frozen = set()
    for tri in triangles:
        if any(not inside(vertices[i], h) for i in tri):
            frozen.update(tri)
    return {i for i,p in enumerate(vertices)
            if inside(p,h-task['guard_mm']) and i not in frozen}


def validate_mesh(snapshot):
    vertices = snapshot.get('vertices')
    triangles = snapshot.get('triangles')
    if not isinstance(vertices,list) or not 3 <= len(vertices) <= 200000:
        raise ValueError('mesh needs 3..200000 vertices')
    for p in vertices:
        vector(p,'vertex')
    if not isinstance(triangles,list) or not triangles or len(triangles)>400000:
        raise ValueError('mesh needs 1..400000 triangles')
    for t in triangles:
        if not isinstance(t,(list,tuple)) or len(t)!=3 or len(set(t))!=3:
            raise ValueError('only nondegenerate triangle topology is supported')
        if any(type(i)!=int or not 0<=i<len(vertices) for i in t):
            raise ValueError('invalid triangle index')


def summarize(snapshot, task):
    vertices=snapshot['vertices']
    visible=[p for p in vertices if inside(p,task['outer_half_mm'])]
    step=max(1, math.ceil(len(visible)/64))
    editable=editable_vertices(vertices,snapshot['triangles'],task)
    return dict(units='mm', origin=[0,0,0], axes='fragment-local XYZ',
                core_half_mm=task['core_half_mm'], outer_half_mm=task['outer_half_mm'],
                readonly_buffer_mm=2*task['scale'], seam_guard_mm=task['guard_mm'],
                max_displacement_mm=task['max_move_mm']*task['scale'],
                visible_vertices=len(visible), editable_vertices=len(editable),
                samples_mm=[[round(x,5) for x in p] for p in visible[::step][:64]])


def validate_recipe(recipe, task):
    if not isinstance(recipe,dict) or set(recipe)-{'task_id','brushes','note'}:
        raise ValueError('recipe accepts only task_id, brushes, note')
    if recipe.get('task_id')!=task['id']:
        raise ValueError('wrong task_id')
    brushes=recipe.get('brushes')
    if not isinstance(brushes,list) or not 1<=len(brushes)<=16:
        raise ValueError('provide 1..16 brushes')
    if not isinstance(recipe.get('note',''),str) or len(recipe.get('note',''))>2000:
        raise ValueError('invalid note')
    result=[]
    for b in brushes:
        if not isinstance(b,dict) or set(b)!={'center_mm','radius_mm','displacement_mm'}:
            raise ValueError('brush fields must be center_mm,radius_mm,displacement_mm')
        center=vector(b['center_mm'],'brush center')
        displacement=vector(b['displacement_mm'],'displacement')
        radius=number(b['radius_mm'],'radius')
        if not inside(center,task['core_half_mm']-task['guard_mm']):
            raise ValueError('brush center outside editable core')
        if not 0<radius<=2*task['core_half_mm']:
            raise ValueError('invalid brush radius')
        if length(displacement)>task['max_move_mm']*task['scale']+1e-9:
            raise ValueError('brush exceeds displacement limit')
        result.append((center,radius,displacement))
    return result


def apply_recipe(snapshot, task, recipe):
    validate_mesh(snapshot)
    brushes=validate_recipe(recipe,task)
    original=snapshot['vertices']; triangles=snapshot['triangles']
    editable=editable_vertices(original,triangles,task)
    if not editable:
        raise ValueError('no editable vertices; prepare a denser triangle mesh')
    vertices=copy.deepcopy(original)
    h=task['core_half_mm']; guard=task['guard_mm']
    max_move=task['max_move_mm']*task['scale']
    changed=set()
    for i in editable:
        p=original[i]; delta=[0.,0.,0.]
        # C1 continuous envelope; zero change in the inner guard and at its edge.
        w=1.
        for x in p:
            t=max(0.,min(1.,(h-guard-abs(x))/guard))
            w*=t*t*(3-2*t)
        for center,radius,displacement in brushes:
            d2=sum((a-b)**2 for a,b in zip(p,center))/(radius*radius)
            support=max(0.,1-d2)**3
            delta=[a+w*support*b for a,b in zip(delta,displacement)]
        if length(delta)>max_move+1e-9:
            raise ValueError('combined brushes exceed displacement limit')
        q=[a+b for a,b in zip(p,delta)]
        if not inside(q,h-guard):
            raise ValueError('deformation crosses locked seam guard')
        if length(delta)>1e-8*task['scale']:
            vertices[i]=q;changed.add(i)
    if not changed:
        raise ValueError('no vertices changed; brush misses editable surface')
    result=copy.deepcopy(snapshot); result['vertices']=vertices
    return result, validate_change(snapshot,result,task)


def validate_change(snapshot,after,task):
    """Validate proposed OR read-back coordinates against the original snapshot."""
    validate_mesh(snapshot);validate_mesh(after)
    original=snapshot['vertices'];vertices=after['vertices'];triangles=snapshot['triangles']
    if len(vertices)!=len(original) or triangles!=after['triangles']:
        raise ValueError('topology changed')
    editable=editable_vertices(original,triangles,task)
    changed={i for i,(a,b) in enumerate(zip(original,vertices)) if a!=b}
    if changed-editable: raise ValueError('locked buffer/seam vertices changed')
    if not changed: raise ValueError('no actual vertices changed')
    max_move=task['max_move_mm']*task['scale']
    for i in changed:
        if length(sub(vertices[i],original[i]))>max_move+1e-7*task['scale']:
            raise ValueError('actual displacement exceeds limit')
        if not inside(vertices[i],task['core_half_mm']-task['guard_mm']):
            raise ValueError('actual vertex crosses locked seam guard')
    min_area=1e-12*task['scale']**2
    for tri in triangles:
        if not changed.intersection(tri):
            continue
        n0=normal(original,tri);n1=normal(vertices,tri)
        if length(n0)<min_area or length(n1)<min_area:
            raise ValueError('degenerate triangle')
        if sum(a*b for a,b in zip(n0,n1))<=0:
            raise ValueError('triangle normal flips')
        for a,b in [(tri[0],tri[1]),(tri[1],tri[2]),(tri[2],tri[0])]:
            old=length(sub(original[a],original[b]));new=length(sub(vertices[a],vertices[b]))
            if old<1e-12 or not 0.5<=new/old<=1.5:
                raise ValueError('edge stretch limit exceeded')
    return dict(changed_vertices=len(changed), topology_unchanged=True,
                        buffer_unchanged=True, max_displacement_mm=max(
                            length(sub(vertices[i],original[i])) for i in changed),
                        self_intersections_checked=False, visual_quality='needs_review')
