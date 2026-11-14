"""Version-scoped concurrency; model/account token admission stays shared."""
EXPANDED_STRATEGIES = frozenset({'newest-k1-1', 'newest-k1-11', 'newest-k1-1-1', 'newest-k1-1-2','newest-k1-1-3','newest-k1-2-4'})
STUDY_WORKERS = 20
STARTUP_WORKERS = 22
SINGLE_UNIT_STRATEGIES = frozenset({'newest-k1-1-1', 'newest-k1-1-2','newest-k1-1-3','newest-k1-2-4'})


def worker_limits(strategy):
    if strategy == 'newest-k1-2-4':return (80,80)
    # K1.1.1 uses one source unit per request, with no extra startup workers.
    return (60, 60) if strategy in SINGLE_UNIT_STRATEGIES else (STUDY_WORKERS, STARTUP_WORKERS)


def admission_options(strategy, *, hedge=False, overview=False):
    if strategy not in EXPANDED_STRATEGIES:
        return {}
    if strategy in SINGLE_UNIT_STRATEGIES:
        # Initial requests/flow share 60 slots. Authorized repeat attempts have
        # separate count admission, while the account TPM/RPM bucket stays shared.
        return {'parallel_limit': 80 if strategy == 'newest-k1-2-4' else 60, 'count_parallel': not hedge}
    exempt_overview=overview and strategy in ('newest-k1-1','newest-k1-1-1','newest-k1-1-2','newest-k1-1-3')
    return {'parallel_limit': STUDY_WORKERS, 'count_parallel': not (hedge or exempt_overview)}
