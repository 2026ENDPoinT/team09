"""Bound bookkeeping references; never shorten learner prose, math, or tables."""
import copy
from pdf_study_stream import PreviewJson


def bounded_schema(schema):
    """Every reference list is a set drawn from this unit's finite sources.

    Keep the original schema/cache identity outside this wire-only copy. Detach
    shared array nodes so a source bound cannot leak into table rows or text.
    """
    root=copy.deepcopy(schema)
    def resolve(node):
        seen=set()
        while isinstance(node,dict)and '$ref'in node:
            ref=node['$ref']
            if ref in seen or not isinstance(ref,str)or not ref.startswith('#/'):return {}
            seen.add(ref);node=root
            try:
                for key in ref[2:].split('/'):node=node[key.replace('~1','/').replace('~0','~')]
            except (KeyError,TypeError):return {}
        return node if isinstance(node,dict)else{}
    def limit(array,record=False):
        array=copy.deepcopy(array)
        item=resolve(array.get('items',{}))
        if record:item=resolve(item.get('properties',{}).get('blockId',{}))
        ids=item.get('enum')
        if isinstance(ids,list)and ids and all(isinstance(x,str)for x in ids):
            maximum=len(set(ids));array['maxItems']=min(array.get('maxItems',maximum),maximum)
        return array
    def walk(node):
        if isinstance(node,dict):
            properties=node.get('properties',{})
            if isinstance(properties,dict):
                for name in ('blockIds','excludedBlocks','uncertainBlocks'):
                    if isinstance(properties.get(name),dict):properties[name]=limit(properties[name],name!='blockIds')
            for child in list(node.values()):walk(child)
        elif isinstance(node,list):
            for child in node:walk(child)
    walk(root);return root


class ReferenceGuard(PreviewJson):
    """Recognize a repeated metadata-ID loop while JSON is still arriving."""
    def __init__(self):
        super().__init__();self.reason=None;self.arrays={}
    def _wanted(self,path):
        return len(path)>=2 and path[-2]=='blockIds'and type(path[-1])is int
    def _string(self,char):
        path=self.path;capturing=self.capture and not self.key
        super()._string(char)
        if capturing and self.mode is None and path in self.complete:
            value=self.values.pop(path);self.complete.discard(path)
            counts=self.arrays.setdefault(path[:-1],{})
            counts[value]=counts.get(value,0)+1
            if counts[value]>=3:
                self.reason='repeated_source_reference';raise ValueError('Repeated source-reference loop')
