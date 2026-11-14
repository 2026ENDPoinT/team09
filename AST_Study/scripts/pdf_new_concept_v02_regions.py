"""New개념Ver ver.02: typography-aware local fragments with matching native word geometry.

No remote calls. The old region extractor remains unchanged. Images/tables stay
atomic; unsupported coordinate frames or unlocated vector art retain the page.
"""
from __future__ import annotations
import io
from contextlib import ExitStack
import math
import re
from collections import Counter
from pathlib import Path
from statistics import median

from pdf_pipeline import check_cancel, repaired_textmap, image_regions, write_json
from pdf_regions import box_ok, union, inside, partitions, page_image, digest
import pdf_image_transport
from pdf_study_reading_policy import coherent_chart

VERSION = 'new-concept-layout-ver.02-symbol-bullets-4'
NUMBERED = re.compile(r'^(\d+(?:\.\d+)*)(?:\.)?\s+\S')
LIST = re.compile(r'^(?:[①-⑳•●▪❖▶※]|[-–]\s|\(?\d+[.)]\s)')


def contains(a, b, tol=1e-7):
    return a[0]-tol <= b[0] and a[1]-tol <= b[1] and a[2]+tol >= b[2] and a[3]+tol >= b[3]


def overlap(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def raster_tiles_touch(a, b):
    """Join aligned strips/tiles of one raster without joining unrelated figures.

    Some PDF exporters store a screenshot as one-pixel scanlines, or a header
    rule as hundreds of image-mask squares. image_regions' identity dedup can
    leave gaps up to .004 page units between such strips. Keep those pixels in
    one crop, including the intervening gap, instead of asking the model to
    explain each strip. Genuine whitespace and diagonal/corner contacts do not
    join; vector/table regions retain their existing overlap-only behavior.
    """
    tolerance = .004001
    horizontal = (min(a[3], b[3]) > max(a[1], b[1])
                  and abs(a[1]-b[1]) <= tolerance and abs(a[3]-b[3]) <= tolerance
                  and max(a[0]-b[2], b[0]-a[2]) <= tolerance)
    vertical = (min(a[2], b[2]) > max(a[0], b[0])
                and abs(a[0]-b[0]) <= tolerance and abs(a[2]-b[2]) <= tolerance
                and max(a[1]-b[3], b[1]-a[3]) <= tolerance)
    return horizontal or vertical


def merge_visuals(regions):
    result=[]
    for region in regions:
        box=region['bbox']; kinds={region['kind']}
        again=True
        while again:
            again=False
            for old in list(result):
                raster_join = (kinds == {'raster'} and set(old['kinds']) == {'raster'}
                               and raster_tiles_touch(box, old['bbox']))
                if overlap(box, old['bbox']) or raster_join:
                    box=union([box,old['bbox']]); kinds.update(old['kinds'])
                    result.remove(old); again=True
        result.append({'bbox':box,'kinds':sorted(kinds)})
    return result


def rows_for(words):
    rows=[]
    for w in sorted(words,key=lambda x:(x['bbox'][1],x['bbox'][0])):
        b=w['bbox']; center=(b[1]+b[3])/2
        # Superscripts/subscripts may have a different baseline; keep them on their line.
        matching=next((r for r in reversed(rows[-3:]) if
            min(r['bbox'][3],b[3])-max(r['bbox'][1],b[1]) > min(r['bbox'][3]-r['bbox'][1],b[3]-b[1])*.45),None)
        if matching is None:rows.append({'bbox':b[:],'words':[w]})
        else:matching['words'].append(w);matching['bbox']=union([matching['bbox'],b])
    output=[]
    for row in rows:
        # Wide horizontal whitespace separates columns; ordinary word spacing does not.
        parts=[];current=[];right=0
        for w in sorted(row['words'],key=lambda x:x['bbox'][0]):
            if current and w['bbox'][0]-right > .05:parts.append(current);current=[]
            current.append(w);right=w['bbox'][2]
        if current:parts.append(current)
        for part in parts:
            text=' '.join(w['text'] for w in part)
            weighted=[w['size'] for w in part for _ in range(max(1,len(w['text'])))]
            weight=sum(len(w['text']) for w in part) or 1
            output.append({'words':part,'bbox':union([w['bbox'] for w in part]),'text':text,
                'fontSize':round(median(weighted),2),
                'bold':sum(len(w['text']) for w in part if w['bold'])/weight>.65})
    return sorted(output,key=lambda r:(round(r['bbox'][1],3),r['bbox'][0]))


def row_kind(row, body_size):
    text=row['text'].strip(); b=row['bbox']
    if re.fullmatch(r'(?:[-–]\s*)?\d{1,4}(?:\s*[-–])?',text) and ((b[1]>.85 and .35<(b[0]+b[2])/2<.65) or b[3]<.04):
        return 'page_number',None
    number=NUMBERED.match(text)
    larger=row['fontSize']>body_size*1.12
    short=len(text)<=100
    heading=short and (larger or (number and ('.' in number.group(1) or row['bold'])))
    if heading:return 'heading',len(number.group(1).split('.')) if number else None
    if text.startswith(('출처:', '자료:', '그림 ', '표 ')):return 'caption',None
    return 'text',None


def order_panel_titles(blocks, zones):
    """Place an unmistakable top title before a slightly higher large diagram.

    Exported diagrams can extend to the top edge beside a title. Pure y sorting
    otherwise attaches that diagram to the previous slide's heading. This local
    rule changes neither pixels, word ownership nor boxes; it runs before stable
    fragment IDs are assigned. Ambiguous labels, captions and competing titles
    retain their original source order.
    """
    result = list(blocks)
    for zone in zones:
        width, height = zone[2]-zone[0], zone[3]-zone[1]
        if width <= 0 or height <= 0:
            continue
        panel = [b for b in result if contains(zone, b['bbox'])]
        text_blocks = [b for b in panel if not b.get('hasVisual')
                       and b.get('kind') != 'page_number' and b.get('text', '').strip()]
        candidates = []
        for title in text_blocks:
            box = title['bbox']; text = title['text'].strip()
            if (title.get('kind') not in ('heading', 'text')
                    or not 2 <= len(text) <= 80 or '\n' in text
                    or (title.get('fontSize') or 0) < 18
                    or (box[1]-zone[1])/height > .12 or (box[3]-zone[1])/height > .20
                    or box[3]-box[1] > height*.14
                    or not re.search(r'[가-힣A-Za-z]{2,}', text)
                    or re.search(r'[=∫∑→]|[.!?。:：]$', text)
                    or LIST.match(text)
                    or re.match(r'^(?:그림|표|출처|자료)\s*\d|^(?:fig(?:ure)?|table)\b', text, re.I)):
                continue
            # A lone large native title has no smaller body text to compare its
            # size to, so row_kind conservatively leaves it as plain text.
            # Promote only that unambiguous case; never a label among other text.
            if title['kind'] == 'text' and len(text_blocks) != 1:
                continue
            if any(other is not title and other['bbox'][1] < box[3]
                   for other in text_blocks):
                continue
            visuals = [b for b in panel if b.get('hasVisual') and b.get('kind') == 'visual'
                       and b['bbox'][2]-b['bbox'][0] >= width*.18
                       and b['bbox'][3]-b['bbox'][1] >= height*.25
                       and (b['bbox'][2]-b['bbox'][0])*(b['bbox'][3]-b['bbox'][1]) >= width*height*.12
                       and box[1]-height*.07 <= b['bbox'][1] <= box[3]
                       and b['bbox'][3] >= box[3]+height*.15]
            if visuals:
                candidates.append((title, visuals))
        if len(candidates) != 1:
            continue
        title, visuals = candidates[0]
        # Any second heading in this panel can delimit a different illustration.
        if any(b is not title and b.get('kind') == 'heading' for b in panel):
            continue
        if title['kind'] == 'text':
            title['kind'] = 'heading'
            title['localTitleRecovered'] = True
        first = min([result.index(title)]+[result.index(b) for b in visuals])
        if result.index(title) != first:
            result.remove(title)
            result.insert(first, title)
    return result



def normalized_box(obj, page):
    return [max(0.,obj['x0']/page.width),max(0.,obj['top']/page.height),
            min(1.,obj['x1']/page.width),min(1.,obj['bottom']/page.height)]


def visible_word_box(box):
    """Intersect a glyph's metric box with the page instead of losing visible text."""
    if (not isinstance(box, (list, tuple)) or len(box) != 4
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in box)
            or box[0] >= box[2] or box[1] >= box[3]):
        return None
    clipped = [max(0., box[0]), max(0., box[1]), min(1., box[2]), min(1., box[3])]
    return clipped if box_ok(clipped) else None


