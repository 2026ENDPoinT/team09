"""Transient learner-only JSON previews; never canonical teaching or paid cache.

The incremental tokenizer sees string paths, not brace/regex guesses. It handles
split JSON escapes and Unicode pairs while ignoring source setup, uncertainty,
easy explanations, evidence and unrelated/nested fields. The normal complete
response validator remains authoritative and replaces every preview.
"""
from __future__ import annotations
import json
import threading
import time


class PreviewJson:
    """Incrementally collect only selected learner strings by exact JSON path."""
    def __init__(self, prefixes=((),)):
        self.prefixes=set(prefixes);self.frames=[];self.root='value';self.mode=None
        self.path=None;self.key=False;self.capture=False;self.buffer=[]
        self.escape=False;self.unicode=None;self.high=None;self.primitive=''
        self.invalid=False;self.values={};self.complete=set()

    def _wanted(self,path):
        for prefix in self.prefixes:
            if path[:len(prefix)]!=prefix:continue
            tail=path[len(prefix):]
            if len(tail)==3 and tail[0]=='concepts' and type(tail[1])is int and tail[2]=='title':return True
            if (len(tail)==5 and tail[0]=='concepts' and type(tail[1])is int
                    and tail[2]=='segments' and type(tail[3])is int and tail[4]in ('kind','text')):return True
        return False

    def _value_path(self):
        if not self.frames:
            if self.root!='value':raise ValueError('Trailing JSON data')
            return ()
        frame=self.frames[-1]
        if frame['state']!='value':raise ValueError('Expected JSON separator')
        return frame['path']+(frame['key'] if frame['kind']=='object'else frame['index'],)

    def _finish(self):
        if self.frames:
            frame=self.frames[-1];frame['state']='comma'
            if frame['kind']=='array':frame['index']+=1
        else:self.root='done'

    def _decoded(self,char):
        point=ord(char)
        if self.high is not None:
            if not 0xDC00<=point<=0xDFFF:raise ValueError('Unpaired high surrogate')
            char=chr(0x10000+((self.high-0xD800)<<10)+(point-0xDC00));self.high=None
        elif 0xD800<=point<=0xDBFF:self.high=point;return
        elif 0xDC00<=point<=0xDFFF:raise ValueError('Unpaired low surrogate')
        if self.key or self.capture:self.buffer.append(char)

    def _string(self,char):
        if self.unicode is not None:
            if char not in '0123456789abcdefABCDEF':raise ValueError('Invalid JSON Unicode escape')
            self.unicode+=char
            if len(self.unicode)==4:
                value=self.unicode;self.unicode=None;self._decoded(chr(int(value,16)))
            return
        if self.escape:
            self.escape=False
            if char=='u':self.unicode='';return
            escapes={'"':'"','\\':'\\','/':'/','b':'\b','f':'\f','n':'\n','r':'\r','t':'\t'}
            if char not in escapes:raise ValueError('Invalid JSON escape')
            self._decoded(escapes[char]);return
        if char=='\\':self.escape=True;return
        if char=='"':
            if self.high is not None:raise ValueError('Unpaired high surrogate')
            value=''.join(self.buffer)
            if self.key:
                frame=self.frames[-1]
                if value in frame['seen']:raise ValueError('Duplicate JSON key')
                frame['seen'].add(value);frame['key']=value;frame['state']='colon'
            else:
                if self.capture:self.values[self.path]=value;self.complete.add(self.path)
                self._finish()
            self.mode=None;return
        if ord(char)<32:raise ValueError('Unescaped JSON control')
        self._decoded(char)

    def feed(self,delta):
        if self.invalid:return False
        try:
            for char in delta:
                if self.mode=='string':self._string(char);continue
                if self.mode=='primitive':
                    if char not in ' \t\r\n,]}':self.primitive+=char;continue
                    value=json.loads(self.primitive)
                    if isinstance(value,(dict,list,str)):raise ValueError('Invalid primitive')
                    self.mode=None;self._finish()
                if char.isspace():continue
                frame=self.frames[-1]if self.frames else None
                if char in '}]':
                    if frame is None or frame['kind']!=('object'if char=='}'else'array'):raise ValueError('Unbalanced JSON')
                    if frame['state']not in ('comma','key_or_end','value_or_end'):raise ValueError('Incomplete JSON value')
                    self.frames.pop();self._finish();continue
                if frame is not None and frame['state']=='colon':
                    if char!=':':raise ValueError('Expected colon')
                    frame['state']='value';continue
                if frame is not None and frame['state']=='comma':
                    if char!=',':raise ValueError('Expected comma')
                    frame['state']='key'if frame['kind']=='object'else'value';continue
                if frame is not None and frame['state']=='value_or_end':frame['state']='value'
                if char=='"':
                    self.key=frame is not None and frame['kind']=='object'and frame['state']in ('key','key_or_end')
                    self.path=None if self.key else self._value_path()
                    self.capture=not self.key and self._wanted(self.path)
                    self.buffer=[];self.high=None;self.escape=False;self.unicode=None;self.mode='string';continue
                if frame is not None and frame['state']=='value_or_end':frame['state']='value'
                path=self._value_path()
                if char in '{[':
                    self.frames.append({'kind':'object'if char=='{'else'array','path':path,
                        'state':'key_or_end'if char=='{'else'value_or_end','key':None,'index':0,'seen':set()})
                else:self.mode='primitive';self.primitive=char
            if self.mode=='string'and self.capture:self.values[self.path]=''.join(self.buffer)
            return True
        except (ValueError,TypeError,UnicodeError):
            self.invalid=True;return False

    def learner(self,prefix=()):
        values=self.values;concepts={}
        for path,text in values.items():
            if path[:len(prefix)]!=prefix:continue
            tail=path[len(prefix):]
            if len(tail)>=3 and tail[0]=='concepts':concepts.setdefault(tail[1],{})[tail[2:]]=text
        parts=[]
        for concept_index,fields in sorted(concepts.items()):
            title=fields.get(('title',),'');segments=[]
            for key,text in sorted(fields.items(),key=lambda row:str(row[0])):
                if len(key)!=3 or key[0]!='segments'or key[2]!='text':continue
                kind_path=prefix+('concepts',concept_index,'segments',key[1],'kind')
                if kind_path in self.complete and values.get(kind_path)in ('definition','explanation') and text:
                    segments.append((key[1],text))
            body='\n\n'.join(text for _,text in sorted(segments))
            if body:parts.append({'title':title,'body':body})
        return parts


