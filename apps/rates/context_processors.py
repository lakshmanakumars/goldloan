def live_gold_rates(request):
    """Inject the live gold rate dict into every template that uses
    RequestContext. Returns None if unavailable so templates can hide
    the ticker gracefully."""
    # Lazy import so admin commands don't trigger network on startup
    from .live import get_live_rates
    try:
        return {'live_gold_rates': get_live_rates()}
    except Exception:
        return {'live_gold_rates': None}