def background_shape(obj, page):
    """Only non-stroked white fills, text backplates and page-wide rules.

    Stroke-based table grids and compact chart bars remain available. White
    backplates cannot provide table rulings but their foreground text is retained.
    """
    if obj.get('object_type')!='rect' or obj.get('stroke') or not obj.get('fill'):
        return False
    color=obj.get('non_stroking_color')
    white=color==1 or isinstance(color,(tuple,list)) and len(color) in (1,3) and all(c>=.985 for c in color)
    if white:return True
    b=normalized_box(obj,page);w=b[2]-b[0];h=b[3]-b[1]
    if w>.70 and h<.008:return True
    if w>.55 and .018<h<.14:
        chars=[c for c in page.chars if obj['x0']<=c['x0']<obj['x1'] and obj['top']<=c['top']<obj['bottom']]
        return len(chars)>=5
    return False


def table_regions(page):
    """Require an occupied grid, not a grid assembled from page furniture."""
    filtered=page.filter(lambda o:not background_shape(o,page))
    if not 4<=len(filtered.edges)<=2000:return []
    regions=[]
    for table in filtered.find_tables({'vertical_strategy':'lines','horizontal_strategy':'lines'}):
        if len(table.cells)<4:continue
        rows=table.extract();occupied=[(i,j) for i,row in enumerate(rows) for j,t in enumerate(row) if t and t.strip()]
        if len(occupied)<3 or len({i for i,j in occupied})<2 or len({j for i,j in occupied})<2:continue
        if len(occupied)/len(table.cells)<.25:continue
        x0,y0,x1,y1=table.bbox
        box=[max(0,x0/page.width),max(0,y0/page.height),min(1,x1/page.width),min(1,y1/page.height)]
        if box_ok(box):regions.append({'bbox':box,'kind':'table'})
    return regions


