import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from zonecoord.model import LocalModel, parse_recipe
from test_core import task


class ModelTests(unittest.IsolatedAsyncioTestCase):
    def test_fenced_json_and_reject_python_or_truncation(self):
        self.assertEqual(parse_recipe('```json\n{"task_id":"a","brushes":[]}\n```')['task_id'],'a')
        with self.assertRaises(ValueError): parse_recipe('import bpy')
        with self.assertRaises(ValueError): parse_recipe('{"a":NaN}')

    async def test_http_request_contains_only_local_task(self):
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append(data)
                body=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({
                    'task_id':'leg-001','brushes':[],'note':'test'})}}],
                    'usage':{'prompt_tokens':400,'completion_tokens':20}}).encode()
                self.send_response(200);self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            model=LocalModel(dict(base_url=f'http://127.0.0.1:{server.server_port}/v1',
                                  name='local-4b',context_tokens=8192,max_output_tokens=2048))
            t=task(center_mm=[2388,4790,0],object='SecretWholeRoomName')
            result=await model.propose(t,{'origin':[0,0,0]},[],None)
            self.assertEqual(result['task_id'],'leg-001')
            text=json.dumps(seen[0]['messages'])
            self.assertNotIn('2388',text);self.assertNotIn('4790',text)
            self.assertNotIn('SecretWholeRoomName',text)
            self.assertEqual(seen[0]['max_tokens'],2048)
        finally: server.shutdown();server.server_close();thread.join()


if __name__=='__main__': unittest.main()
