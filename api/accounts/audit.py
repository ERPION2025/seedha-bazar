from .models import AuditEvent


def client_ip(request):
    if request is None:
        return None
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log(action, actor=None, target=None, request=None, **meta):
    """Record a sensitive action. Never put OTPs, PINs or tokens in meta."""
    AuditEvent.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        target_type=target.__class__.__name__ if target is not None else "",
        target_id=str(getattr(target, "pk", "")) if target is not None else "",
        meta=meta,
        ip=client_ip(request),
    )