def page_zones(page,words):
    """Detect repeated slide frames; never split through a word/image."""
    rules=sorted({round(o['top']/page.height,3) for o in page.rects
                  if o['width']/page.width>.7 and o['height']/page.height<.008})
    paired=sum(any(.47<abs(a-b)<.53 for b in rules) for a in rules)
    if paired>=4:
        objects=[w['bbox'] for w in words]+[x['bbox'] for x in image_regions(page)]
        cuts=[.5+i*.002 for i in range(-12,13)]
        cut=next((c for c in sorted(cuts,key=lambda v:abs(v-.5))
                  if not any(b[1]<c<b[3] for b in objects)),None)
        if cut is not None:return [[0.,0.,1.,cut],[0.,cut,1.,1.]]
    return [[0.,0.,1.,1.]]


def vector_regions(page,visuals):
    regions=[]
    for o in [*page.curves,*page.lines,*page.rects]:
        if background_shape(o,page):continue
        b=normalized_box(o,page)
        if max(b[2]-b[0],b[3]-b[1])<.012:continue
        if any(contains(v['bbox'],b,.003) for v in visuals):continue
        # Slightly expand zero-width axes so they can participate in clustering.
        b=[max(0,b[0]-.003),max(0,b[1]-.003),min(1,b[2]+.003),min(1,b[3]+.003)]
        if box_ok(b):regions.append({'bbox':b,'kind':'vector'})
    return regions


