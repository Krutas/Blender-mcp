"""python -m zonecoord --help"""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from .core import validate_task,validate_config
from .demo import DemoBackend,DemoModel,demo_config
from .model import LocalModel
from .mcp_client import BlenderMCP
from .runner import run_queue,reconcile,report,write_json
from .store import Store,JobLock


def load_config(path):
    path=Path(path).resolve()
    config=json.loads(path.read_text(encoding='utf-8'))
    validate_config(config)
    for t in config['tasks']:
        validate_task(t)
        if t.get('reference_image'):
            t['reference_image']=str((path.parent/t['reference_image']).resolve())
            if not Path(t['reference_image']).is_file(): raise ValueError('reference_image missing')
    return config


async def main_async(args):
    if args.command=='doctor':
        config=load_config(args.config)
        model=LocalModel(config['model'])
        models=await model.probe()
        ids=[item['id'] for item in models.get('data',[])]
        print('Model API ids:',json.dumps(ids))
        if config['model']['name'] not in ids:
            raise ValueError('set model.name to an exact id from the list above')
        async with BlenderMCP(config['mcp']) as backend:
            print('Blender:',json.dumps(await backend.probe(),ensure_ascii=False))
            for raw in config['tasks']:
                from .core import summarize
                t=validate_task(raw)
                print(t['id'],json.dumps(summarize(await backend.snapshot(t),t)))
        return 0
    root=Path(args.state).resolve();root.mkdir(parents=True,exist_ok=True)
    if args.command=='demo': config=demo_config()
    elif args.command in ('run','reconcile') and args.config: config=load_config(args.config)
    else:
        path=root/'config.json'
        if not path.exists(): raise ValueError('state directory has no config.json')
        config=load_config(path)
    with JobLock(root/'coordinator.lock'):
        store=Store(root/'queue.sqlite',config)
        try:
            write_json(root/'config.json',config)
            if args.command=='status':
                for row in store.rows():
                    print(f"{row['id']:24} {row['status']:14} attempts={row['attempts']} {row['error'] or ''}")
                print(json.dumps(report(store,root)));return 0
            if args.command=='review':
                row=store.get(args.task)
                if row['status']!='needs_review': raise ValueError('only needs_review can be reviewed')
                store.state(args.task,'reviewed' if args.approve else 'rejected',detail=args.note)
                if args.reject:
                    print('Rejected status does NOT undo geometry. Restore checkpoint and use a new state if reworking.')
                print(json.dumps(report(store,root)));return 0
            if args.command=='retry':
                row=store.get(args.task)
                if row['status'] not in ('failed','uncertain','running'):
                    raise ValueError('only failed/interrupted tasks may be retried')
                if not args.verified_scene:
                    raise ValueError('inspect/restore the saved scene first, then use --verified-scene')
                store.state(args.task,'pending',detail='Operator confirmed scene state for retry')
                print(json.dumps(report(store,root)));return 0
            if args.command=='demo':
                backend=DemoBackend(root/'demo-scene.json')
                counts=await run_queue(config,store,backend,DemoModel(),root,args.limit)
            else:
                async with BlenderMCP(config['mcp']) as backend:
                    if args.command=='reconcile':
                        await reconcile(store,backend,args.task)
                        counts=report(store,root)
                    else:
                        counts=await run_queue(config,store,backend,LocalModel(config['model']),root,args.limit)
            print(json.dumps(counts,ensure_ascii=False))
            return 2 if any(counts.get(k,0) for k in ('failed','uncertain','rejected')) else 0
        finally: store.close()


def parser():
    p=argparse.ArgumentParser(description='Local fragment coordinator for Blender + a local 4B model')
    sub=p.add_subparsers(dest='command',required=True)
    for name in ('demo','run','doctor','status','review','retry','reconcile'):
        c=sub.add_parser(name)
        if name!='doctor': c.add_argument('--state',default='runs/live' if name!='demo' else 'runs/demo')
        if name in ('run','doctor','reconcile'):
            c.add_argument('--config',default='examples/local.json' if name!='reconcile' else None)
        if name in ('run','demo'): c.add_argument('--limit',type=int)
        if name in ('review','retry','reconcile'): c.add_argument('task')
        if name=='review':
            group=c.add_mutually_exclusive_group(required=True)
            group.add_argument('--approve',action='store_true');group.add_argument('--reject',action='store_true')
            c.add_argument('--note',required=True,help='What you inspected; visual review is a human decision')
        if name=='retry': c.add_argument('--verified-scene',action='store_true')
    return p


def main():
    args=parser().parse_args()
    if getattr(args,'limit',None) is not None and args.limit<1:
        raise SystemExit('--limit must be positive')
    try: raise SystemExit(asyncio.run(main_async(args)))
    except KeyboardInterrupt:
        print('Interrupted. Inspect status and reconcile before restarting.',file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(type(exc).__name__+': '+str(exc),file=sys.stderr);raise SystemExit(2)


if __name__=='__main__': main()
