"""Printable income statement for a Kisan Credit Card or bank loan, and a public page a bank can use to check it."""
from datetime import date

from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import Role, User
from farmerbook import statement
from farmerbook.models import Statement
from profiles.models import OrgMembership

from .helpers import ok
from .market_views import base_for


def _owner(request):
    """The farmer the statement is about: yourself, or a member if you are their FPO's agent (?for=<id>)."""
    u = request.user
    if not u.is_authenticated:
        return None
    if u.role == Role.FARMER:
        return u
    pid = request.GET.get("for") or request.POST.get("for") or ""
    if u.role == Role.AGENT and pid.isdigit():
        orgs = OrgMembership.objects.filter(user=u).values_list("organisation_id", flat=True)
        return User.objects.filter(pk=int(pid), role=Role.FARMER, farmer_profile__organisation_id__in=list(orgs)).first()
    return None


def page(request):
    owner = _owner(request)
    if owner is None:
        return redirect("/login/?as=farmer")
    start, end = statement.default_period()
    return render(request, "web/statement/page.html", {"owner": owner, "start": start, "end": end, "rows": Statement.objects.filter(owner=owner)[:10],
                                                       "base_tpl": base_for(request.user), "for_id": owner.pk if owner != request.user else ""})


@require_POST
def make(request):
    owner = _owner(request)
    if owner is None:
        raise Http404
    try:
        start, end = date.fromisoformat(request.POST["from"]), date.fromisoformat(request.POST["to"])
    except (KeyError, ValueError):
        start, end = statement.default_period()
    s = statement.make(owner, start, end, request.user)
    ok(request, "Statement ready. Print it or save it as PDF from your browser.")
    return redirect(f"/statement/{s.code}/")


def show(request, code):
    s = get_object_or_404(Statement, code=code)
    u = request.user
    allowed = u.is_authenticated and (u.pk in (s.owner_id, s.made_by_id) or u.is_staff)
    if not allowed:
        raise Http404
    from django.conf import settings
    return render(request, "web/statement/print.html", {"s": s, "d": s.data, "verify_url": f"{settings.SITE_URL}/verify/{s.code}/"})


def verify(request, code):
    """Public: a bank enters the code from the paper and sees the key figures and fingerprint. No phone number."""
    s = Statement.objects.filter(code=code).first()
    ok_digest = s is not None and statement.digest(s.data) == s.digest
    return render(request, "web/statement/verify.html", {"s": s, "d": s.data if s else None, "ok_digest": ok_digest})
