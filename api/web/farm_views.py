"""Livelihoods: choose them before setting up (farmers, FPOs and NGOs), and "My farm" for everything beyond crops:
units (herd, batch, pond, apiary, rearing, pig unit), quick diary entries, reminders, and selling what they produce."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django import forms
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import audit
from accounts.models import Role
from farming import farm as farm_svc, livelihoods as lh
from farming.models import FarmEntry, FarmUnit

from .forms import LangForm, date_field
from .helpers import ok, role_required, warn
from .market_views import base_for

farmer_or_agent = role_required(Role.FARMER, Role.AGENT)
farmer_only = role_required(Role.FARMER)


def _holder(user):
    """Where the choice is kept: the farmer's profile, or the FPO/NGO of an agent."""
    if user.role == Role.FARMER:
        return user.farmer_profile
    from profiles.models import OrgMembership
    m = OrgMembership.objects.filter(user=user).select_related("organisation").first()
    return m.organisation if m else None


@farmer_or_agent
def start(request):
    """Step one after signing in: what do you do? Only the matching parts of the app are shown afterwards."""
    u = request.user
    holder = _holder(u)
    if holder is None:  # a new FPO/NGO agent registers the organisation first
        return redirect("/fpo/register/")
    if request.method == "POST":
        picked = [c for c in request.POST.getlist("segments") if c in lh.CODES]
        if not picked:
            warn(request, "Choose at least one.")
        else:
            holder.segments = picked
            holder.save()
            audit.log("livelihoods_chosen", actor=u, target=u, request=request, segments=picked)
            nxt = request.POST.get("next", "")
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            if u.role == Role.FARMER and holder.level == 0:
                return redirect("/farmer/profile/")
            return redirect("/farmer/" if u.role == Role.FARMER else "/fpo/")
    current = list(holder.segments or ([] if u.role == Role.AGENT else (["crops"] if getattr(holder, "crops", None) else [])))
    return render(request, "web/farm/start.html", {"options": [(c, v) for c, v in lh.LIVELIHOODS.items()], "current": current, "next": request.GET.get("next", ""),
                                                   "org": u.role == Role.AGENT, "base_tpl": base_for(u)})


def needs_start(user) -> bool:
    """New farmers (and FPOs) choose their livelihoods before anything else. Older crop accounts count as crop farmers."""
    holder = _holder(user)
    if holder is None or holder.segments:
        return False
    return not getattr(holder, "crops", None) if user.role == Role.FARMER else True


# ---------- My farm ----------
class UnitForm(LangForm):
    livelihood = forms.ChoiceField(label="Livelihood", choices=[])
    kind = forms.ChoiceField(label="Type", choices=[])
    name = forms.CharField(label="Name", max_length=80, widget=forms.TextInput(attrs={"placeholder": "Home shed, Pond 1, Batch March..."}))
    count = forms.IntegerField(label="How many", min_value=0, max_value=1000000)
    area_acres = forms.DecimalField(label="Area in acres (optional)", required=False, min_value=Decimal("0"), decimal_places=2)
    tag = forms.CharField(label="ID or registration (optional)", max_length=200, required=False)
    started_on = date_field("Started on (batch, stocking or rearing)")

    def __init__(self, *args, segs=(), livelihood="", **kw):
        super().__init__(*args, **kw)
        animal = [c for c in segs if c in lh.ANIMAL_CODES] or lh.ANIMAL_CODES
        self.fields["livelihood"].choices = [(c, lh.LIVELIHOODS[c]["label"]) for c in animal]
        cfg = lh.LIVELIHOODS[livelihood if livelihood in animal else animal[0]]
        self.fields["kind"].choices = cfg["kinds"]
        self.fields["count"].label = cfg["count"]
        if cfg.get("area"):
            self.fields["area_acres"].label = cfg["area"] + " (optional)"
        else:
            del self.fields["area_acres"]
        if cfg.get("tag"):
            self.fields["tag"].label = cfg["tag"]
        else:
            del self.fields["tag"]


@farmer_only
def farm(request):
    u = request.user
    segs = lh.of(u)
    units = list(FarmUnit.objects.filter(owner=u))
    for un in units:
        un.cfg, un.s = lh.LIVELIHOODS.get(un.livelihood, {}), farm_svc.summary(un)
    return render(request, "web/farm/list.html", {"units": units, "tasks": farm_svc.tasks_for(u), "segs": [(c, lh.LIVELIHOODS[c]) for c in segs if c in lh.ANIMAL_CODES],
                                                  "whole": farm_svc.whole_farm(u) if len(segs) > 1 else [], "base_tpl": base_for(u)})


