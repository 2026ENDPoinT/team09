"""Prove repeated tiny bitmap ornament strips, not semantic figure content.

No OCR/model or image resizing. A match needs empty native text, margin geometry,
many small identical PDF tiles, no overlapping native glyphs, and repetition on
three distinct pages. Ordinary raster pictures, labels, tables and charts fail
closed. Canonical extraction stays intact; only the plan decoration role changes.
"""
import collections
import hashlib
from pathlib import Path


def candidates(blocks):
    selected=[]
    for b in blocks:
        box=b.get('bbox',[])
        if (b.get('kind')!='visual' or b.get('text','').strip() or b.get('wordIds')
                or b.get('geometryFallback') or b.get('visualKinds')!=['raster'] or len(box)!=4):continue
        x0,y0,x1,y1=box;width=x1-x0;height=y1-y0
        if width>=.45 and 0<height<=.022 and width/height>=25 and (y1<=.1 or y0>=.9):
            selected.append(b)
    return selected


def mark_tiled_margins(folder, blocks):
    if not (Path(folder)/'source.pdf').is_file():return []
    try:return _mark_tiled_margins(folder,blocks)
    except InterruptedError:raise
    except Exception:
        # A decoration optimization must never block analysis or guess that
        # unreadable source content is empty. Unsupported PDFs keep all blocks.
        return []


def _mark_tiled_margins(folder, blocks):
    folder=Path(folder)
    items=candidates(blocks)
    if len({b['page']for b in items})<3:return []
    import pdfplumber
    from pdf_pipeline import check_cancel
    signatures={};resources={}
    with pdfplumber.open(Path(folder)/'source.pdf')as pdf:
        grouped=collections.defaultdict(list)
        for block in items:grouped[block['page']].append(block)
        for number,selected in grouped.items():
            check_cancel(folder)
            page=pdf.pages[number-1]
            for block in selected:
                box=block['bbox'];tiles=[];placements=[];bad=False
                for image in page.images:
                    rect=[image['x0']/page.width,image['top']/page.height,
                          image['x1']/page.width,image['bottom']/page.height]
                    if min(rect[2],box[2])<=max(rect[0],box[0]) or min(rect[3],box[3])<=max(rect[1],box[1]):continue
                    size=image.get('srcsize',())
                    if (len(size)!=2 or not all(0<n<=32 for n in size)
                            or rect[0]<box[0]-.0001 or rect[1]<box[1]-.0001
                            or rect[2]>box[2]+.0001 or rect[3]>box[3]+.0001):bad=True;break
                    stream=image['stream'];key=getattr(stream,'objid',id(stream))
                    if key not in resources:resources[key]=hashlib.sha256(stream.get_data()).hexdigest()
                    tiles.append(resources[key])
                    placements.append((rect,resources[key]))
                if bad or len(tiles)<8 or len(set(tiles))>2:continue
                area=(box[2]-box[0])*(box[3]-box[1])
                painted=sum((r[2]-r[0])*(r[3]-r[1])for r,_ in placements)
                # Sparse tiny chart marks or a changing tile order are not a
                # background band, even if their tile counts happen to match.
                if not .98<=painted/area<=1.02:continue
                if any(box[0]<c['x1']/page.width and c['x0']/page.width<box[2]
                       and box[1]<c['bottom']/page.height and c['top']/page.height<box[3]
                       for c in page.chars):continue
                # The motif may have different ink/compression on each page.
                # Prove repetition of the geometry/tile arrangement across
                # pages, and of at most two tiny bitmaps WITHIN each strip.
                # A paragraph raster or a table of different cells cannot pass.
                motifs={};arrangement=[]
                for rect,motif in sorted(placements,key=lambda p:(p[0][1],p[0][0])):
                    rank=motifs.setdefault(motif,len(motifs))
                    arrangement.append((tuple(round(n,5)for n in rect),rank))
                signature=(tuple(round(n,3)for n in box),tuple(arrangement))
                signatures[block['id']]=(signature,number)
            page.close()
    pages=collections.defaultdict(set)
    for signature,number in signatures.values():pages[signature].add(number)
    proved=[]
    for b in items:
        value=signatures.get(b['id'])
        if value and len(pages[value[0]])>=3:
            # planRole is already an explicit partition annotation. Never
            # change extractor-owned localRole: that would invalidate paid
            # plans against the next independent extraction and force a replan.
            b['planRole']='decoration'
            proved.append(b['id'])
    return proved
