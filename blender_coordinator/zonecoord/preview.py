"""Local-only geometry previews. Not textured/photorealistic Blender renders."""
import math
from .core import inside, normal, length


def save_preview(snapshot,task,path):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    image=Image.new('RGB',(960,380),'#151a23');draw=ImageDraw.Draw(image)
    vertices=snapshot['vertices'];h=task['outer_half_mm'];core=task['core_half_mm']
    # Full faces must fit in local box, so no room-wide geometry leaks to the model.
    triangles=[t for t in snapshot['triangles'] if all(inside(vertices[i],h) for i in t)]
    for panel,(a,b,depth,label) in enumerate([(0,2,1,'XZ'),(0,1,2,'XY'),(1,2,0,'YZ')]):
        ox=panel*320+160;oy=195;scale=130/h
        draw.text((panel*320+15,12),label+' | LOCAL mm | geometry only',fill='white')
        for t in sorted(triangles,key=lambda t:sum(vertices[i][depth] for i in t)):
            points=[(ox+vertices[i][a]*scale,oy-vertices[i][b]*scale) for i in t]
            n=normal(vertices,t);shade=0.3+0.7*abs(n[depth])/max(length(n),1e-12)
            c=int(80+shade*100)
            draw.polygon(points,fill=(c,c,min(c+20,255)),outline=(65,74,88))
        for half,color in [(h,'#6b8cac'),(core,'#e5b75b')]:
            extent=half*scale
            draw.rectangle((ox-extent,oy-extent,ox+extent,oy+extent),outline=color,width=2)
        draw.line((ox-4,oy,ox+4,oy),fill='red',width=2)
        draw.line((ox,oy-4,ox,oy+4),fill='red',width=2)
        draw.text((panel*320+15,350),f'core +/-{core:.2f}; view +/-{h:.2f}',fill='white')
    image.save(path)
    return path
