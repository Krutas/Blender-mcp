"""OpenAI-compatible chat client for local models. No cloud dependency."""
import asyncio
import base64
import io
import json
import os
import urllib.error
import urllib.request

SYSTEM = '''You refine ONE local fragment of an existing Blender surface.
Coordinates and distances are physical millimetres in fragment-local XYZ.
Origin is the fragment centre. Do not infer a room, object placement, or overall
object proportions. Existing material mapping and all topology are fixed.
The core is editable; buffer and seam guard are read-only. Work only on the
visible local surface. Return a single JSON object, no Python, no markdown:
{"task_id":"provided id","brushes":[{"center_mm":[0,0,0],"radius_mm":4,
"displacement_mm":[0,0,0.1]}],"note":"brief explanation"}
Each brush applies a smooth compact radial displacement to existing vertices;
influence (1-distance_squared/radius_squared)^3, zero outside radius.
Coordinator also fades displacement to zero near the fixed boundary.
Use 1..16 brushes. Respect max_displacement_mm even when brushes overlap.
Do not invent extra operations or claim photorealism: visual acceptance is
separate. Preview is a technical XZ/XY/YZ projection, NOT a textured render.
If surface cannot support the instruction, return an empty brushes list and
explain in note; coordinator will stop rather than pretend completion.'''


def parse_recipe(text):
    if not isinstance(text,str) or len(text)>24000:
        raise ValueError('model reply must be bounded text')
    text=text.strip()
    if text.startswith('```'):
        lines=text.splitlines()
        if lines[-1].strip()!='```': raise ValueError('incomplete fenced JSON')
        text='\n'.join(lines[1:-1])
    def reject_constant(x): raise ValueError('nonfinite JSON number: '+x)
    try:
        value=json.loads(text,parse_constant=reject_constant)
    except (TypeError,json.JSONDecodeError) as exc:
        raise ValueError('model must return one valid JSON object') from exc
    if not isinstance(value,dict): raise ValueError('recipe must be an object')
    return value


def image_url(path):
    from PIL import Image
    with Image.open(path) as image:
        image=image.convert('RGB');image.thumbnail((960,640))
        stream=io.BytesIO();image.save(stream,format='JPEG',quality=85)
    return 'data:image/jpeg;base64,'+base64.b64encode(stream.getvalue()).decode()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


class LocalModel:
    def __init__(self,config):
        self.config=config
        self.base=config.get('base_url','http://127.0.0.1:1234/v1').rstrip('/')
        if not self.base.startswith(('http://','https://')): raise ValueError('invalid model API URL')
        if not config.get('name'): raise ValueError('model.name must match local /v1/models')
        self.context=int(config.get('context_tokens',8192))
        self.output=int(config.get('max_output_tokens',2048))
        if self.context<4096 or not 256<=self.output<=self.context//2:
            raise ValueError('invalid context/output token budget')

    def request(self,path,payload=None):
        headers={'Content-Type':'application/json'}
        key=os.getenv(self.config.get('api_key_env','LOCAL_MODEL_API_KEY'),'')
        if key: headers['Authorization']='Bearer '+key
        data=json.dumps(payload,allow_nan=False).encode() if payload is not None else None
        request=urllib.request.Request(self.base+path,data=data,headers=headers)
        try:
            with urllib.request.build_opener(NoRedirect()).open(
                request,timeout=self.config.get('timeout_seconds',180)) as response:
                raw=response.read(2_000_001)
                if len(raw)>2_000_000: raise ValueError('model response too large')
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise ConnectionError(f'model API HTTP {exc.code}; check model name/API settings') from exc
        except urllib.error.URLError as exc:
            raise ConnectionError('cannot reach local model API') from exc

    async def probe(self): return await asyncio.to_thread(self.request,'/models')

    async def propose(self,task,summary,images,error):
        # Deliberately omit object name, world transform, object-local centre and full mesh.
        instruction=dict(task_id=task['id'],instruction=task['instruction'],material=task['material'],
                         fragment=summary,previous_error=error)
        text=json.dumps(instruction,ensure_ascii=False,allow_nan=False)
        if len(text)+len(SYSTEM)>12000:
            raise ValueError('local prompt too long; shorten instruction/summary')
        if len(images)>2: raise ValueError('at most two local images per request')
        content=[{'type':'text','text':text}]
        for path in images:
            content.append({'type':'image_url','image_url':{'url':image_url(path)}})
        payload=dict(model=self.config['name'],messages=[{'role':'system','content':SYSTEM},
                      {'role':'user','content':content}],temperature=0.2,max_tokens=self.output,
                      stream=False)
        if self.config.get('json_mode',True): payload['response_format']={'type':'json_object'}
        if self.config.get('disable_thinking',True):
            payload['chat_template_kwargs']={'enable_thinking':False}
        response=await asyncio.to_thread(self.request,'/chat/completions',payload)
        try:
            choice=response['choices'][0]
            if choice.get('finish_reason')!='stop':
                raise ValueError('model did not finish normally; output truncated or unexpected tool call')
            usage=response.get('usage',{})
            total=usage.get('total_tokens',usage.get('prompt_tokens',0)+usage.get('completion_tokens',0))
            if total>self.context: raise ValueError('reported token usage exceeds configured context')
            return parse_recipe(choice['message']['content'])
        except (KeyError,IndexError,TypeError) as exc:
            raise ValueError('invalid chat API response') from exc
