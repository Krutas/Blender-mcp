"""Sequential propose -> validate -> compare-and-commit loop."""
import json
import os
from pathlib import Path
from .core import apply_recipe, summarize


def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('w',encoding='utf-8') as f:
        json.dump(value,f,indent=2,ensure_ascii=False,allow_nan=False)
        f.flush();os.fsync(f.fileno())
    temp.replace(path)


def report(store,root):
    result=dict(job_id=store.job_id,counts=store.counts(),tasks=store.rows(),
                note='needs_review means geometry committed, NOT photorealism approved')
    write_json(Path(root)/'report.json',result)
    return result['counts']


async def run_queue(config,store,backend,model,root,limit=None):
    root=Path(root)
    if any(r['status'] in ('running','uncertain') for r in store.rows()):
        raise RuntimeError('interrupted task: use reconcile before continuing')
    await verify_scene(store,backend)
    completed=0
    for row in store.rows():
        if row['status'] in ('needs_review','reviewed'): continue
        if row['status'] in ('failed','rejected'): break
        if limit is not None and completed>=limit: break
        task=json.loads(row['task']);tid=task['id'];token=store.token(tid)
        folder=root/'tasks'/token;folder.mkdir(parents=True,exist_ok=True)
        store.state(tid,'running')
        print('Zone:',tid,flush=True)
        try:
            await verify_scene(store,backend)
            snapshot=await backend.snapshot(task)
            expected=latest_object_receipts(store).get(task['object'])
            if expected and snapshot['fingerprint']!=expected['after']:
                raise ValueError('scene changed between resume verification and snapshot')
            summary=summarize(snapshot,task)
            write_json(folder/'before.json',snapshot)
            if summary['editable_vertices']==0:
                raise ValueError('no editable vertices: densify mesh before running')
            images=[]
            from .preview import save_preview
            preview=save_preview(snapshot,task,folder/'before.png')
            if preview and config.get('model',{}).get('send_preview',True): images.append(preview)
            if task.get('reference_image'): images.append(Path(task['reference_image']))
            error=None;recipe=None
            for attempt in range(config.get('max_attempts',3)):
                store.state(tid,'running',detail=error,attempt=True)
                try:
                    candidate=await model.propose(task,summary,images,error)
                    after,checks=apply_recipe(snapshot,task,candidate)
                    recipe=candidate
                    break
                except (ValueError,TimeoutError,ConnectionError) as exc:
                    error=str(exc)[:1000]
                    write_json(folder/f'attempt-{attempt+1}-error.json',{'error':error})
            if recipe is None:
                raise ValueError('proposal attempts exhausted: '+str(error))
            # Write-ahead record exists before a live scene can change.
            write_json(folder/'proposal.json',dict(recipe=recipe,expected=snapshot['fingerprint'],
                                                   token=token,checks=checks))
        except Exception as exc:
            store.state(tid,'failed',detail=str(exc)[:2000]);break
        try:
            receipt=await backend.commit(task,recipe,snapshot['fingerprint'],token)
        except Exception as exc:
            # A timeout can mean Blender saved successfully but response was lost.
            # NEVER repeat automatically, even if a remote exception sounds harmless.
            store.state(tid,'uncertain',detail=str(exc)[:2000]);break
        store.state(tid,'needs_review',receipt=receipt)
        write_json(folder/'receipt.json',receipt)
        try:
            actual=await backend.snapshot(task)
            if actual['fingerprint']!=receipt['after']:
                raise ValueError('scene changed after commit; inspect after.blend checkpoint')
            write_json(folder/'after.json',actual)
            save_preview(actual,task,folder/'after.png')
        except Exception as exc:
            # Geometry is already committed: retain status, never repeat deformation.
            write_json(folder/'after-capture-error.json',{'error':str(exc)[:2000]})
            store.state(tid,'needs_review',detail='After capture failed: '+str(exc)[:1000],receipt=receipt)
            report(store,root)
            break
        completed+=1
        report(store,root)
    return report(store,root)


def latest_object_receipts(store):
    latest={}
    for row in store.rows():
        if row['status'] in ('needs_review','reviewed') and row['receipt']:
            latest[json.loads(row['task'])['object']]=json.loads(row['receipt'])
    return latest


async def verify_scene(store,backend):
    latest={}
    for row in store.rows():
        if row['status'] in ('needs_review','reviewed'):
            task=json.loads(row['task'])
            latest[task['object']]=(row,task)
    for row,task in latest.values():
        receipt=await backend.receipt(task,store.token(row['id']))
        if not receipt or receipt.get('current_matches') is not True:
            raise RuntimeError('scene differs from last committed checkpoint for '+task['object']+
                               '; open the correct after.blend or start a new state directory')


async def reconcile(store,backend,task_id):
    row=store.get(task_id)
    if row['status'] not in ('running','uncertain'):
        raise ValueError('reconcile applies only to running/uncertain tasks')
    task=json.loads(row['task'])
    receipt=await backend.receipt(task,store.token(task_id))
    if not receipt:
        raise RuntimeError('no matching commit receipt; inspect checkpoint and use retry only after restoring/verifying scene')
    if receipt.get('current_matches') is False:
        raise RuntimeError('receipt exists but mesh changed afterward; inspect saved after checkpoint')
    store.state(task_id,'needs_review',receipt=receipt)
    return receipt
