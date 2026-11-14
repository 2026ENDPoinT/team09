"""Current-run request timings, attributed without dividing shared batch latency."""
import math


def unit_timings(jobs, done, failures, ledger, *, local_units=()):
    entries=ledger.get('requests',[]) if isinstance(ledger,dict) else []
    failed={f.get('unitId') for f in failures}
    rows=[]
    for index,job in enumerate(jobs):
        requests=[r for r in entries if r.get('kind')=='region_study'
                  and job['id'] in r.get('unitIds',[])]
        # Hedged attempts overlap. Report time until the usable winner, not the
        # sum of two simultaneous requests (nor a late loser's cleanup time).
        durations=[];hedges=set()
        for request in requests:
            group=request.get('hedgeGroup')
            if group and group in hedges:continue
            if group:
                hedges.add(group)
                winner=next((r for r in requests if r.get('hedgeGroup')==group and r.get('hedgeWinner')is True),{})
                durations.append(winner.get('hedgeResultSeconds'))
            else:durations.append(request.get('latencySeconds'))
        measured=[value for value in durations if type(value)in (int,float)
                  and math.isfinite(value)and value>=0]
        complete=index in done
        status=('completed' if requests else 'reused') if complete else ('failed' if job['id'] in failed else 'pending')
        if index in local_units and complete and not requests:status='local'
        row={'unitId':job['id'],'index':index+1,'title':job['title'],
             'semanticIndex':job.get('topicIndex',index)+1,
             'pages':sorted({b['page'] for b in job['blocks']}),'status':status,
             'requestCount':len(requests),
             'sharedRequest':any(len(r.get('unitIds',[]))>1 for r in requests),
             'requestIds':[r['requestId'] for r in requests if r.get('requestId')]}
        # Missing measurements are unknown, never a fabricated zero duration.
        if measured and len(measured)==len(durations):row['requestSeconds']=round(sum(measured),3)
        rows.append(row)
    return rows
