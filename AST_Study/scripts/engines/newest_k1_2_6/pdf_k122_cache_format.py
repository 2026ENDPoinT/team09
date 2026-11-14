"""Stable source-reference schema; exact source constraints remain local.

Keep content/prompt/semantic guard requirements unchanged. The wire may name a
fixed alias pool, but restored replies are validated against the original exact
schema before canonical IDs are decoded. Unused/duplicate/missing IDs fail closed.
"""
import copy

VERSION='k122-stable-source-format-v1'

def encode(original):
    result=copy.deepcopy(original);root=result['json_schema']['schema']
    ids=root['$defs']['studySourceId']['enum']
    n=1<<(max(32,len(ids))-1).bit_length()
    def alias(index):
        word='';index+=1
        while index:index,digit=divmod(index-1,26);word=chr(97+digit)+word
        return word
    root['$defs']['studySourceId']['enum']=[alias(i)for i in range(n)]
    def visit(node):
        if not isinstance(node,dict):return
        props=node.get('properties',{})
        if 'blockIds'in props:props['blockIds'].pop('maxItems',None)
        for key in ('excludedBlocks','sourceCoverage'):
            if key in props:
                props[key].pop('maxItems',None);props[key].pop('minItems',None)
        for value in node.values():
            if isinstance(value,dict):visit(value)
            elif isinstance(value,list):
                for item in value:visit(item)
    visit(root)
    return result
