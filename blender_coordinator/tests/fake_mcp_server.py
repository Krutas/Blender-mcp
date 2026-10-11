"""Transport fixture. It does not emulate or claim to run Blender."""
import json
from mcp.server.fastmcp import FastMCP
server=FastMCP('Coordinator protocol fixture')
@server.tool()
def execute_blender_code(code:str,user_prompt:str='')->str:
    return 'Code executed successfully: ZC_RESULT:'+json.dumps({'fixture':True,'code_received':bool(code)})
if __name__=='__main__': server.run(transport='stdio')
