"""Opt-in CPU-only composite graph benchmark; no models, brokers or viewer sockets.

Run from user-backend: python benchmarks/composite_perf.py --formulas 10000 --events 100
Selective changes one team metric; shared-denominator deliberately fans out to every metric.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.models.events import Event
from backend.models.rules import Rule
from backend.services.filter_engine import FilterEngine


def run(size, events, shared_denominator):
    engine = FilterEngine()
    started = time.perf_counter()
    for index in range(size):
        scope = [{'field':'event_type','op':'eq','value':'pass'}]
        team = {'field':'team_id','op':'eq','value':f'team-{index}'}
        success = Rule(match_id='benchmark',predicates=scope+[team,{'field':'outcome','op':'eq','value':'success'}])
        denominator = Rule(match_id='benchmark',predicates=scope+([] if shared_denominator else [team])+
                           [{'field':'outcome','op':'in','value':['success','failure']}])
        engine.register(Rule(match_id='benchmark',operation='percentage',inputs=(success,denominator)))
    register_seconds = time.perf_counter()-started
    timings, evaluations = [], []
    for index in range(events):
        event = Event(event_id=str(index),match_id='benchmark',event_type='pass',team_id='team-0',
                      match_time_seconds=index,outcome='success' if index%2 else 'failure')
        started=time.perf_counter()
        engine.ingest(event)
        timings.append(time.perf_counter()-started)
        evaluations.append(engine.last_formula_evaluation_count)
    timings.sort()
    return {'profile':'shared_denominator' if shared_denominator else 'selective',
            'formulas':size,'leaves':engine.leaf_count,'events':events,'registration_seconds':register_seconds,
            'median_event_ms':timings[len(timings)//2]*1000,
            'p95_event_ms':timings[min(len(timings)-1,int(len(timings)*.95))]*1000,
            'max_formulas_evaluated_per_event':max(evaluations)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--formulas',type=int,default=10000)
    parser.add_argument('--events',type=int,default=100)
    options=parser.parse_args()
    if not 1<=options.formulas<=100000 or not 1<=options.events<=1000:
        parser.error('Use 1–100000 formulas and 1–1000 events; this is a bounded local benchmark.')
    for broad in (False,True):
        print(json.dumps(run(options.formulas,options.events,broad)),flush=True)
