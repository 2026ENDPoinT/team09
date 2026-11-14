"""Deterministic, offline request-latency replay. No API, PDF or UI operations."""
from collections import deque
import heapq
import math


def replay(tasks, workers, *, pipeline=True, start=0.0):
    """Replay fixed preparation/service times in supplied submission order.

    A worker remains occupied while waiting for the single crop preparer, while
    preparing its request, and while waiting for its response. This models the
    current combined worker pool; it does not assume lower concurrency changes
    server or upload time. UI persistence lag does not occupy a network worker.
    """
    if not isinstance(workers,int) or workers<1:
        raise ValueError('workers must be a positive integer')
    for task in tasks:
        for key in ('prepareSeconds','serviceSeconds','uiLagSeconds'):
            value=task.get(key,0)
            if not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                raise ValueError('durations must be finite and nonnegative')
    if not tasks:
        return {'lastResponseSeconds':start,'lastUiSeconds':start,
                'firstLearnerUiSeconds':None,'requests':[]}
    completed=[]
    if not pipeline:
        ready=start+sum(task.get('prepareSeconds',0) for task in tasks)
        available=[(ready,index) for index in range(workers)];heapq.heapify(available)
        for task in tasks:
            send,worker=heapq.heappop(available)
            end=send+task['serviceSeconds'];heapq.heappush(available,(end,worker))
            completed.append({'id':task['id'],'sendSeconds':send,'responseSeconds':end,
                              'uiSeconds':end+task.get('uiLagSeconds',0),
                              'hasLearnerBody':bool(task.get('hasLearnerBody'))})
    else:
        pending=iter(tasks);preparing=deque();events=[];serial=0;crop_busy=False
        for _ in range(min(workers,len(tasks))):preparing.append(next(pending))
        def prepare(now):
            nonlocal crop_busy,serial
            if crop_busy or not preparing:return
            task=preparing.popleft();crop_busy=True;serial+=1
            heapq.heappush(events,(now+task.get('prepareSeconds',0),1,serial,'prepared',task))
        prepare(start)
        while events:
            now,_,_,kind,task=heapq.heappop(events)
            if kind=='prepared':
                crop_busy=False;serial+=1
                sent={**task,'_send':now}
                heapq.heappush(events,(now+task['serviceSeconds'],0,serial,'response',sent))
            else:
                completed.append({'id':task['id'],'sendSeconds':task['_send'],
                    'responseSeconds':now,'uiSeconds':now+task.get('uiLagSeconds',0),
                    'hasLearnerBody':bool(task.get('hasLearnerBody'))})
                following=next(pending,None)
                if following is not None:preparing.append(following)
            prepare(now)
    return {'lastResponseSeconds':max(row['responseSeconds'] for row in completed),
            'lastUiSeconds':max(row['uiSeconds'] for row in completed),
            'firstLearnerUiSeconds':min((row['uiSeconds'] for row in completed
                                        if row['hasLearnerBody']),default=None),
            'requests':sorted(completed,key=lambda row:(row['sendSeconds'],row['id']))}
