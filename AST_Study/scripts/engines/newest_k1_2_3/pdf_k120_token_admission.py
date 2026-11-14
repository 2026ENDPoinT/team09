"""K1.2.0 TPM admission: calibrate only an identical, measured fixed prefix.

This does not estimate source text, image tokens, or schemas with a new model
tokenizer. A completed request's measured TOTAL input already includes its
fixed instructions. That total, with 25% margin and framing headroom, replaces
only the instructions' UTF-8 bytes in the previous conservative input bound.
All variable bytes and image bounds stay intact. Cached input is not subtracted.

Only current-operation records supplied by the caller are used. No disk reads,
provider calls, wallet changes, admitted-ticket changes, or cross-model history.
"""
import hashlib
import json

VERSION = 'k120-confirmed-fixed-prefix-v1'
HEADROOM_TOKENS = 256


def _positive_int(value):
    return type(value) is int and value > 0


def prefix_metadata(*, model, instructions, final_delivery=''):
    """Hash the entire fixed text and model; remove only bytes actually bounded."""
    if not isinstance(model, str) or not model:
        raise ValueError('model must be nonempty text')
    if not isinstance(instructions, str) or not isinstance(final_delivery, str):
        raise ValueError('fixed instructions must be text')
    identity = json.dumps([model, instructions, final_delivery], ensure_ascii=False,
                          separators=(',', ':')).encode('utf-8')
    return {'tokenAdmissionPolicy': VERSION,
            'tokenAdmissionModel': model,
            'tokenAdmissionPrefixSha': hashlib.sha256(identity).hexdigest(),
            # final_delivery is covered by the original framing allowance. It is
            # part of the identity, but must never be subtracted a second time.
            'tokenAdmissionFixedBytes': len(instructions.encode('utf-8'))}


def _sample(row, metadata):
    if not isinstance(row, dict):
        return None
    if (row.get('state') != 'settled'
            or row.get('strategy') != 'newest-k1-2-3'
            or row.get('kind') != 'region_study'
            or row.get('inputApi') != 'responses'
            or row.get('studyForegroundResponses') is not True
            or row.get('serverTerminalStatus') != 'completed'
            or row.get('finishReason') not in (None, 'stop')
            or row.get('responseStatus') in ('failed', 'cancelled', 'incomplete')):
        return None
    for key in ('tokenAdmissionPolicy', 'tokenAdmissionModel',
                'tokenAdmissionPrefixSha', 'tokenAdmissionFixedBytes'):
        if row.get(key) != metadata.get(key):
            return None
    usage = row.get('usage')
    if not isinstance(usage, dict):
        return None
    total = usage.get('prompt_tokens', usage.get('input_tokens'))
    if not _positive_int(total):
        return None
    return total


class FixedPrefixAdmission:
    """Callable estimate for not-yet-admitted requests, plus auditable metadata.

    ``records`` must return only this Provider operation's ledger snapshot. The
    admission loop calls ``input_tokens`` outside its rate-state file lock, so a
    provider snapshot never reverses the lock order used by usage settlement.
    Copy ``metadata`` to the request ledger at creation and after admission.
    """
    def __init__(self, *, model, instructions, final_delivery, input_bound, records):
        if type(input_bound) is not int or input_bound < 0:
            raise ValueError('input_bound must be a nonnegative integer')
        if not callable(records):
            raise ValueError('records must return current-operation rows')
        self.original = input_bound
        self.records = records
        self.metadata = prefix_metadata(model=model, instructions=instructions,
                                        final_delivery=final_delivery)
        self.metadata.update(tokenAdmissionInputEstimate=input_bound,
                             tokenAdmissionConfirmedSamples=0,
                             tokenAdmissionBasis='original_input_bound',
                             tokenAdmissionFixedTokenUpper=None,
                             tokenAdmissionEvidenceRequestId=None)

    def input_tokens(self):
        fixed_bytes = self.metadata['tokenAdmissionFixedBytes']
        # Inconsistent framing must never remove variable source/schema bytes.
        if fixed_bytes > self.original or not fixed_bytes:
            return self.original
        samples = []
        try:
            rows = tuple(self.records())
            for row in rows:
                total = _sample(row, self.metadata)
                if total is not None:
                    samples.append((total, row.get('requestId')))
        except Exception:
            # Missing/malformed local evidence restores the previous hard bound.
            samples = []
        estimate = self.original
        upper = evidence = None
        if samples:
            total, evidence = min(samples, key=lambda item: item[0])
            upper = (total * 5 + 3) // 4 + HEADROOM_TOKENS
            estimate = self.original - fixed_bytes + min(fixed_bytes, upper)
        self.metadata.update(tokenAdmissionInputEstimate=estimate,
                             tokenAdmissionConfirmedSamples=len(samples),
                             tokenAdmissionBasis=('confirmed_total_input_as_prefix_upper'
                                                  if estimate < self.original else 'original_input_bound'),
                             tokenAdmissionFixedTokenUpper=upper,
                             tokenAdmissionEvidenceRequestId=evidence)
        return estimate