def fragment_page(page,saved,compatible=True):
    import pdfplumber
    n=saved['number'];_,chars,_=repaired_textmap(page)
    raw=pdfplumber.utils.extract_words(chars,extra_attrs=['size','fontname'])
    words=[{'text':w['text'],'bbox':[w['x0']/page.width,w['top']/page.height,w['x1']/page.width,w['bottom']/page.height],
            'size':w['size'],'bold':any(x in w['fontname'].lower() for x in ('bold','black','heavy','demi'))} for w in raw]
    visible=[]
    for word in words:
        box=visible_word_box(word['bbox'])
        if box is not None:
            visible.append({**word,'bbox':box,**({'pageEdgeClipped':True} if box!=word['bbox'] else {})})
    words=visible
    for i,w in enumerate(words):w['id']=f'p{n}w{i}'
    if not compatible or not words:
        return [{'id':f'v2p{n}f0','page':n,'bbox':[0.,0.,1.,1.],
            'text':saved.get('nativeText',''),'kind':'page','headingLevel':None,'fontSize':None,
            'hasVisual':True,'visualKinds':['page_fallback'],'visualOnly':not words,
            'geometryFallback':True,'zone':0,'wordIds':[w['id'] for w in words]}],words
    zones=page_zones(page,words)
    objects=image_regions(page)+table_regions(page)
    visuals=merge_visuals(objects+vector_regions(page,objects))
    blocks=[];remaining=words[:]
    for visual in visuals:
        selected=[w for w in remaining if inside(w['bbox'],visual['bbox'])]
        owned={w['id'] for w in selected};remaining=[w for w in remaining if w['id'] not in owned]
        box=union([visual['bbox']]+[w['bbox'] for w in selected])
        blocks.append({'bbox':box,'text':'\n'.join(r['text'] for r in rows_for(selected)),
            'kind':'visual','headingLevel':None,'fontSize':None,'hasVisual':True,'visualKinds':visual['kinds'],
            'wordIds':[w['id'] for w in selected]})
    for z,zone in enumerate(zones):
        selected=[w for w in remaining if inside(w['bbox'],zone)]
        body=median([w['size'] for w in selected]) if selected else 12
        tiles=partitions([w['bbox'] for w in selected],zone) if selected else []
        for tile in tiles:
            rows=rows_for([w for w in selected if inside(w['bbox'],tile)])
            current=[]
            def flush():
                if not current:return
                text='\n'.join(r['text'] for r in current);kind,level=row_kind(current[0],body)
                # Large mathematical glyphs are not section headings.
                if kind=='heading' and not re.search(r'[가-힣A-Za-z]{2,}',text):kind,level='text',None
                blocks.append({'bbox':union([r['bbox'] for r in current]),'text':text,'kind':kind,
                    'headingLevel':level,'fontSize':current[0]['fontSize'],'hasVisual':False,'visualKinds':[],
                    'wordIds':[w['id'] for r in current for w in r['words']]})
                current.clear()
            for row in rows:
                kind,_=row_kind(row,body)
                if current:
                    prev=current[-1];height=prev['bbox'][3]-prev['bbox'][1];gap=row['bbox'][1]-prev['bbox'][3]
                    style=abs(row['fontSize']-prev['fontSize'])>max(.8,prev['fontSize']*.12)
                    if kind=='heading' or gap>max(.012,height*.65) or style or LIST.match(row['text']):flush()
                current.append(row)
            flush()
    blocks.sort(key=lambda b:(next((z for z,zone in enumerate(zones) if inside(b['bbox'],zone)),0),round(b['bbox'][1],3),b['bbox'][0]))
    blocks=order_panel_titles(blocks,zones)
    for i,b in enumerate(blocks):
        z=next((z for z,zone in enumerate(zones) if inside(b['bbox'],zone)),0)
        b.update(id=f'v2p{n}f{i}',page=n,zone=z,zoneBounds=zones[z],visualOnly=not b['text'].strip(),geometryFallback=False)
        if any(w.get('pageEdgeClipped') for w in words if w['id'] in b['wordIds']):
            b['pageEdgeClipped']=True
        from pdf_study_text_input import native_prose_verified, VERSION as TEXT_PROOF_VERSION
        if native_prose_verified(page,b,chars):
            b['nativeTextProof']=TEXT_PROOF_VERSION
    # Metadata-only title/objective panels remain accounted for but need no generation.
    for z,zone in enumerate(zones):
        local=[b for b in blocks if b['zone']==z];text='\n'.join(b['text'] for b in local)
        objective=bool(re.search(r'학습\s*목표|Learning Objectives|\bContents\b',text,re.I)) and len(text)<700 and not re.search(r'[=∫]|(?:이다|한다|됩니다|해요)[.]',text)
        for b in local:
            if objective:b['localRole']='navigation'
            rel=(b['bbox'][1]-zone[1])/(zone[3]-zone[1])
            # Repeated frame's header/footer strip; generic single-page files use
            # corpus repetition below instead of erasing their first/last lines.
            if len(zones)>1 and (rel<.065 or rel>.93):b['localRole']='decoration'
    return blocks,words


