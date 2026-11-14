"""Offline recovery and repeat-charge protection for already-sent study batches.

Ledger files are indexed once per generation. Only the original namespaced
contract and an exact cached JSON response may provide a child reply. Durable
Responses native bodies are re-normalized using an explicit final phase; other
transport raw/incomplete files are never interpreted as a successful answer. The ordinary
unit validator still runs after recovery. No provider, network or wallet is used.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re

from pdf_study_batch_transport import decode_each
from pdf_study_cache_reuse import constrained_format
from pdf_auth_rejection import is_authentication_rejection


class BatchRecoveryError(ValueError):
    """The local source/ledger cannot safely establish paid batch ownership."""


def _strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise BatchRecoveryError('복구 계약이나 사용 기록에 중복 JSON 키가 있어요.')
            value[key] = item
        return value
    def constant(_):
        raise BatchRecoveryError('복구 계약이나 사용 기록의 숫자 형식이 올바르지 않아요.')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _source_ids(job):
    if not isinstance(job, dict) or not isinstance(job.get('id'), str) or not job['id']:
        raise BatchRecoveryError('현재 학습 단위 ID가 올바르지 않아요.')
    blocks = job.get('blocks')
    if not isinstance(blocks, list) or not blocks:
        raise BatchRecoveryError('현재 학습 단위의 원문 목록이 없어요.')
    ids = [block.get('id') if isinstance(block, dict) else None for block in blocks]
    if any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
        raise BatchRecoveryError('현재 원문 ID가 없거나 중복돼요.')
    return ids


class BatchRecoveryIndex:
    """Index ``folder/usage`` once, independent of changed batch packaging.

    ``recover(job, retry_missing_responses=False)`` returns ``(raw, diagnostic)``
    for a valid cached child, ``None`` for no paid batch history (or an explicitly
    permitted unresolved retry), and otherwise raises ``MissingPaidResponseError``.
    New explicit teaching identities are separate generation contracts; missing
    legacy identities block repayment but cannot establish a recoverable answer.
    ``response_format`` must be the current canonical per-unit format, before
    source-ID constraining. The current study format is the default.
    ``single_history(job)`` separately reports sent singleton history so callers
    can use the original single payload's cache-only Provider path before
    repacking. It neither loads a response nor authorizes a new paid attempt.
    """

    def __init__(self, folder, jobs, model, strategy, teaching_identity, *, response_format=None):
        self.folder = Path(folder).resolve()
        self.generated = self.folder / 'generated'
        self.model = model
        self.strategy = strategy
        self.teaching_identity = teaching_identity
        if not all(isinstance(value, str) and value for value in (model, strategy, teaching_identity)):
            raise BatchRecoveryError('모델·학습 방식·생성 계약 ID가 필요해요.')
        if response_format is None:
            from pdf_new_concept_ver99_study import STUDY_FORMAT
            response_format = STUDY_FORMAT
        if not isinstance(response_format, dict):
            raise BatchRecoveryError('현재 단위별 응답 형식이 필요해요.')
        self.jobs = {}
        self.schemas = {}
        for job in jobs:
            ids = _source_ids(job)
            key = job['id']
            if key in self.jobs:
                raise BatchRecoveryError('현재 학습 단위 ID가 중복돼요.')
            self.jobs[key] = copy.deepcopy(job)
            self.schemas[key] = constrained_format(response_format, job)['json_schema']['schema']
            if self.schemas[key].get('$defs', {}).get('studySourceId') != {'type': 'string', 'enum': ids}:
                raise BatchRecoveryError('현재 응답 형식의 원문 범위를 확인하지 못했어요.')
        self.stats = {'ledgerFilesRead': 0, 'matchedPaidBatchRequests': 0, 'matchedPaidSingleRequests': 0,
                      'contractFilesRead': 0, 'responseFilesRead': 0}
        self._by_job = {key: [] for key in self.jobs}
        self._singles = set()
        self._single_pending = set()
        self._single_pending_ids = {}
        self._decoded = {}
        self._index()

    def _index(self):
        records = []
        seen = {}
        for path in sorted((self.folder / 'usage').glob('*.json')):
            self.stats['ledgerFilesRead'] += 1
            try:
                ledger = _strict_json(path.read_bytes())
            except (OSError, ValueError, TypeError) as error:
                raise BatchRecoveryError('이전 유료 사용 기록을 안전하게 읽지 못했어요.') from error
            if not isinstance(ledger, dict):
                raise BatchRecoveryError('이전 유료 사용 기록이 객체가 아니에요.')
            if ledger.get('model') != self.model:
                continue
            entries = ledger.get('requests')
            if not isinstance(entries, list):
                raise BatchRecoveryError('이전 유료 요청 목록이 없어요.')
            for entry in entries:
                if not isinstance(entry, dict):
                    raise BatchRecoveryError('이전 유료 요청 기록이 객체가 아니에요.')
                ids = entry.get('unitIds')
                if (entry.get('state') == 'not_sent' or is_authentication_rejection(entry) or 'sentAtMs' not in entry or
                        not isinstance(ids, list) or not ids):
                    continue
                if entry.get('strategy') not in (None, self.strategy):
                    continue
                identity = entry.get('studyTeachingIdentity')
                if isinstance(identity, str) and identity and identity != self.teaching_identity:
                    continue
                matching = [key for key in ids if isinstance(key, str) and key in self.jobs]
                if not matching:
                    continue
                if len(ids) == 1:
                    # Missing kind/identity metadata is legacy ambiguity, not
                    # evidence that the original single request was free.
                    if entry.get('kind') not in (None, 'region_study'):
                        continue
                    self._singles.add(matching[0])
                    from pdf_generation_cancel import retryable
                    if entry.get('state')!='settled' and not retryable(entry):
                        self._single_pending.add(matching[0])
                        self._single_pending_ids.setdefault(matching[0],set()).add(entry.get('requestId'))
                    self.stats['matchedPaidSingleRequests'] += 1
                    continue
                record = {'entry': copy.deepcopy(entry), 'ledger': str(path),
                          'number': len(records), 'indexError': None}
                request_id = entry.get('requestId')
                previous = seen.get(request_id) if isinstance(request_id, str) else None
                binding = (entry.get('unitIds'), entry.get('studyBatchContract'),
                           entry.get('responseCacheKey'), entry.get('studyTeachingIdentity'))
                if previous is not None and previous['binding'] != binding:
                    previous['ambiguous'] = True
                if previous is not None and previous['ambiguous']:
                    record['indexError'] = 'ambiguous_request_binding'
                    for old in previous['records']:
                        old['indexError'] = 'ambiguous_request_binding'
                if isinstance(request_id, str):
                    if previous is None:
                        seen[request_id] = {'binding': binding, 'records': [record], 'ambiguous': False}
                    else:
                        previous['records'].append(record)
                records.append(record)
                for key in set(matching):
                    self._by_job[key].append(record)
                self.stats['matchedPaidBatchRequests'] += 1
        # Prefer the most recent valid paid answer, including an explicitly
        # retried one. A failed later attempt cannot erase an older usable reply.
        def stamp(record):
            value = record['entry'].get('sentAtMs')
            return value if type(value) in (int, float) else 0
        for records in self._by_job.values():
            records.sort(key=lambda record: (stamp(record), record['number']), reverse=True)

    def _safe_contract_path(self, value):
        if not isinstance(value, str) or not value or not Path(value).is_absolute():
            raise BatchRecoveryError('원래 배치 계약의 절대 경로가 없어요.')
        generated = self.generated.resolve()
        path = Path(value).resolve()
        if (self.generated.is_symlink() or not generated.is_relative_to(self.folder) or
                not path.is_relative_to(generated) or path.suffix != '.json'):
            raise BatchRecoveryError('배치 복구 계약이 해당 문서의 generated 범위를 벗어나요.')
        return path

    def _safe_response_path(self, key):
        if not isinstance(key, str) or re.fullmatch(r'[0-9a-f]{64}', key) is None:
            raise BatchRecoveryError('원래 유료 응답 파일 ID가 올바르지 않아요.')
        generated = self.generated.resolve()
        directory = self.generated / 'paid-responses'
        resolved = directory.resolve()
        path = (directory / (key + '.json')).resolve()
        if (self.generated.is_symlink() or not generated.is_relative_to(self.folder) or
                not resolved.is_relative_to(generated) or not path.is_relative_to(resolved)):
            raise BatchRecoveryError('유료 응답 파일이 해당 문서 범위를 벗어나요.')
        return path

    def _paid_reply(self, response_path):
        """Prefer authoritative native Responses, without rewriting any cache."""
        from pdf_study_rejection import is_rejected
        if is_rejected(response_path):
            raise BatchRecoveryError('반복 출력으로 거부된 응답은 학습 결과로 복구하지 않아요.')
        native_path = response_path.with_suffix('.responses.raw.json')
        if native_path.exists() or native_path.is_symlink():
            directory = (self.generated / 'paid-responses').resolve()
            resolved = native_path.resolve()
            if not resolved.is_relative_to(directory):
                raise BatchRecoveryError('유료 원본 응답 파일이 해당 문서 범위를 벗어나요.')
            from pdf_responses_transport import response_body
            normalized = response_body(_strict_json(resolved.read_bytes()))
            choice = normalized['choices'][0]
            message = choice.get('message', {})
            if (choice.get('finish_reason') != 'stop' or message.get('refusal') or
                    not isinstance(message.get('content'), str)):
                raise BatchRecoveryError('유료 원본 응답에서 확정된 최종 학습 답변을 확인하지 못했어요.')
            # Preserve the final JSON string for decode_each so duplicate keys
            # and an invalid child cannot be hidden by an earlier JSON parser.
            return message['content'], 'responses_native'
        return response_path.read_bytes(), 'parsed_response'

    def _load(self, record):
        number = record['number']
        if number in self._decoded:
            return self._decoded[number]
        entry = record['entry']
        value = {'valid': {}, 'errors': [], 'reason': None}
        try:
            if record['indexError']:
                raise BatchRecoveryError('같은 유료 요청에 서로 다른 배치 소유 정보가 있어요.')
            if not isinstance(entry.get('requestId'), str) or not entry['requestId']:
                raise BatchRecoveryError('원래 유료 요청 ID가 없어요.')
            if entry.get('studyTeachingIdentity') != self.teaching_identity:
                raise BatchRecoveryError('이전 배치의 생성 계약 ID가 없어 같은 학습 지침인지 확인하지 못했어요.')
            ids = entry.get('unitIds')
            if (not isinstance(ids, list) or not 2 <= len(ids) <= 4 or
                    any(not isinstance(key, str) or key not in self.jobs for key in ids) or len(set(ids)) != len(ids)):
                raise BatchRecoveryError('이전 배치와 현재 학습 단위의 소유 범위가 다르거나 모호해요.')
            contract_path = self._safe_contract_path(entry.get('studyBatchContract'))
            response_path = self._safe_response_path(entry.get('responseCacheKey'))
            from pdf_study_rejection import is_rejected
            if is_rejected(response_path,entry):
                raise BatchRecoveryError('반복 출력으로 거부된 요청의 사용 기록만 보존했어요.')
            self.stats['contractFilesRead'] += 1
            contract = _strict_json(contract_path.read_bytes())
            units = contract.get('units') if isinstance(contract, dict) else None
            if (not isinstance(units, list) or len(units) != len(ids) or
                    any(not isinstance(unit, dict) for unit in units) or
                    [unit.get('jobId') for unit in units] != ids):
                raise BatchRecoveryError('원래 배치 계약과 결제한 학습 단위 목록이 일치하지 않아요.')
            for unit in units:
                job = self.jobs[unit['jobId']]
                if unit.get('sourceIds') != _source_ids(job) or unit.get('schema') != self.schemas[job['id']]:
                    raise BatchRecoveryError('복구할 단위의 원문 ID 또는 응답 계약이 현재 범위와 달라요.')
            value['contractValidated']=True
            self.stats['responseFilesRead'] += 1
            raw, source = self._paid_reply(response_path)
            value['source'] = source
            records, errors = decode_each(raw, contract)
            value['valid'] = {units[row['index']]['jobId']: row['raw'] for row in records}
            value['errors'] = errors
            if errors:
                value['reason'] = 'partial_paid_response'
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
            value['reason'] = type(error).__name__
            value['errors'] = [{'index': None, 'name': None, 'code': 'unusable_paid_batch',
                                'error': str(error)}]
        self._decoded[number] = value
        return value

    def _current_key(self, job):
        _source_ids(job)
        key = job['id']
        if key not in self.jobs or job != self.jobs[key]:
            raise BatchRecoveryError('복구 요청이 처음 확인한 현재 원문 단위와 달라요.')
        return key

    def single_history(self, job):
        """A sent original singleton must not silently become a paid new batch."""
        return self._current_key(job) in self._singles

    def single_unresolved(self, job, *, retry_unresolved_request_ids=()):
        key=self._current_key(job)
        return key in self._single_pending and not (
            self._single_pending_ids.get(key,set()) <= set(retry_unresolved_request_ids))

    def recover(self, job, *, retry_missing_responses=False, retry_unresolved_request_ids=()):
        key = self._current_key(job)
        records = self._by_job[key]
        if not records:
            return None
        attempts = []
        for record in records:
            decoded = self._load(record)
            entry = record['entry']
            attempts.append({'requestId': entry.get('requestId'), 'reason': decoded['reason']})
            if key in decoded['valid']:
                return copy.deepcopy(decoded['valid'][key]), {
                    'kind': 'paid_batch_local_recovery', 'additionalApiRequests': 0,
                    'requestId': entry.get('requestId'), 'responseCacheKey': entry.get('responseCacheKey'),
                    'ledgerPath': record['ledger'], 'contractPath': entry.get('studyBatchContract'),
                    'unitId': key, 'paidBatchUnitIds': copy.deepcopy(entry.get('unitIds')),
                    'legacyTeachingIdentity': not bool(entry.get('studyTeachingIdentity')),
                    'paidResponseSource': decoded.get('source'),
                    'transportErrors': copy.deepcopy(decoded['errors'])}
        if retry_missing_responses is True and all(r['entry'].get('state')=='settled'for r in records):
            return None
        from pdf_generation_cancel import retryable
        if all(retryable(r['entry']) for r in records):
            return None
        # Completed peers above always win. Broken contracts/invalid existing
        # answers do not become missing receipts merely because retry was approved.
        if (retry_missing_responses is True and records and
                all(self._load(r).get('contractValidated') is True
                    and self._load(r).get('reason') == 'FileNotFoundError'
                    and r['entry'].get('requestId') in retry_unresolved_request_ids
                    for r in records)):
            return None
        from pdf_ai import MissingPaidResponseError
        error = MissingPaidResponseError('이 단위의 원래 유료 요청 기록을 보존했어요. 응답과 사용량을 아직 확인하지 못해 중복 생성하지 않았어요. 연결이 돌아오면 원래 결과를 다시 조회할 수 있어요.')
        error.batch_recovery_diagnostic = {'kind': 'paid_batch_recharge_blocked',
            'additionalApiRequests': 0, 'unitId': key, 'attempts': attempts}
        raise error
