"""Only exact native Flex capacity rejection is documented as uncharged."""
def unavailable(native, entry):
    err=native.get('error')or{}
    return (entry.get('requestedServiceTier')=='flex'
        and native.get('service_tier')=='flex'
        and native.get('id')==entry.get('responseId')
        and native.get('status')=='failed'
        and err.get('type')=='resource_unavailable'
        and err.get('code')=='flex_unavailable'
        and not entry.get('finalTextChars') and not native.get('usage'))
def tier(attempt):
    if attempt is None:return None
    # Reuse the existing next attempt, never create a fifth delivery.
    with attempt.race.lock:
        prior=attempt.race.attempts[:attempt.index]
        return 'default' if any((a.entry or{}).get('documentedFlexNoCharge')for a in prior) else None
