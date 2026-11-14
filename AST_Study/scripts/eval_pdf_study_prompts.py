"""Small opt-in synthetic study evaluation; never reads or overwrites user PDF results.

Outputs are evidence for human review against fixtures' criteria, not automatic quality scores.
"""
import argparse
import hashlib
import json
from pathlib import Path

import pdf_semantic as semantic
from pdf_ai import Provider, run_usage
from pdf_pipeline import write_json
from pdf_summary_editor import edit_summary
from pdf_summary_editor import PROMPT as EDIT_PROMPT


def cases():
    return json.loads((Path(__file__).parent / 'fixtures/pdf_study_quality.json').read_text(encoding='utf-8'))


def make_job(fixtures):
    job = []
    for i, case in enumerate(fixtures):
        block = {'id': f'b{i}', 'page': i+1, 'kind': 'text', 'sourceRole': 'teaching',
                 'title': case['title'], 'text': case['source'], 'readingStatus': 'complete',
                 'uncertainDetails': [], 'bbox': [0, 0, 1, 1], 'anchorIds': [],
                 'originId': f'b{i}', 'provenance': 'synthetic-fixture', 'start': 0,
                 'end': len(case['source'])}
        job.append({'unitId': case['id'], 'parentId': case['id'], 'segment': 1,
                    'blocks': [block], 'context': [], 'requiredBlockIds': [block['id']],
                    'boundaryChecks': [], 'definedTerms': []})
    return job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-remote', action='store_true')
    parser.add_argument('--max-usd', type=float, default=.15)
    args = parser.parse_args()
    fixtures = cases()
    args.output.mkdir(parents=True, exist_ok=True)
    signature = hashlib.sha256(json.dumps([semantic.STUDY_PROMPT, EDIT_PROMPT,
        semantic.CONCEPT_AUDIT_PROMPT, fixtures], ensure_ascii=False).encode()).hexdigest()
    manifest_path = args.output / 'prompt-manifest.json'
    if (args.output / 'study-raw.json').exists():
        if not manifest_path.exists() or json.loads(manifest_path.read_text())['signature'] != signature:
            raise ValueError('Use a fresh output folder for a different prompt revision.')
    write_json(manifest_path, {'signature': signature, 'studyVersion': semantic.STUDY_VERSION,
                              'studyPrompt': semantic.STUDY_PROMPT, 'editorPrompt': EDIT_PROMPT,
                              'auditPrompt': semantic.CONCEPT_AUDIT_PROMPT})
    write_json(args.output / 'fixtures.json', fixtures)
    if not args.allow_remote:
        print('Fixtures prepared; no API request. Use --allow-remote for a bounded run.')
        return
    provider = Provider(args.output, True, args.max_usd)
    job = make_job(fixtures)
    doc = {'documentId': 'synthetic-prompt-review', 'pages': [{} for _ in job]}
    try:
        raw_path = args.output / 'study-raw.json'
        if raw_path.is_file():
            raw = json.loads(raw_path.read_text(encoding='utf-8'))
        else:
            provider.context = {'kind': 'prompt_eval', 'stage': 'semantic_study'}
            raw = provider.complete({'task': 'semantic_study', 'units': job},
                                    system_prompt=semantic.STUDY_PROMPT,
                                    response_format=semantic.study_format(job), max_output=20000)
            write_json(raw_path, raw)
        completed = semantic.validate_study(raw, job, doc)
        write_json(args.output / 'study-validated.json', completed)
        sections = [item['summary'] for item in completed]
        opening, edited, status = edit_summary(provider, args.output, sections)
        write_json(args.output / 'edited.json', {'overview': opening, 'sections': edited,
                                               'summaryEditing': status})
        # A separate missing-card request exercises the same writing rules and knowledge flag.
        audit_path = args.output / 'audit-raw.json'
        if not audit_path.is_file():
            provider.context = {'kind': 'prompt_eval', 'stage': 'missing_concept'}
            audit = provider.complete({'task': 'missing_concept_audit', 'existingConceptNames': [],
                'candidates': [{'cueId': 'c0', 'term': fixtures[1]['title'],
                                'excerpts': [fixtures[1]['source']]}]},
                system_prompt=semantic.CONCEPT_AUDIT_PROMPT,
                response_format=semantic.CONCEPT_AUDIT_FORMAT, max_output=5000)
            write_json(audit_path, audit)
        print(json.dumps({'validatedUnits': len(completed), 'editedSections': len(edited),
                          'editStatus': status['status'], 'usage': run_usage(provider)}, ensure_ascii=False))
    finally:
        write_json(args.output / 'usage-summary.json', run_usage(provider))


if __name__ == '__main__':
    main()