def extract(folder,document,numbers,cache=None):
    import pdfplumber
    from pdf_page_analysis import frame_compatible
    blocks=[];catalog=[]
    with pdfplumber.open(Path(folder)/'source.pdf') as pdf:
        for n in numbers:
            check_cancel(folder)
            found,words=fragment_page(pdf.pages[n-1],document['pages'][n-1],frame_compatible(folder,n))
            catalog.append({'page':n,'words':words,'fragments':found});blocks.extend(found)
    # Repeated marginal furniture is recorded, not deleted from the audit trail.
    freq=Counter()
    def key(b):return (re.sub(r'\d+','#',b['text'].strip()),round(b['bbox'][0],1),round(b['bbox'][1],2))
    for page in catalog:
        freq.update({key(b) for b in page['fragments'] if not b['hasVisual'] and (b['bbox'][1]<.055 or b['bbox'][3]>.94)})
    # Explicit unanswered exercise panels are excluded locally. Worked steps or
    # an existing conceptual explanation keep the panel eligible. This conservative
    # rule follows the user's preference to omit ambiguous source examples.
    panels={}
    for b in blocks:panels.setdefault((b['page'],b.get('zone',0)),[]).append(b)
    for panel in panels.values():
        active=[b for b in panel if not b.get('localRole')]
        text='\n'.join(b['text'] for b in active)
        start=re.search(r'(?:^|\n)\s*(?:예제[. ]|문제\s*\d+[. ])',text)
        if not start:continue
        before=text[:start.start()].strip()
        questions=list(re.finditer(r'(?:구하여라|구하시오|구하라|계산하라|증명하여라)[.]?',text))
        if not questions:continue
        tail=text[questions[-1].end():].strip()
        if not re.search(r'[가-힣A-Za-z]{2,}',before) and not tail and not re.search(r'풀이|해설|Solution',text,re.I):
            for b in active:b['localRole']='exercise'
    heading=None
    for b in blocks:

        if len(catalog)>=3 and freq[key(b)]>=max(3,len(catalog)*.6):b['localRole']='decoration'
        if b.get('localRole') in ('navigation','decoration'):
            b['headingId']=None;b['headingTitle']=None;heading=None;continue
        if b['kind']=='heading':heading=b
        b['headingId']=heading['id'] if heading else None
        b['headingTitle']=heading['text'] if heading else None
    if cache:write_json(Path(cache)/'local-layout.json',{'version':VERSION,'pages':catalog,'excludedPageNumbers':[]})
    return blocks


def crop_runs(blocks):
    # Keep chart axes, labels, annotation arrows and bars in the same frame.
    # Detect only within contiguous page/panel spans, never across slide boundaries.
    spans=[]
    for block in blocks:
        if spans and (spans[-1][0]['page'],spans[-1][0].get('zone')) == (block['page'],block.get('zone')):
            spans[-1].append(block)
        else:spans.append([block])
    if any(coherent_chart(span) for span in spans):
        return [run for span in spans for run in
                ([span] if coherent_chart(span) else _fragment_crop_runs(span))]
    return _fragment_crop_runs(blocks)