@farmer_only
def unit_new(request):
    u = request.user
    segs = lh.of(u)
    chosen = request.POST.get("livelihood") or request.GET.get("livelihood") or ""
    form = UnitForm(request.POST if request.POST.get("action") == "save" else None, lang=request.lang, segs=segs, livelihood=chosen,
                    initial={"livelihood": chosen, "started_on": timezone.localdate()})
    if request.method == "POST" and request.POST.get("action") == "save" and form.is_valid():
        d = form.cleaned_data
        un = FarmUnit.objects.create(owner=u, livelihood=d["livelihood"], kind=d["kind"], name=d["name"], count=d["count"], area_acres=d.get("area_acres"),
                                     tag=d.get("tag", ""), started_on=d["started_on"])
        audit.log("farm_unit_added", actor=u, target=un, request=request)
        ok(request, "Added. Reminders for it will appear here and on your phone.")
        return redirect(f"/farm/{un.pk}/")
    return render(request, "web/farm/unit_form.html", {"form": form, "base_tpl": base_for(u)})


def _dec(v):
    try:
        return Decimal(str(v)) if v not in (None, "") else None
    except InvalidOperation:
        return None


@farmer_only
def unit(request, pk):
    u = request.user
    un = get_object_or_404(FarmUnit, pk=pk, owner=u)
    cfg = lh.LIVELIHOODS[un.livelihood]
    if request.method == "POST":
        action = request.POST.get("action", "entry")
        if action == "entry":
            kind = request.POST.get("kind", "")
            qty, amt = _dec(request.POST.get("quantity")), _dec(request.POST.get("amount"))
            if kind not in FarmEntry.Kind.values or kind == "task" or (qty is None and amt is None) or (qty is not None and qty < 0) or (amt is not None and amt < 0):
                warn(request, "Write how much, or the amount in rupees.")
            else:
                try:
                    when = date.fromisoformat(request.POST.get("date") or "") if request.POST.get("date") else timezone.localdate()
                except ValueError:
                    when = timezone.localdate()
                FarmEntry.objects.create(unit=un, owner=u, kind=kind, date=min(when, timezone.localdate()), quantity=qty, amount=amt, note=request.POST.get("note", "")[:200])
                ok(request, "Saved.")
        elif action == "done":
            ref = request.POST.get("ref", "")[:40]
            if any(t["ref"] == ref for t in farm_svc.due_tasks(un)):
                FarmEntry.objects.create(unit=un, owner=u, kind="task", date=timezone.localdate(), ref=ref)
                ok(request, "Marked as done.")
        elif action in ("close", "reopen"):
            un.active = action == "reopen"
            un.save(update_fields=["active"])
            ok(request, "Saved.")
        return redirect(f"/farm/{un.pk}/")
    return render(request, "web/farm/unit.html", {"un": un, "cfg": cfg, "s": farm_svc.summary(un), "tasks": farm_svc.due_tasks(un), "entries": un.entries.exclude(kind="task")[:60],
                                                  "kinds": [k for k in FarmEntry.Kind.choices if k[0] != "task"], "today": timezone.localdate(),
                                                  "products": list(cfg.get("products", {})), "base_tpl": base_for(u)})


@farmer_or_agent
def fpo_farm(request):
    """For an FPO or NGO: members' farm units by livelihood, what they produced in the last 30 days, and reminders falling due."""
    from datetime import timedelta

    from django.db.models import Count, Sum

    from profiles.models import FarmerProfile, OrgMembership

    m = OrgMembership.objects.filter(user=request.user).select_related("organisation").first()
    if m is None:
        raise Http404
    members = FarmerProfile.objects.filter(organisation=m.organisation, org_status="confirmed").values_list("user_id", flat=True)
    units = FarmUnit.objects.filter(owner_id__in=members, active=True)
    since = timezone.localdate() - timedelta(days=30)
    rows = []
    for code in lh.ANIMAL_CODES:
        us = units.filter(livelihood=code)
        if not us.exists():
            continue
        made = FarmEntry.objects.filter(unit__in=us, kind="produce", date__gte=since).aggregate(t=Sum("quantity"))["t"] or 0
        rows.append({"code": code, "cfg": lh.LIVELIHOODS[code], "units": us.count(), "farmers": us.values("owner").distinct().count(), "head": sum(u.count for u in us),
                     "made": made})
    tasks = sorted((t for un in units.select_related("owner__farmer_profile")[:300] for t in farm_svc.due_tasks(un) if t["days"] <= 0), key=lambda t: t["date"])[:30]
    return render(request, "web/farm/fpo.html", {"rows": rows, "tasks": tasks, "org": m.organisation, "base_tpl": base_for(request.user)})
