"""Group farming for farmers and FPOs/NGOs: start a crop group, find one nearby, join, and see what makes it trusted."""
from decimal import Decimal

from django import forms
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.errors import ApiError
from accounts.models import Role
from farming import services as farming
from farming.models import PRACTICES, CropGroup, CropGroupMember
from rates.crops import CROPS

from .farmer_views import farmer_only
from .fpo_views import agent_only, needs_org
from .forms import LangForm
from .helpers import error_text, ok, warn


class GroupForm(LangForm):
    crop = forms.ChoiceField(label="Crop", choices=list(CROPS.items()))
    season = forms.ChoiceField(label="Season", choices=list(CropGroup.Season.choices))
    year = forms.IntegerField(label="Year", min_value=2024, max_value=2100)
    village = forms.CharField(label="Village or cluster", max_length=120, required=False)
    seed_variety = forms.CharField(label="Seed variety you will all sow (optional)", max_length=80, required=False)
    practices = forms.MultipleChoiceField(label="What the group agrees to do", choices=PRACTICES, required=False, widget=forms.CheckboxSelectMultiple(attrs={"class": "chips"}),
                                          initial=["same_seed", "sow_together", "buy_inputs", "sell_together"])
    note = forms.CharField(label="Note for members (optional)", max_length=300, required=False, widget=forms.Textarea(attrs={"rows": 2}))


class FarmerGroupForm(GroupForm):
    acres = forms.DecimalField(label="Your acres under this crop", min_value=Decimal("0.1"), max_value=Decimal("500"), decimal_places=2)


def _initial(fp=None):
    season, year = farming.season_now()
    out = {"season": season, "year": year}
    if fp:
        out.update({"village": fp.village, "acres": fp.land_acres, "crop": (fp.crops or [""])[0]})
    return out


@farmer_only
def farmer_groups(request):
    fp = request.user.farmer_profile
    form = FarmerGroupForm(request.POST or None, lang=request.lang, initial=_initial(fp))
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            g = farming.create(request.user, crop=d["crop"], season=d["season"], year=d["year"], district=fp.district, state=fp.state, village=d["village"],
                               seed_variety=d["seed_variety"], practices=d["practices"], note=d["note"], organisation=fp.organisation if fp.org_status == "confirmed" else None,
                               lead_acres=d["acres"], request=request)
        except ApiError as e:
            form.add_error(None, error_text(request, e))
        else:
            ok(request, "Group started. Farmers of your district who grow this crop have been told.")
            return redirect(f"/farmer/groups/{g.pk}/")
    mine = [farming.card(g) for g in farming.groups_of(request.user).select_related("organisation", "centre")]
    near = [farming.card(g) for g in farming.near(request.user)]
    return render(request, "web/groups/farmer.html", {"form": form, "mine": mine, "near": near, "fp": fp})


@farmer_only
def farmer_group(request, pk):
    g = get_object_or_404(CropGroup.objects.select_related("organisation", "centre"), pk=pk)
    me = CropGroupMember.objects.filter(group=g, farmer=request.user, status="active").first()
    if request.method == "POST":
        try:
            if request.POST.get("action") == "leave":
                farming.leave(g, request.user)
                ok(request, "You left the group.")
                return redirect("/farmer/groups/")
            farming.join(g, request.user, request.POST.get("acres") or "0")
            ok(request, "You are in the group. Members will be told about seed, sowing and selling together.")
        except ApiError as e:
            warn(request, error_text(request, e))
        return redirect(f"/farmer/groups/{g.pk}/")
    return render(request, "web/groups/detail.html", _detail(g, me=me, fp=request.user.farmer_profile))


def _detail(g, **kw):
    members = [{"name": m.farmer.farmer_profile.name, "village": m.farmer.farmer_profile.village, "acres": m.area_acres} for m in farming.active_members(g)]
    return {"g": g, "s": farming.stats(g), "signal": farming.price_signal(g), "members": members,
            "practices": [label for k, label in PRACTICES if k in (g.practices or [])], **kw}


@agent_only
@needs_org
def fpo_groups(request):
    org = request.org
    form = GroupForm(request.POST or None, lang=request.lang, initial=_initial())
    if request.method == "POST" and form.is_valid():
        if not org.verified:
            warn(request, "Your organisation is still being verified. You can add farmers once it is approved.")
            return redirect("/fpo/groups/")
        d = form.cleaned_data
        try:
            g = farming.create(request.user, crop=d["crop"], season=d["season"], year=d["year"], district=org.district, state=org.state, village=d["village"],
                               seed_variety=d["seed_variety"], practices=d["practices"], note=d["note"], organisation=org, request=request)
        except ApiError as e:
            form.add_error(None, error_text(request, e))
        else:
            ok(request, "Group started. Farmers of your district who grow this crop have been told.")
            return redirect(f"/fpo/groups/{g.pk}/")
    rows = [farming.card(g) for g in CropGroup.objects.filter(organisation=org).exclude(status="closed").select_related("organisation", "centre")]
    return render(request, "web/groups/fpo.html", {"form": form, "rows": rows, "org": org, "summary": farming.org_summary(org)})


@agent_only
@needs_org
def fpo_group(request, pk):
    g = get_object_or_404(CropGroup.objects.select_related("organisation", "centre"), pk=pk, organisation=request.org)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "invite":
            n = farming.invite_growers(g)
            ok(request, "Sent to {n} people.", n=n)
        elif action in ("active", "closed"):
            g.status = action
            g.save(update_fields=["status"])
            ok(request, "Saved.")
        return redirect(f"/fpo/groups/{g.pk}/")
    return render(request, "web/groups/detail.html", _detail(g, fpo=True))
