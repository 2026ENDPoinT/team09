"""Recognize a complete schema-valid JSON frame without clipping learner strings."""
import json
from pdf_study_batch_transport import _validate, BatchTransportError

OUTSIDE_WHITESPACE_LIMIT=256


def _pairs(items):
    value={}
    for key,item in items:
        if key in value:raise ValueError('Duplicate JSON field')
        value[key]=item
    return value


class JsonBoundary:
    def __init__(self,schema):
        self.schema=schema;self.chars=[];self.stack=[];self.quoted=False;self.escaped=False
        self.started=False;self.finished=False;self.invalid=False;self.value=None;self.whitespace=0
        self.tail_chars=0;self.end=0
        from pdf_source_reference_guard import ReferenceGuard
        self.references=ReferenceGuard()

    def feed(self,delta):
        self.references.feed(delta)
        if self.references.reason:return self.references.reason
        if self.invalid:return None
        for char in delta:
            if self.finished:
                self.tail_chars+=1
                if not char.isspace():return 'non_json_after_complete'
                if self.tail_chars>OUTSIDE_WHITESPACE_LIMIT:return 'padding_after_complete'
                continue
            self.chars.append(char)
            if self.quoted:
                if self.escaped:self.escaped=False
                elif char=='\\':self.escaped=True
                elif char=='"':self.quoted=False
                continue
            if char.isspace():
                self.whitespace+=1
                if self.whitespace>OUTSIDE_WHITESPACE_LIMIT:return 'padding_before_complete'
                continue
            self.whitespace=0
            if not self.started:
                if char!='{':self.invalid=True;return None
                self.started=True
            if char=='"':self.quoted=True
            elif char in '{[':self.stack.append(char)
            elif char in '}]':
                if not self.stack or self.stack.pop()!=('{' if char=='}'else '['):self.invalid=True;return None
                if not self.stack:
                    try:
                        value=json.loads(''.join(self.chars),object_pairs_hook=_pairs,
                            parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Non-finite number')))
                        _validate(value,self.schema,self.schema)
                    except (ValueError,TypeError,BatchTransportError):self.invalid=True;return 'invalid_complete_json'
                    self.finished=True;self.value=value;self.end=len(self.chars)
        return None
