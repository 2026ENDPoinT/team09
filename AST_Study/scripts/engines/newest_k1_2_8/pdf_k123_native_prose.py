"""Source-preserving proof for Unicode-styled letters/digits in ordinary prose.

Only proof copies are normalized. Original source text/chars stay unchanged.
Existing graphics, code, font, glyph equality and clipping checks still apply.
Raised/small math characters and all non-alphabet compatibility changes fail.
"""
import copy,math,re,statistics,unicodedata


def normalized(text):
    for char in text:
        plain=unicodedata.normalize('NFKC',char)
        if plain!=char and not (0x1D400<=ord(char)<=0x1D7FF or 0x2460<=ord(char)<=0x2473):
            return None
    return unicodedata.normalize('NFKC',text)


def _verify(page,block,chars):
    from pdf_study_text_input import native_prose_verified
    plain=normalized(block.get('text',''))
    if not plain or not re.search('[가-힣]',plain):return False
    box=[block['bbox'][0]*page.width,block['bbox'][1]*page.height,
         block['bbox'][2]*page.width,block['bbox'][3]*page.height]
    selected=[c for c in chars if c.get('text','').strip() and
        min(box[2],c['x1'])>max(box[0],c['x0'])and min(box[3],c['bottom'])>max(box[1],c['top'])]
    ordinary=[c for c in selected if re.search('[가-힣]',c.get('text',''))]
    if not ordinary:return False
    for c in selected:
        text=c.get('text','')
        if normalized(text) is None:return False
        if unicodedata.normalize('NFKC',text)==text:continue
        nearby=[x for x in ordinary if abs(x['top']-c['top'])<max(x['size'],c['size'])*.65]
        if not nearby:return False
        size=statistics.median(x['size']for x in nearby)
        bottom=statistics.median(x['bottom']for x in nearby)
        if not(.85*size<=c['size']<=1.2*size)or abs(c['bottom']-bottom)>.23*size:return False
    copied=[{**c,'text':unicodedata.normalize('NFKC',c.get('text',''))}for c in chars]
    return native_prose_verified(page,{**block,'text':plain},copied)


def verify(page,block,chars):
    try:return _verify(page,block,chars)
    except(KeyError,TypeError,ValueError,AttributeError,IndexError):return False


def mark(blocks,folder):
    from pathlib import Path
    import pdfplumber
    from pdf_equation_font import repair_chars
    from pdf_study_text_input import VERSION
    from pdf_pipeline import write_json
    changed=[];blocks=copy.deepcopy(blocks)
    previous_page=None;chars=None
    with pdfplumber.open(Path(folder)/'source.pdf')as pdf:
        for b in blocks:
            if b.get('nativeTextProof')or b.get('localRole')or b.get('hasVisual'):continue
            if b['page']!=previous_page:
                from pdf_pipeline import check_cancel
                check_cancel(folder)
                chars=repair_chars(pdf.pages[b['page']-1].chars)[0]
                previous_page=b['page']
            page=pdf.pages[b['page']-1]
            if verify(page,b,chars):
                b['nativeTextProof']=VERSION;b['additionalNativeProof']='k123-unicode-styled-prose-v1'
                changed.append({'id':b['id'],'page':b['page'],'originalTextPreserved':True})
    write_json(Path(folder)/'native-proof-audit.json',{'changed':changed,'count':len(changed),
        'sourceTextUnchanged':True,'graphicsAndRaisedMathStillProtected':True})
    return blocks
