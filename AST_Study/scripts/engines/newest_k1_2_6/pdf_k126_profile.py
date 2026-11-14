"""Select one 1.2.6 prompt experiment for the lifetime of the process."""
import os


PROFILE = os.environ.get('SYNESIS_K126_PROFILE', 'notes')
if PROFILE not in ('dedup', 'notes'):
    raise ValueError('SYNESIS_K126_PROFILE must be dedup or notes')