def _fragment_crop_runs(blocks):
    runs=[]
    for b in blocks:
        if runs and runs[-1][0]['page']==b['page'] and runs[-1][0].get('zone')==b.get('zone') and b.get('kind') not in ('heading','label'):
            prev=union([x['bbox'] for x in runs[-1]]);box=b['bbox']
            vertical_overlap=min(prev[3],box[3])-max(prev[1],box[1])
            horizontal_overlap=min(prev[2],box[2])-max(prev[0],box[0])
            below=0<=box[1]-prev[3]<.06 and horizontal_overlap>0
            alongside=vertical_overlap>0 and max(box[0]-prev[2],prev[0]-box[2])<.25
            if below or alongside:
                runs[-1].append(b);continue
        runs.append([b])
    # Five small formula/text crops in one panel can exceed the provider cap.
    # Combine the nearest same-panel runs before transporting, never across a
    # slide boundary. The manifest names every included source fragment.
    while len(runs)>4:
        choices=[]
        for i in range(len(runs)-1):
            a,b=runs[i],runs[i+1]
            if (a[0]['page'],a[0].get('zone'))!=(b[0]['page'],b[0].get('zone')):continue
            if b[0].get('kind') in ('heading','label') and re.search(r'[가-힣]{2,}',b[0]['text']):continue
            box=union([x['bbox'] for x in a+b]);choices.append(((box[2]-box[0])*(box[3]-box[1]),i))
        if not choices:break
        _,i=min(choices);runs[i:i+2]=[runs[i]+runs[i+1]]
    return runs


from pdf_performance import timed, measure

@timed("crop_preparation_total")
def render_crops(folder, blocks, root):
    """One image per adjacent run per page, not one huge union across unrelated gaps."""
    root=Path(root);images=[];manifest=[]
    runs=crop_runs(blocks)
    page=None;current_page=None;page_context=ExitStack()
    try:
        for selected in runs:
            n=selected[0]['page'];box=union([b['bbox'] for b in selected])
            # Native Korean font boxes can miss visible top strokes. A small page-relative
            # margin preserves glyphs without the old 0.8% padding into neighboring text.
            if n != current_page:
                if page is not None:page.close()
                page_context.close()
                page=None
                page=page_context.enter_context(page_image(folder,n,root));current_page=n
            if page is not None:
                pad_x=max(3,math.ceil(page.width*.003));pad_y=max(3,math.ceil(page.height*.003))
                pixels=(max(0,math.floor(box[0]*page.width)-pad_x),max(0,math.floor(box[1]*page.height)-pad_y),
                        min(page.width,math.ceil(box[2]*page.width)+pad_x),min(page.height,math.ceil(box[3]*page.height)+pad_y))
                padded=[pixels[0]/page.width,pixels[1]/page.height,pixels[2]/page.width,pixels[3]/page.height]
                with page.crop(pixels) as crop:
                    with measure(folder,'crop_png_encode',page=n):
                        from pdf_local_preparation_cache import crop_png
                        raw=crop_png(crop,root/'crop-encoding-cache')
                    path=root/'crops'/(digest([n,padded,crop.size])[:24]+'.png');path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(raw)
                    # The persisted crop remains the original PNG. Optional wire
                    # compression changes only request bytes, never pixels or size.
                    with measure(folder,'crop_wire_encode',page=n):
                        images.append(pdf_image_transport.encode_crop(crop,png_bytes=raw,
                                      cache_dir=root/'transport-cache'))
                    manifest.append({'page':n,'bbox':padded,'blockIds':[b['id'] for b in selected],
                        'path':str(path),'width':crop.width,'height':crop.height})
    finally:
        if page is not None:page.close()
        page_context.close()
    return images,manifest