class StudyPreview:
    """A request-local decoder; callback receives a job index and learner-only body."""
    def __init__(self, units, publish, *, clock=time.monotonic, interval=.08):
        self.units=units;self.publish=publish;self.clock=clock;self.interval=interval;self.last_publish=None
        self.parser=PreviewJson(tuple(prefix for prefix,_ in units))
        self.last={}
    def reset(self):
        # An explicitly budgeted alternate starts a NEW JSON document. Never
        # append its prefix to the lost stream or duplicate its learner text.
        self.parser=PreviewJson(tuple(prefix for prefix,_ in self.units))
        self.last={};self.last_publish=None
    def feed(self,delta):
        if not self.parser.feed(delta):return
        now=self.clock()
        if self.last and self.last_publish is not None and now-self.last_publish<self.interval:return
        self.flush()
    def flush(self):
        if self.parser.invalid:return
        self.last_publish=self.clock()
        for prefix,index in self.units:
            parts=self.parser.learner(prefix)
            body='\n\n'.join(('### '+p['title']+'\n\n'if p['title'] else'')+p['body']for p in parts)
            if body and body!=self.last.get(index):
                self.last[index]=body;self.publish(index,body)


class PreviewPublication:
    """Thread-safe preview order and cadence, independent of generation scheduling."""
    def __init__(self,jobs,front,terminal,*,scope,page,strategy,emit,clock=time.monotonic,interval=.1,started=None):
        self.jobs=jobs;self.front=list(front);self.terminal=set(terminal)
        self.scope=scope;self.page=page;self.strategy=strategy;self.emit=emit
        self.clock=clock;self.interval=interval;self.lock=threading.RLock()
        self.started=clock()if started is None else started;self.first_visible_seconds=None
        self.pending={};self.last={};self.sequence={};self.visible=set();self.authoritative=set()
    def _event(self,index,**values):
        sequence=self.sequence.get(index,0)+1;self.sequence[index]=sequence
        try:
            self.emit('summary_unit_delta',unit=index+1,total=len(self.jobs),scope=self.scope,
                selectionPage=self.page,strategy=self.strategy,preview=True,sequence=sequence,**values)
            return True
        except InterruptedError:raise
        except Exception:return False  # Display-only failure never changes paid completion.
    def _send(self,index,force=False):
        body=self.pending.get(index)
        if not body or index in self.authoritative:return
        now=self.clock();previous=self.last.get(index)
        if previous and not force and now-previous[0]<self.interval:return
        if previous and previous[1]==body:return
        job=self.jobs[index];pages=sorted({b['page']for b in job['blocks']})
        # Group titles are provisional. Once a real learner heading arrives,
        # show it with its own body rather than a stale grouping hint.
        title=body.split('\n',1)[0][4:].strip()if body.startswith('### ')else job['title']
        if not self._event(index,summary={'title':title or job['title'],'body':body,'visualPages':pages[:1]}):return
        if self.first_visible_seconds is None:self.first_visible_seconds=round(now-self.started,3)
        self.last[index]=(now,body);self.visible.add(index)
    def _flush(self,force=False):
        for index in self.front:
            self._send(index,force)
            if index not in self.visible and index not in self.terminal:return
        for index in sorted(self.pending):
            if index not in self.front:self._send(index,force)
    def update(self,index,body):
        with self.lock:
            if index in self.authoritative or index in self.terminal:return
            self.pending[index]=body;self._flush()
    def settle(self,index,accepted):
        with self.lock:
            # Flush this unit's last decoded text before its canonical event.
            self._flush(force=True)
            self.terminal.add(index);self.authoritative.add(index);self.pending.pop(index,None)
            if not accepted and index in self.visible:self._event(index,discard=True)
            self._flush(force=True)
