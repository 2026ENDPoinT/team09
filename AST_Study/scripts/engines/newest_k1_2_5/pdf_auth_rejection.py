"""Recognize definite credential rejection without rewriting historical ledgers.

An HTTP status alone is not enough: an accepted response or recorded usage keeps
the ordinary duplicate-charge guard, even if a later lookup returned 401.
"""
import hashlib


AUTHENTICATION_CODES = frozenset(('invalid_api_key', 'expired_secret_key', 'token_invalidated'))


def authentication_key_id(key):
    """Opaque comparison only; never persist the credential itself."""
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def is_authentication_rejection(entry):
    if not isinstance(entry, dict) or entry.get('state') != 'failed_or_uncertain':
        return False
    error = entry.get('apiError')
    return (type(entry.get('httpStatus')) is int and entry['httpStatus'] == 401
            and isinstance(error, dict) and isinstance(error.get('code'), str)
            and error['code'] in AUTHENTICATION_CODES
            and not entry.get('responseId') and not entry.get('chatCompletionId')
            and not entry.get('usage') and not entry.get('recoveredOriginalResponse')
            and entry.get('estimatedUsd', 0) == 0)
