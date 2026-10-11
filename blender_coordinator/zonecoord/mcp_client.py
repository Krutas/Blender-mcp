"""MCP v1 SDK adapter. Model never supplies code to this adapter."""
import json
import os
from contextlib import AsyncExitStack
from datetime import timedelta
from pathlib import Path


def parse_result(text):
    marker='ZC_RESULT:'
    position=text.rfind(marker)
    if position<0: raise ValueError('Blender returned no coordinator result: '+text[:400])
    try:
        result=json.JSONDecoder().raw_decode(text[position+len(marker):].lstrip())[0]
    except json.JSONDecodeError as exc: raise ValueError('invalid Blender result') from exc
    if not isinstance(result,dict): raise ValueError('Blender result is not an object')
    if 'error' in result: raise ValueError('Blender: '+str(result['error']))
    return result


def build_script(payload):
    root=Path(__file__).parent
    # Static reviewed sources + JSON data. No eval/exec or arbitrary LLM code.
    return (root/'core.py').read_text(encoding='utf-8')+'\n'+(
        root/'blender_runtime.py').read_text(encoding='utf-8')+'\nZC_REQUEST = json.loads('+repr(
        json.dumps(payload,allow_nan=False))+')\nprint("ZC_RESULT:" + json.dumps(zc_dispatch(ZC_REQUEST), allow_nan=False))\n'


class BlenderMCP:
    def __init__(self,config): self.config=config;self.stack=None
    async def __aenter__(self):
        try:
            from mcp import ClientSession,StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError as exc:
            raise RuntimeError('Install pinned dependencies: pip install -r requirements.txt') from exc
        self.stack=AsyncExitStack()
        await self.stack.__aenter__()
        try:
            timeout=timedelta(seconds=self.config.get('timeout_seconds',180))
            if self.config.get('transport','stdio')=='stdio':
                params=StdioServerParameters(command=self.config['command'],
                    args=self.config.get('args',[]),env={**os.environ,**self.config.get('env',{})})
                reader,writer=await self.stack.enter_async_context(stdio_client(params))
            elif self.config['transport']=='http':
                headers={}
                token=os.getenv(self.config.get('token_env','BLENDER_MCP_TOKEN'),'')
                if token: headers['Authorization']='Bearer '+token
                reader,writer,_=await self.stack.enter_async_context(streamablehttp_client(
                    self.config['url'],headers=headers,timeout=timeout,sse_read_timeout=timeout))
            else: raise ValueError('MCP transport must be stdio or http')
            self.session=await self.stack.enter_async_context(ClientSession(reader,writer,read_timeout_seconds=timeout))
            await self.session.initialize()
            listed=await self.session.list_tools()
            self.tool=self.config.get('execute_tool','execute_blender_code')
            description=next((t for t in listed.tools if t.name==self.tool),None)
            if description is None: raise ValueError('MCP server lacks '+self.tool)
            self.schema=description.inputSchema
            if 'code' not in self.schema.get('properties',{}):
                raise ValueError('execute tool must accept code argument')
            return self
        except BaseException:
            await self.stack.aclose();raise
    async def __aexit__(self,*args): return await self.stack.__aexit__(*args)

    async def request(self,payload):
        args={'code':build_script(payload)}
        if 'user_prompt' in self.schema.get('properties',{}):
            args['user_prompt']=self.config.get('user_prompt','Paruosk koordinatoriu')
        result=await self.session.call_tool(self.tool,args,
                    read_timeout_seconds=timedelta(seconds=self.config.get('timeout_seconds',180)))
        if result.isError: raise ValueError('MCP tool reported an error')
        text='\n'.join(block.text for block in result.content if getattr(block,'type',None)=='text')
        return parse_result(text)
    async def probe(self): return await self.request({'action':'probe'})
    async def snapshot(self,task): return await self.request({'action':'snapshot','task':task})
    async def commit(self,task,recipe,expected,token):
        return await self.request(dict(action='commit',task=task,recipe=recipe,expected=expected,token=token))
    async def receipt(self,task,token):
        result=await self.request(dict(action='receipt',task=task,token=token))
        return result.get('receipt')
