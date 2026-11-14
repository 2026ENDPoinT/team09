"""Publish an independently generated roadmap alongside live teaching units."""
import copy
import threading
from pdf_pipeline import write_json, read_json_cache


class ParallelOverview:
    def __init__(self, initial, path, *, emit, metadata):
        self.lock=threading.RLock()
        self.value=copy.deepcopy(initial)
        self.path=path
        self.emit,self.metadata=emit,metadata

    def start(self, executor, generate):
        def work():
            value=generate()
            with self.lock:
                self.value=copy.deepcopy(value)
                partial=read_json_cache(self.path)
                if isinstance(partial,dict):
                    partial['overview']=copy.deepcopy(value)
                    write_json(self.path,partial)
                    self.emit('summary_overview_ready',path=str(self.path),**self.metadata)
            return value
        self.future=executor.submit(work)

    def publish(self, partial, export):
        with self.lock:
            partial['overview']=copy.deepcopy(self.value)
            write_json(self.path,partial)
            export(partial)

    def result(self):
        return self.future.result()
