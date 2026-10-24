"""Ask an expert: farmers and FPOs raise a problem (typed, spoken or as a voice note); the district's KVK answers."""
from django import forms
from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.errors import ApiError
from accounts.models import Role, User
from extension.scope import centre_for_place
from issues import services
from issues.models import Issue, Reply
from rates.crops import CROPS

from .forms import LangForm
from .helpers import error_text, ok, warn
from .market_views import base_for


class IssueForm(LangForm):
    category = forms.ChoiceField(label="What is it about?", choices=list(Issue.Category.choices), initial="pest")
    crop = forms.ChoiceField(label="Crop (optional)", choices=[("", "-")] + list(CROPS.items()), required=False)
    description = forms.CharField(label="Tell us the problem", required=False, max_length=2000, widget=forms.Textarea(attrs={"rows": 4, "data-voice": "1"}))
    urgent = forms.BooleanField(label="It is urgent (the crop is being damaged now)", required=False)


def _who(request):
    u = request.user
    if not u.is_authenticated or u.role not in (Role.FARMER, Role.AGENT):
        return None
    return u


def desk(request):
    u = _who(request)
    if u is None:
        return redirect("/login/?next=/help/")
    from django.db.models import Q
    qs = Issue.objects.filter(Q(raised_by=u) | Q(farmer=u))
    if u.role == Role.AGENT:
        from profiles.models import OrgMembership
        org_ids = list(OrgMembership.objects.filter(user=u).values_list("organisation_id", flat=True))
        qs = Issue.objects.filter(Q(raised_by=u) | Q(organisation_id__in=org_ids))
    from extension.services import place_of
    state, district, _ = place_of(u)
    centre = centre_for_place(state, district)
    members = User.objects.filter(farmer_profile__organisation__memberships__user=u).select_related("farmer_profile") if u.role == Role.AGENT else []
    return render(request, "web/help/desk.html", {"rows": qs.select_related("centre")[:60], "form": IssueForm(lang=request.lang), "centre": centre, "members": members,
                                                  "base_tpl": base_for(u)})


@require_POST
def raise_issue(request):
    u = _who(request)
    if u is None:
        raise Http404
    form = IssueForm(request.POST, lang=request.lang)
    if not form.is_valid():
        warn(request, "Something went wrong. Please try again.")
        return redirect("/help/")
    d = form.cleaned_data
    farmer = None
    if u.role == Role.AGENT and (request.POST.get("farmer") or "").isdigit():
        farmer = User.objects.filter(pk=int(request.POST["farmer"]), role=Role.FARMER).first()

    def num(key):
        try:
            return float(request.POST.get(key)) if request.POST.get(key) else None
        except ValueError:
            return None

    try:
        issue = services.raise_issue(u, {**d, "via_voice": request.POST.get("via_voice") == "1", "voice_note": request.FILES.get("voice_note"), "photo": request.FILES.get("photo"),
                                         "lat": num("lat"), "lon": num("lon"), "farmer": farmer}, request)
    except ApiError as e:
        warn(request, error_text(request, e))
        return redirect("/help/")
    if issue.centre_id:
        ok(request, "Sent to {centre}. An expert will reply here.", centre=issue.centre.name)
    else:
        ok(request, "Saved. No KVK is connected for your district yet; Seedha Bazar staff will see it.")
    return redirect(f"/help/{issue.pk}/")


def detail(request, pk):
    issue = get_object_or_404(Issue.objects.select_related("centre", "farmer__farmer_profile"), pk=pk)
    side = services.can_see(request.user, issue)
    if side != "owner":
        if side == "centre":
            return redirect(f"{settings.INSTITUTION_URL}/issues/{issue.pk}/")
        raise Http404
    Issue.objects.filter(pk=issue.pk).update(farmer_seen_at=timezone.now())
    return render(request, "web/help/detail.html", {"i": issue, "replies": issue.replies.exclude(kind="note").select_related("by"), "base_tpl": base_for(request.user)})


@require_POST
def reply(request, pk):
    issue = get_object_or_404(Issue, pk=pk)
    try:
        services.reply(issue, request.user, request.POST.get("text", ""), request.POST.get("kind", "reply"), request.POST.get("via_voice") == "1",
                       request.FILES.get("voice_note"), request.POST.get("status", ""), request)
        ok(request, "Sent.")
    except ApiError as e:
        warn(request, error_text(request, e))
    side = services.can_see(request.user, issue)
    return redirect(f"/issues/{issue.pk}/" if side == "centre" else f"/help/{issue.pk}/")


def media(request, kind, pk, field):
    """Voice notes and photos are private: only the people on the issue and its centre may open them."""
    obj = get_object_or_404(Issue if kind == "issue" else Reply, pk=pk)
    issue = obj if kind == "issue" else obj.issue
    if not services.can_see(request.user, issue) or field not in ("voice_note", "photo"):
        raise Http404
    f = getattr(obj, field, None)
    if not f:
        raise Http404
    resp = FileResponse(f.open("rb"))
    resp["Cache-Control"] = "private, no-store"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp
