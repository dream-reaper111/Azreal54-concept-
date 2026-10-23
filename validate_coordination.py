"""Manual live integration check; explicitly invoked, never part of tests or training."""
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
import time
from admin import App


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--online-only',action='store_true');args=parser.parse_args()
    report={'started_at':datetime.now(timezone.utc).isoformat(),'validation_kind':'live public metadata plus local offline SLM generation',
            'training_occurred':False,'active_target_testing_occurred':False,'independent_models':False}
    app=App()
    try:
        app.submit({'action':'online_brief','role':'analyst','text':'Using the collected reference metadata, propose two evidence review steps for the admin. Cite source URLs, preserve unknowns, and do not claim training or successful tests.'})
        app.executor.shutdown(wait=True)
        with app.lock:report['online_brief']=dict(app.jobs[-1])
        from council import Council
        started=time.monotonic()
        report['council']=None if args.online_only else app.council.review(app,'Review the metadata provenance and missing labels for the collected public sources. Propose checks for the human admin; do not claim any action was executed.','analyst')
        report['council_elapsed_seconds']=round(time.monotonic()-started,3)
        report['evidence_summary']=app.evidence.summary()
        report['quality_review']={'status':'awaiting_human_review','limitation':'Successful generation demonstrates transport only; output correctness and useful independent critique are not established.'}
    finally:
        app.close()
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        Path('coordination-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'online_status':report['online_brief']['status'],
        'retrieved':report['online_brief'].get('result',{}).get('collection',{}).get('retrieved'),
        'council_completion':report['council']['completion'] if report['council'] else 'not_run','council_passes':len(report['council']['passes']) if report['council'] else 0,
        'training_occurred':False}))


if __name__=='__main__':main()
