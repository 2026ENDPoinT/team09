"""Explicit $2 aggregate live QA authorization; short PDFs only, isolated results."""
import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import shutil
import time
import traceback

from pdf_ai import Provider, run_usage
from pdf_pipeline import write_json
import pdf_semantic as semantic

ROOT = Path('build/pdf-semantic-live-20261007')
CAP = 2.0
CASES = {'six-cold': ('3b0f0b8b2708', False), 'rp-reuse': ('d0042fffa2b4', True)}
CASES.update({'six-topics-v2': ('3b0f0b8b2708', False), 'rp-topics-v2': ('d0042fffa2b4', True)})
READING_BASELINES = {'six-topics-v2': 'six-cold', 'rp-topics-v2': 'rp-reuse'}


def consumed():
    return sum(e.get('estimatedUsd', e.get('reservedUsd', 0))
               for p in ROOT.glob('*/usage/*.json')
               for e in json.loads(p.read_text())['requests'])


def source_hashes(folder):
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', choices=CASES)
    parser.add_argument('--retry-missing-responses', action='store_true',
                        help='Retry a previously reserved request without a saved response within the aggregate cap.')
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    # One aggregate budget owner, including retries and uncertain reservations.
    with semantic.generation_lock(ROOT):
        prefix, reuse = CASES[args.case]
        source = next(Path('.synesis/pdf').glob(prefix+'*'))
        original = json.loads((source/'document.json').read_text())
        assert 1 <= len(original['pages']) <= 20, 'Short PDFs only; 177-page document excluded.'
        before = source_hashes(source)
        folder = ROOT/args.case
        folder.mkdir(exist_ok=True)
        if not (folder/'document.json').exists():
            shutil.copyfile(source/'document.json', folder/'document.json')
            shutil.copyfile(source/'source.pdf', folder/'source.pdf')
            if reuse:
                shutil.copytree(source/'generated/page-analysis', folder/'generated/page-analysis')
            old = source/'generated/latest-document-0.json'
            if old.exists():
                shutil.copyfile(old, folder/'legacy-reference.json')
        baseline = READING_BASELINES.get(args.case)
        if baseline:
            # Reuse exactly the earlier experiment's readings, never its plans or prose.
            for relative in ('generated/semantic/readings', 'generated/page-analysis'):
                prior = ROOT/baseline/relative
                if prior.exists():
                    shutil.copytree(prior, folder/relative, dirs_exist_ok=True)
        document = json.loads((folder/'document.json').read_text())
        remaining = CAP-consumed()
        if remaining <= 0:
            raise RuntimeError('Aggregate $2 budget exhausted.')
        provider = Provider(folder, True, min(1., remaining), 'gpt-6-luna',
                            retry_missing_responses=args.retry_missing_responses)
        start = time.monotonic()
        report = {'case': args.case, 'pages': len(document['pages']), 'capUsd': CAP,
                  'reusesLegacyReadings': reuse, 'readingBaseline': baseline,
                  'planVersion': semantic.PLAN_VERSION, 'studyVersion': semantic.STUDY_VERSION,
                  'sourceDocumentId': source.name}
        with (folder/'progress.log').open('a') as log, contextlib.redirect_stdout(log):
            try:
                result = semantic.generate(folder, document, provider, 'document', None)
                result.update(runUsage=run_usage(provider))
                write_json(semantic.latest_path(folder, 'document', 0), result)
                write_json(folder/'result.json', result)
                report.update(status='complete', coverageComplete=result['coverageComplete'],
                              coverageCounts=result['coverageCounts'], metrics=result['metrics'],
                              sections=len(result['sections']), concepts=len(result['concepts']))
            except Exception as error:
                report.update(status='failed', errorType=type(error).__name__, error=str(error))
                traceback.print_exc(file=log)
            finally:
                history = semantic.record_usage(folder, document, provider, 'document', None)
        report.update(seconds=round(time.monotonic()-start, 2), usage=run_usage(provider),
                      aggregateReservedOrSettledUsd=round(consumed(), 8), generationUsage=history,
                      originalUnchanged=before == source_hashes(source))
        write_json(folder/f"report-{provider.ledger['operationId']}.json", report)
        write_json(folder/'report.json', report)
        print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
