"""Read-only comparison of saved strategies; never imports a Provider or calls an API."""
import argparse
import json
from pathlib import Path


def load(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def describe(result):
    if not result:
        return {'available': False}
    usage = result.get('generationUsage') or result.get('runUsage')
    return {'available': True, 'model': result.get('model'), 'promptVersion': result.get('promptVersion'),
            'sourceFingerprint': result.get('sourceFingerprint'), 'sections': len(result.get('sections', [])),
            'concepts': len(result.get('concepts', [])), 'coverageComplete': result.get('coverageComplete'),
            'coverageCounts': result.get('coverageCounts'), 'metrics': result.get('metrics'),
            'usage': usage, 'usageRecorded': usage is not None}


def compare(folder, scope='document', page=0):
    if scope=='document':page=0
    elif page<1:raise ValueError('page must be positive for page/section scope')
    elif scope=='section':page=(page-1)//5*5+1
    name=f'latest-{scope}-{page}.json'
    old=load(folder/'generated'/name)
    new=load(folder/'generated/semantic'/name)
    return {'documentId': folder.name, 'scope': scope, 'page': page,
            'legacy': describe(old), 'semantic': describe(new),
            'sameSourceAndModel': bool(old and new and old.get('sourceFingerprint')==new.get('sourceFingerprint') and old.get('model')==new.get('model')),
            'costComparisonNote': '기존 판독·응답 캐시 재사용과 실패·재시도 비용을 포함한 동일 조건 실행만 절감률로 비교할 수 있어요. 비용 기록이 없으면 0으로 취급하지 않아요.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--scope',choices=['document','page','section'],default='document')
    parser.add_argument('--page',type=int,default=0)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    text=json.dumps(compare(args.folder,args.scope,args.page),ensure_ascii=False,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text,encoding='utf-8')
    else:print(text)
