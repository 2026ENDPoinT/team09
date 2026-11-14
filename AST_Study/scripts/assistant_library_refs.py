"""Short, turn-local wire references; native capabilities always use exact IDs."""
import copy
import json
import re

_OPAQUE=re.compile(r'(?:[0-9a-f]{64}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\Z')
_IDS={'id','parentId','destinationId','sourceFolderId','sourceParentId','currentFolderId','rootId','proposalId','clarificationId'}


class LibraryRefs:
    def __init__(self):
        self.forward={};self.backward={};self.counts={'LI':0,'LR':0}

    def _value(self,value,key,encode):
        if isinstance(value,dict):return {k:self._value(v,k,encode) for k,v in value.items()}
        if isinstance(value,list):return [self._value(v,'id' if key=='ancestorIds' else key,encode) for v in value]
        if not isinstance(value,str) or key not in _IDS|{'revision','expectedRevision'}:return value
        if not encode:return self.backward.get(value,value)
        if not _OPAQUE.fullmatch(value):return value
        if value not in self.forward:
            prefix='LR' if key in ('revision','expectedRevision') else 'LI'
            self.counts[prefix]+=1;alias=prefix+str(self.counts[prefix])
            self.forward[value]=alias;self.backward[alias]=value
        return self.forward[value]

    def payload(self,payload):
        out=copy.deepcopy(payload)
        context=out.get('localContext',{})
        if isinstance(context.get('library'),dict):context['library']=self._value(context['library'],'',True)
        for row in out.get('localResults',[]):
            request=row.get('request',{})
            if request.get('tool','').startswith('library.'):
                if 'arguments' in request:request['arguments']=self._value(request['arguments'],'',True)
                if 'data' in row.get('result',{}):row['result']['data']=self._value(row['result']['data'],'',True)
        for field in ('acceptedLibraryIntent','libraryTaskPlan','libraryPlanCorrection','libraryRevisionCorrection','libraryPendingRequests','libraryCompletionReview','libraryAmbiguityReview'):
            if field in out:out[field]=self._value(out[field],'',True)
        return out

    def response(self,value):
        if not isinstance(value,dict):return value
        out=copy.deepcopy(value)
        if isinstance(out.get('libraryIntent'),dict):out['libraryIntent']=self._value(out['libraryIntent'],'',False)
        requests=out.get('localRequests',[])
        if not isinstance(requests,list):return out
        for request in requests:
            if not isinstance(request,dict) or not str(request.get('tool','')).startswith('library.'):continue
            arguments=request.get('argumentsJson')
            if not isinstance(arguments,str):continue
            try:parsed=json.loads(arguments)
            except (ValueError,TypeError):continue  # Normal envelope validation reports malformed JSON.
            request['argumentsJson']=json.dumps(self._value(parsed,'',False),ensure_ascii=False,separators=(',',':'))
        return out
