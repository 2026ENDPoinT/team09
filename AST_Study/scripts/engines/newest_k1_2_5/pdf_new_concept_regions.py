"""New개념Ver: typography-aware local fragments with matching native word geometry.

No remote calls. The old region extractor remains unchanged. Images/tables stay
atomic; unsupported coordinate frames or unlocated vector art retain the page.
"""
from __future__ import annotations
import base64
import io
import math
import re
from collections import Counter
from pathlib import Path
from statistics import median

from pdf_pipeline import check_cancel, repaired_textmap, image_regions, table_regions, write_json
from pdf_regions import box_ok, union, inside, partitions, page_image, digest

VERSION = 'new-concept-layout-v3'
NUMBERED = re.compile(r'^(\d+(?:\.\d+)*)(?:\.)?\s+\S')
LIST = re.compile(r'^(?:[①-⑳•●▪▶※]|[-–]\s|\(?\d+[.)]\s)')


def contains(a, b, tol=1e-7):
    return a[0]-tol <= b[0] and a[1]-tol <= b[1] and a[2]+tol >= b[2] and a[3]+tol >= b[3]


def overlap(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def merge_visuals(regions):
    result=[]
    for region in regions:
        box=region['bbox']; kinds={region['kind']}
        again=True
        while again:
            again=False
            for old in list(result):
                if overlap(box, old['bbox']):
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


def fragment_page(page, saved, compatible=True):
    import pdfplumber
    n=saved['number']
    textmap,chars,_=repaired_textmap(page)
    raw=pdfplumber.utils.extract_words(chars,extra_attrs=['size','fontname'])
    words=[{'text':w['text'],'bbox':[w['x0']/page.width,w['top']/page.height,w['x1']/page.width,w['bottom']/page.height],
            'size':w['size'],'bold':any(s in w['fontname'].lower() for s in ('bold','black','heavy','demi'))} for w in raw]
    words=[w for w in words if box_ok(w['bbox'])]
    visuals=merge_visuals(image_regions(page)+table_regions(page))
    # Vector diagrams have no embedded raster object. Until reliable clustering exists,
    # retain their full page instead of losing arrows/axes in text-only rectangles.
    unknown_vectors=[]
    for obj in [*page.curves,*page.lines,*page.rects]:
        b=[max(0,obj['x0']/page.width),max(0,obj['top']/page.height),min(1,obj['x1']/page.width),min(1,obj['bottom']/page.height)]
        if (b[2]-b[0]>.025 or b[3]-b[1]>.025) and not any(contains(v['bbox'],b,.003) for v in visuals):unknown_vectors.append(b)
    fallback=not compatible or not words or len(unknown_vectors)>=4
    if fallback:
        text=saved.get('nativeText','') if not compatible else '\n'.join(r['text'] for r in rows_for(words))
        return [{'id':f'n{n}f0','page':n,'bbox':[0.,0.,1.,1.], 'text':text,
            'kind':'page','headingLevel':None,'fontSize':None,'hasVisual':True,
            'visualKinds':['page_fallback'],'visualOnly':not text.strip(),'geometryFallback':True}],words
    body_size=median([w['size'] for w in words for _ in range(max(1,len(w['text'])))])
    blocks=[];remaining=words[:]
    for visual in visuals:
        selected=[w for w in remaining if overlap(w['bbox'],visual['bbox'])]
        remaining=[w for w in remaining if w not in selected]
        box=union([visual['bbox']]+[w['bbox'] for w in selected])
        blocks.append({'bbox':box,'text':'\n'.join(r['text'] for r in rows_for(selected)),
                       'kind':'visual','headingLevel':None,'fontSize':None,'hasVisual':True,'visualKinds':visual['kinds']})
    # Coarse whitespace cuts preserve reading columns. Typography refines each tile.
    tiles=partitions([w['bbox'] for w in remaining]+[v['bbox'] for v in visuals]) if remaining else []
    for tile in sorted(tiles,key=lambda b:(round(b[1],3),b[0])):
        rows=rows_for([w for w in remaining if inside(w['bbox'],tile)])
        gaps=[b['bbox'][1]-a['bbox'][3] for a,b in zip(rows,rows[1:])
              if 0<=b['bbox'][1]-a['bbox'][3]<= (a['bbox'][3]-a['bbox'][1])*1.5]
        typical_gap=median(gaps) if gaps else 0
        current=[];last_kind=None
        def flush():
            if not current:return
            kind,level=row_kind(current[0],body_size)
            blocks.append({'bbox':union([r['bbox'] for r in current]),'text':'\n'.join(r['text'] for r in current),
                'kind':kind,'headingLevel':level,'fontSize':current[0]['fontSize'],
                'hasVisual':False,'visualKinds':[]})
            current.clear()
        for row in rows:
            kind,_=row_kind(row,body_size)
            if current:
                prev=current[-1]; height=prev['bbox'][3]-prev['bbox'][1];gap=row['bbox'][1]-prev['bbox'][3]
                style=abs(row['fontSize']-prev['fontSize'])>max(.7,prev['fontSize']*.10) or row['bold']!=prev['bold']
                indent=abs(row['bbox'][0]-prev['bbox'][0])>.018
                paragraph=gap>max(height*.55,typical_gap*1.35) or indent or bool(LIST.match(row['text']))
                # A short preceding line followed by a left-aligned new line often ends a paragraph.
                short_end=(prev['bbox'][2]-prev['bbox'][0]) < (tile[2]-tile[0])*.62 and gap>height*.2
                if kind!='text' or last_kind!='text' or style or paragraph or short_end:flush()
            current.append(row);last_kind=kind
        flush()
    blocks.sort(key=lambda b:(round(b['bbox'][1],3),b['bbox'][0]))
    # Plain-font list introductions are structural too. A label alone has no
    # definition to lose: attach it forward instead of reporting it as a missing fact.
    for i,b in enumerate(blocks):
        text=b['text'].strip()
        next_text=blocks[i+1]['text'].strip() if i+1<len(blocks) else ''
        if (b['kind']=='text' and len(text)<=60 and '\n' not in text
                and not LIST.match(text) and not re.search(r'[.!?。]$',text)
                and (text.endswith((':','：')) or re.match(r'^(?:①|1[.)])\s',next_text)
                     or (text.startswith('(참고)') and text.endswith(('종류','유형','구분'))))):
            b['kind']='label'
    for i,b in enumerate(blocks):
        b.update(id=f'n{n}f{i}',page=n,visualOnly=not b['text'].strip(),geometryFallback=False)
    return blocks,words


def extract(folder, document, numbers, cache=None):
    import pdfplumber
    from pdf_page_analysis import frame_compatible
    blocks=[];catalog=[];excluded=[]
    with pdfplumber.open(Path(folder)/'source.pdf') as pdf:
        for n in numbers:
            check_cancel(folder)
            found,words=fragment_page(pdf.pages[n-1],document['pages'][n-1],frame_compatible(folder,n))
            catalog.append({'page':n,'words':words,'fragments':found})
            for b in found:
                if b['kind']=='page_number':excluded.append(b)
                else:blocks.append(b)
    # Keep the last heading as explicit context for both the planner and the teacher.
    heading=None
    for b in blocks:
        if b['kind']=='heading':heading=b
        b['headingId']=heading['id'] if heading else None
        b['headingTitle']=heading['text'] if heading else None
    if cache:
        write_json(Path(cache)/'local-layout.json',{'version':VERSION,'pages':catalog,'excludedPageNumbers':excluded})
    return blocks


def crop_runs(blocks):
    runs=[]
    for b in blocks:
        if runs and runs[-1][0]['page']==b['page'] and b['bbox'][1]-max(x['bbox'][3] for x in runs[-1])<.07:
            runs[-1].append(b)
        else:runs.append([b])
    return runs


def render_crops(folder, blocks, root):
    """One image per adjacent run per page, not one huge union across unrelated gaps."""
    root=Path(root);images=[];manifest=[]
    runs=crop_runs(blocks)
    for selected in runs:
        n=selected[0]['page'];box=union([b['bbox'] for b in selected])
        # Native Korean font boxes can miss visible top strokes. A small page-relative
        # margin preserves glyphs without the old 0.8% padding into neighboring text.
        with page_image(folder,n,root) as page:
            pad_x=max(3,math.ceil(page.width*.003));pad_y=max(3,math.ceil(page.height*.003))
            pixels=(max(0,math.floor(box[0]*page.width)-pad_x),max(0,math.floor(box[1]*page.height)-pad_y),
                    min(page.width,math.ceil(box[2]*page.width)+pad_x),min(page.height,math.ceil(box[3]*page.height)+pad_y))
            padded=[pixels[0]/page.width,pixels[1]/page.height,pixels[2]/page.width,pixels[3]/page.height]
            with page.crop(pixels) as crop:
                buf=io.BytesIO();crop.save(buf,format='PNG');raw=buf.getvalue()
                path=root/'crops'/(digest([n,padded,crop.size])[:24]+'.png');path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(raw)
                images.append({'data':'data:image/png;base64,'+base64.b64encode(raw).decode(),
                    'width':crop.width,'height':crop.height,'bytes':len(raw)})
                manifest.append({'page':n,'bbox':padded,'blockIds':[b['id'] for b in selected],
                    'path':str(path),'width':crop.width,'height':crop.height})
    return images,manifest
