"""Versioned study-answer projection. No semantic review, repair, or network calls."""
import copy
import hashlib
import json

VERSION = 'study-answer-v1'
OPTION_IDS = ('O01', 'O02', 'O03', 'O04')


def scoped_body_schema(body, kind):
    result = copy.deepcopy(body)
    if kind == 'ox':
        result['properties']['answer'] = {'type':'string','enum':['O','X']}
        return result
    if kind not in ('mcq', 'essay'):
        return result
    props = result['properties']
    for key in ('answer', 'keyPoints', 'distractors'):
        props.pop(key, None)
    text = {'type': 'string'}
    if kind == 'essay':
        props.update(exampleAnswer=text, commonRequirements={'type':'array','items':text,'minItems':1},
            conditionalRequirements={'type':'array','items':{'type':'object','properties':{
                'condition':text,'requirement':text},'required':['condition','requirement'],'additionalProperties':False}},
            acceptedAliases={'type':'array','items':text})
    else:
        props.update(options={'type':'array','minItems':4,'maxItems':4,'items':{'type':'object',
            'properties':{'optionId':{'type':'string','enum':list(OPTION_IDS)},'text':text,'explanation':text},
            'required':['optionId','text','explanation'],'additionalProperties':False}},
            correctOptionId={'type':'string','enum':list(OPTION_IDS)})
    result['required'] = list(props)
    return result


def project_answers(raw):
    result = copy.deepcopy(raw)
    if not isinstance(result, dict) or not isinstance(result.get('questions'), list):
        return result
    for q in result['questions']:
        if not isinstance(q, dict):
            continue
        is_essay = q.get('type') == 'essay' and 'exampleAnswer' in q
        is_mcq = q.get('type') == 'mcq' and 'correctOptionId' in q
        if not (is_essay or is_mcq):
            continue
        original = copy.deepcopy(q)
        q['answerContractVersion'] = VERSION
        q['rawAnswerContract'] = original
        q['answerContractHash'] = hashlib.sha256(json.dumps(original,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        q.setdefault('qualityStatus', 'unreviewed')
        try:
            if is_essay:
                points = q['commonRequirements']; conditions = q['conditionalRequirements']
                if (not isinstance(q['exampleAnswer'],str) or not q['exampleAnswer'].strip()
                    or not isinstance(points,list) or not points or any(not isinstance(p,str) or not p.strip() for p in points)
                    or not isinstance(conditions,list) or any(not isinstance(c,dict) or
                        any(not isinstance(c.get(k),str) or not c[k].strip() for k in ('condition','requirement')) for c in conditions)):
                    raise ValueError('예시·공통·조건부 답안 계약을 확인하지 못했어요.')
                q['answer'] = q['exampleAnswer']
                q['keyPoints'] = list(points) + ['조건: '+c['condition']+' → 요구: '+c['requirement'] for c in conditions]
                q['keyPoints'] += ['허용 대안(필수 아님): '+a for a in q.get('acceptedAliases',[]) if isinstance(a,str) and a.strip()]
                q['options'] = []
            else:
                options = q['options']
                if (not isinstance(options,list) or len(options)!=4 or any(not isinstance(o,dict) for o in options)
                    or {o.get('optionId') for o in options} != set(OPTION_IDS)
                    or q['correctOptionId'] not in OPTION_IDS
                    or any(not isinstance(o.get(k),str) or not o[k].strip() for o in options for k in ('text','explanation'))):
                    raise ValueError('불변 보기 ID와 정답 연결을 확인하지 못했어요.')
                # Display letters are stable aliases, never used as source option identity.
                mapping = dict(zip(OPTION_IDS,'ABCD'))
                q['options'] = [{'id':mapping[o['optionId']], **o} for o in options]
                q['answer'] = mapping[q['correctOptionId']]
                q['keyPoints'] = []
        except (KeyError, TypeError, ValueError) as error:
            q['answerContractError'] = str(error)
            q['warnings'] = list(q.get('warnings',[])) + [str(error)]
    return result


def preserve_metadata(source, destination):
    for key in ('answerContractVersion','answerContractHash','rawAnswerContract','exampleAnswer',
                'commonRequirements','conditionalRequirements','acceptedAliases','correctOptionId',
                'rawGenerationQuestion','answerContractError','qualityStatus','profile','profileStatus','additionalJudgment','profileEvidenceSourceIds'):
        if key in source:
            destination[key] = copy.deepcopy(source[key])
    return destination
