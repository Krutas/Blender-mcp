import asyncio
import copy
import json
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from zonecoord.store import Store
from zonecoord.runner import run_queue, reconcile
from zonecoord.demo import DemoBackend, DemoModel, demo_config


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.cfg=demo_config()
        self.store=Store(self.root/'queue.sqlite',self.cfg)
        self.backend=DemoBackend(self.root/'scene.json')
    async def asyncTearDown(self):
        self.store.close();self.temp.cleanup()

    async def test_demo_commits_fresh_zones_and_resume_skips_them(self):
        result=await run_queue(self.cfg,self.store,self.backend,DemoModel(),self.root)
        self.assertEqual(result['needs_review'],2)
        self.assertEqual(len(self.backend.receipts),2)
        before=copy.deepcopy(self.backend.vertices)
        await run_queue(self.cfg,self.store,self.backend,DemoModel(),self.root)
        self.assertEqual(before,self.backend.vertices)
        self.assertTrue((self.root/'report.json').exists())

    async def test_invalid_model_reply_retries_without_touching_mesh(self):
        class BadModel:
            async def propose(self,*a,**k): return {'task_id':'wrong','brushes':[]}
        before=copy.deepcopy(self.backend.vertices)
        await run_queue(self.cfg,self.store,self.backend,BadModel(),self.root)
        self.assertEqual(self.store.counts()['failed'],1)
        self.assertEqual(before,self.backend.vertices)

    async def test_timeout_after_commit_requires_reconcile_no_double_apply(self):
        real=self.backend.commit
        async def ambiguous(*a,**k):
            await real(*a,**k)
            raise TimeoutError('response lost')
        self.backend.commit=ambiguous
        await run_queue(self.cfg,self.store,self.backend,DemoModel(),self.root)
        self.assertEqual(self.store.counts()['uncertain'],1)
        first=self.store.rows()[0]
        self.backend.commit=real
        await reconcile(self.store,self.backend,first['id'])
        self.assertEqual(self.store.rows()[0]['status'],'needs_review')
        await run_queue(self.cfg,self.store,self.backend,DemoModel(),self.root)
        self.assertEqual(len(self.backend.receipts),2)

    async def test_config_drift_rejected(self):
        changed=copy.deepcopy(self.cfg);changed['tasks'][0]['scale']=2
        with self.assertRaisesRegex(ValueError,'configuration'):
            other=Store(self.root/'queue.sqlite',changed)

    async def test_interrupted_running_not_blindly_retried(self):
        row=self.store.rows()[0]
        self.store.state(row['id'],'running')
        with self.assertRaisesRegex(RuntimeError,'reconcile'):
            await run_queue(self.cfg,self.store,self.backend,DemoModel(),self.root)

    async def test_resume_refuses_old_or_manually_changed_scene(self):
        await run_queue(self.cfg,self.store,self.backend,DemoModel(),self.root,limit=1)
        self.backend.vertices[0][0]+=1
        with self.assertRaisesRegex(RuntimeError,'scene|checkpoint'):
            await run_queue(self.cfg,self.store,self.backend,DemoModel(),self.root)

    async def test_change_between_resume_check_and_snapshot_is_rejected(self):
        await run_queue(self.cfg,self.store,self.backend,DemoModel(),self.root,limit=1)
        original=self.backend.snapshot
        async def edit_before_snapshot(task):
            self.backend.vertices[0][0]+=1
            return await original(task)
        self.backend.snapshot=edit_before_snapshot
        await run_queue(self.cfg,self.store,self.backend,DemoModel(),self.root)
        self.assertEqual(self.store.rows()[1]['status'],'failed')
        self.assertEqual(len(self.backend.receipts),1)

    async def test_after_artifact_has_actual_committed_hash(self):
        await run_queue(self.cfg,self.store,self.backend,DemoModel(),self.root,limit=1)
        folder=self.root/'tasks'/self.store.token('leg-001')
        after=json.loads((folder/'after.json').read_text())
        receipt=json.loads((folder/'receipt.json').read_text())
        self.assertEqual(after['fingerprint'],receipt['after'])

    async def test_after_capture_failure_does_not_repeat_commit(self):
        original=self.backend.snapshot
        calls=[]
        async def fail_post_commit(task):
            calls.append(1)
            if len(calls)==3: raise ConnectionError('post-commit capture unavailable')
            return await original(task)
        self.backend.snapshot=fail_post_commit
        await run_queue(self.cfg,self.store,self.backend,DemoModel(),self.root,limit=1)
        self.assertEqual(len(self.backend.receipts),1)
        self.assertEqual(self.store.rows()[0]['status'],'needs_review')
        self.assertEqual(len(calls),3)
        self.assertTrue((self.root/'tasks'/self.store.token('leg-001')/'after-capture-error.json').exists())

    async def test_invalid_retry_config_rejected_before_queue_creation(self):
        for value in [1.5,True,0,6]:
            cfg=copy.deepcopy(self.cfg);cfg['max_attempts']=value
            path=self.root/('invalid-'+str(value)+'.sqlite')
            with self.assertRaises(ValueError): Store(path,cfg)
            self.assertFalse(path.exists())

    async def test_cli_persists_across_process_restart(self):
        path=str(self.root/'cli-restart')
        command=[sys.executable,'-m','zonecoord','demo','--state',path]
        first=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(first.returncode,0,first.stderr)
        second=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(second.returncode,0,second.stderr)
        self.assertNotIn('Zone:',second.stdout)
        self.assertIn('"needs_review": 2',second.stdout)


if __name__=='__main__': unittest.main()
