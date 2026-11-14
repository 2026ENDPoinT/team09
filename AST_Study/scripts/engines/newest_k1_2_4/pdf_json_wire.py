"""Remove JSON separator whitespace only, preserving prompt/cache/source values."""
import copy
import json

TASKS = {'region_groups', 'region_teaching', 'region_teaching_batch', 'lecture_flow_from_headings',
         'quiz_plan', 'quiz_questions'}


def compact_request(body, task):
    if task not in TASKS:
        return body, 0
    messages = body.get('messages', body.get('input', []))
    if len(messages) < 2:
        return body, 0
    content = messages[1].get('content')
    text = content if isinstance(content, str) else (
        content[0].get('text') if isinstance(content, list) and content else None)
    if not isinstance(text, str):
        return body, 0
    value = json.loads(text)
    if not isinstance(value, dict) or value.get('task') != task:
        return body, 0
    compact = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    saved = len(text.encode()) - len(compact.encode())
    if saved <= 0:
        return body, 0
    result = copy.deepcopy(body)
    target = result.get('messages', result.get('input'))[1]
    if isinstance(content, str):
        target['content'] = compact
    else:
        target['content'][0]['text'] = compact
    return result, saved


def label_images(body, task):
    """Put exact unit/page/source ownership beside each unchanged image.

    The canonical paid-cache identity is intentionally independent of this
    delivery metadata. No existing source/prose/pixel value is rewritten.
    """
    if task not in {'region_teaching', 'region_teaching_batch'}:return body, 0
    route='messages' if 'messages'in body else 'input'
    messages=body.get(route,[])
    if len(messages)<2:return body,0
    content=messages[1].get('content')
    if not isinstance(content,list)or not content:return body,0
    image_type='image_url'if route=='messages'else'input_image'
    images=[v for v in content[1:]if v.get('type')==image_type]
    # Already labelled input keeps its established source labels verbatim.
    if len(content)!=len(images)+1:return body,0
    payload=json.loads(content[0]['text'])
    if not images and not (task=='region_teaching_batch' and payload.get('unitEnvelopeVersion')=='k1.1.1-v1'):return body,0
    if task=='region_teaching_batch':
        order=payload.get('imageOrder',[]);units=payload.get('units',{})
    else:
        order=[{'unit':'single','cropIndex':i}for i in range(len(images))]
        units={'single':payload}
    if len(order)!=len(images):return body,0
    labels=[]
    for entry in order:
        unit=units.get(entry.get('unit'),{});crops=unit.get('crops',[]);index=entry.get('cropIndex')
        if type(index)is not int or not 0<=index<len(crops):return body,0
        crop=crops[index]
        label={'unit':entry['unit'],'cropIndex':index,'pdfPage':crop['page'],'targetBlockIds':crop['blockIds']}
        text='IMAGE OWNERSHIP '+json.dumps(label,ensure_ascii=False,separators=(',',':'))
        labels.append({'type':'text'if route=='messages'else'input_text','text':text})
    if task=='region_teaching_batch' and payload.get('unitEnvelopeVersion')=='k1.1.1-v1':
        return unit_envelopes(body,payload,images,labels,route)
    result=copy.deepcopy(body);labelled=[copy.deepcopy(content[0])]
    for label,image in zip(labels,images):labelled.extend([label,copy.deepcopy(image)])
    result[route][1]['content']=labelled
    return result,len(labels)


def unit_envelopes(body, payload, images, labels, route):
    """Opt-in K1.1.1 wire layout; unchanged unit values and image bytes."""
    units=payload['units'];order=payload['imageOrder']
    if set(e['unit'] for e in order)-set(units):
        raise ValueError('Unknown image owner in unit envelopes')
    kind='text' if route=='messages' else 'input_text'
    def text(value):return {'type':kind,'text':value}
    header={k:v for k,v in payload.items() if k not in ('units','imageOrder')}
    header['unitOrder']=list(units)
    content=[text(json.dumps(header,ensure_ascii=False,separators=(',',':')))]
    for name,unit in units.items():
        content.append(text('BEGIN UNIT '+name+'\n'+json.dumps(
            {'unit':name,'source':unit},ensure_ascii=False,separators=(',',':'))))
        for entry,label,image in zip(order,labels,images):
            if entry['unit']==name:content.extend([label,copy.deepcopy(image)])
        content.append(text('END UNIT '+name))
    result=copy.deepcopy(body);result[route][1]['content']=content
    return result,len(labels)
