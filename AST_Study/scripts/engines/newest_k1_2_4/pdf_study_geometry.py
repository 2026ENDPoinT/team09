"""Read vector connectivity locally, without OCR, source edits or another API call."""
from functools import lru_cache
from pathlib import Path
import math


def shared_endpoints(shapes, width, height):
    edges=[];seen=set()
    for shape in shapes:
        path=shape.get('path',[])
        if (not shape.get('stroke') or shape.get('fill') or not path
                or any(p[0]=='h' for p in path)
                or sum(p[0]=='m' for p in path)!=1):continue
        points=shape.get('pts',[])
        if len(points)<2:continue
        a=(points[0][0]/width,points[0][1]/height)
        b=(points[-1][0]/width,points[-1][1]/height)
        if math.dist(a,b)<.06:continue
        signature=tuple((round(x/width,5),round(y/height,5))for x,y in points)
        if signature in seen or signature[::-1]in seen:continue
        seen.add(signature)
        edges.append({'start':a,'end':b,'curved':any(p[0]=='c'for p in path),
            'bbox':[shape['x0']/width,shape['top']/height,shape['x1']/width,shape['bottom']/height]})
    groups=[]
    for edge in edges:
        group=next((g for g in groups if all(
            (math.dist(edge['start'],p['start'])<.013 and math.dist(edge['end'],p['end'])<.013)
            or (math.dist(edge['start'],p['end'])<.013 and math.dist(edge['end'],p['start'])<.013)
            for p in g)),None)
        if group is None:groups.append([edge])
        else:group.append(edge)
    # Several distinct curved edges avoid confusing table rules/overprinted
    # strokes with a diagram. Do not infer an itinerary or semantic direction.
    return [g for g in groups if len(g)>=3 and sum(e['curved']for e in g)>=2]


@lru_cache(maxsize=128)
def _page_connections(path,mtime,size,page_number):
    import pdfplumber
    with pdfplumber.open(path)as pdf:
        page=pdf.pages[page_number-1]
        return shared_endpoints(page.curves+page.lines,page.width,page.height)


def connection_hints(folder,blocks):
    path=Path(folder)/'source.pdf'
    if not path.is_file():return []
    candidates=[b for b in blocks if b.get('hasVisual') and 'vector'in b.get('visualKinds',[]) and b.get('bbox')]
    if not candidates:return []
    stat=path.stat();result=[]
    for number in sorted({b['page']for b in candidates}):
        try:groups=_page_connections(str(path.resolve()),stat.st_mtime_ns,stat.st_size,number)
        except (OSError,ValueError,IndexError,KeyError,TypeError):continue
        for group in groups:
            # Every edge must fit in an owned diagram region. Never import
            # another diagram from elsewhere on the same page.
            owners=[b for b in candidates if b['page']==number and all(
                b['bbox'][0]-.015<=e['bbox'][0] and b['bbox'][1]-.015<=e['bbox'][1]
                and e['bbox'][2]<=b['bbox'][2]+.015 and e['bbox'][3]<=b['bbox'][3]+.015
                for e in group)]
            if not owners:continue
            result.append({'page':number,'blockIds':[b['id']for b in owners],
                'edgeCount':len(group),'endpoints':[list(group[0]['start']),list(group[0]['end'])],
                'relation':'Distinct vector paths share the same pair of endpoint locations. Geometry alone does not establish a successive end-to-start itinerary.',
                'scope':'Page-normalized geometry only. Read the source to determine whether these are alternatives, parallel connections, or an explicitly stated itinerary. Do not sum all paths merely because their labels are listed.'})
    return result
