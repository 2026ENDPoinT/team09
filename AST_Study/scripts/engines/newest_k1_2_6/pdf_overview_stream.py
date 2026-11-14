"""Transient flow previews; parse only the root learner body, never source IDs."""
from pdf_study_stream import PreviewJson

class BodyJson(PreviewJson):
    def _wanted(self,path):return path==('body',)

class OverviewPreview:
    def __init__(self,publish):self.publish=publish;self.parser=BodyJson();self.last=''
    def feed(self,delta):
        if not self.parser.feed(delta):return
        body=self.parser.values.get(('body',),'')
        if body and body!=self.last:self.last=body;self.publish(body)
    def reset(self):
        self.parser=BodyJson();self.last='';self.publish('',discard=True)
