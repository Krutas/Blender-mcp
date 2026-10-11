import importlib.util
import sys
import unittest
from pathlib import Path
from zonecoord.mcp_client import BlenderMCP, parse_result


class ParseTests(unittest.TestCase):
    def test_marker_survives_wrapped_output(self):
        self.assertEqual(parse_result('Code executed successfully: ZC_RESULT:{"ok":true}\n')['ok'],True)
        with self.assertRaises(ValueError): parse_result('Error: denied')
        with self.assertRaises(ValueError): parse_result('ZC_RESULT:{"error":"stale"}')


@unittest.skipUnless(importlib.util.find_spec('mcp'),'optional mcp SDK not installed')
class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_session_discovers_and_calls_tool(self):
        cfg=dict(transport='stdio',command=sys.executable,
                 args=[str(Path(__file__).with_name('fake_mcp_server.py'))],timeout_seconds=20)
        async with BlenderMCP(cfg) as client:
            result=await client.request({'action':'probe'})
            self.assertTrue(result['fixture']);self.assertTrue(result['code_received'])


if __name__=='__main__': unittest.main()
