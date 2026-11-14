"""Book-level profile planning from existing evidence. No extra provider call."""
import copy

PURPOSES = {
 'concept_completion':'기본 정의·용어·핵심 특징·기본 관계·유사 개념 구별을 폭넓게 확인한다. 짧은 회상·직접 구별도 충분하며 심화나 조건 변형을 요구하지 않는다.',
 'understanding':'의미·이유·성립 조건과 조건 변화의 결과를 이해한다.',
 'practice_set':'상황에서 개념·방법·조건을 선택하고 적용·진단한다.',
 'recall':'지정된 세부 사실·대응·예외·필수 순서를 정확히 회상한다.'}


def planning_evidence(concepts, sources, char_budget=24000):
    # Complete passages only. Omission is explicit, not an invented summary.
    result=[]; included=set(); used=0
    for concept in concepts.values():
        for sid in concept['sourceIds']:
            if sid in included: continue
            source=sources[sid]
            if used+len(source['text'])>char_budget: continue
            included.add(sid); used+=len(source['text']); result.append(copy.deepcopy(source))
    return {'sources':result,'omittedSourceIds':[s for s in sources if s not in included],
            'scope':'전체 본문이 아닐 수 있다. 누락 근거로 심화 가능성을 추측하지 않는다.'}


def policy(count, theme):
    advanced=0 if theme=='concept_completion' else count//2
    return {'version':'study-profile-v2','purpose':PURPOSES[theme],
            'targetCounts':{'general':count-advanced,'advanced':advanced},
            'actualFit':'unknown','studentDifficultyMeasured':False}


def apply_profile_plan(plan, evidence, config, concepts=None):
    out=copy.deepcopy(plan); allowed={s['sourceId'] for s in evidence['sources']}
    held=[]; assigned={'general':0,'advanced':0,'unspecified':0}
    for unit in out['allocations']:
        kept=[]
        for target in unit.get('targets',[]):
            profile=target.get('profile','unspecified')
            refs=target.get('profileEvidenceSourceIds',[])
            target_allowed = allowed if concepts is None else allowed & {s for cid in target['conceptIds'] for s in concepts[cid]['sourceIds']}
            if profile not in ('general','advanced','unspecified') or (profile=='advanced' and (not isinstance(target.get('additionalJudgment'),str) or not target['additionalJudgment'].strip() or not isinstance(refs,list) or not refs or any(not isinstance(s,str) or s not in target_allowed for s in refs))):
                held.append({**target,'reason':'심화 추가 판단과 제공된 근거 연결이 부족해요.'}); continue
            target['profileStatus']='unverified' # Exists != semantically supports.
            assigned[profile]=assigned.get(profile,0)+1; kept.append(target)
        if 'targets' in unit:
            unit['targets']=kept
            unit['counts']={k:sum(t['type']==k for t in kept) for k in ('ox','mcq','word','essay')}
    out['allocations']=[u for u in out['allocations'] if 'targets' not in u or u['targets']]
    out['unallocated']+=len(held)
    out['heldTargets']=held
    out['profileAllocation']={**policy(config['totalCount'],config['theme']),'plannedCounts':assigned,
        'advancedShortfall':max(0,policy(config['totalCount'],config['theme'])['targetCounts']['advanced']-assigned['advanced']),
        'suitableCounts':{'general':None,'advanced':None},'generationQualityCertified':False}
    return out
