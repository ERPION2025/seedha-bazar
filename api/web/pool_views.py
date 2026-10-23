"""Group selling: FPOs build one lot from many members' stock; members join, see their share and get paid."""
from decimal import Decimal, InvalidOperation

from django import forms
from django.db.models import Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

import catalog
from accounts.errors import ApiError
from accounts.models import Role, User
from farmerbook.models import CropCycle
from market import pools, stock
from market.models import Pool, PoolShare
from profiles.models import OrgMembership
from rates.crops import CROPS

from .forms import LangForm, date_field
from .helpers import error_text, ok, warn
from .i18n import tr


class PoolForm(LangForm):
    product = forms.ChoiceField(label="What will the group sell?", choices=[])
    grade = forms.ChoiceField(label="Quality", choices=[("ungraded", "Not graded"), ("A", "Grade A"), ("B", "Grade B"), ("C", "Grade C")], initial="ungraded", required=False)
    unit = forms.ChoiceField(label="Unit", choices=[("quintal", "Quintal"), ("kg", "Kg"), ("tonne", "Tonne")], initial="quintal")
    price = forms.DecimalField(label="Asking price (₹ per unit)", min_value=Decimal("0.01"), decimal_places=2)
    fee_pct = forms.DecimalField(label="FPO fee (% of the sale, optional)", min_value=Decimal("0"), max_value=Decimal("15"), decimal_places=2, initial=0, required=False)
    collect_by = date_field("Collect shares until", required=False)
    description = forms.CharField(label="Note for buyers (optional)", max_length=300, required=False)

    def __init__(self, *args, products=(), **kw):
        super().__init__(*args, **kw)
        self.fields["product"].choices = [(k, tr(self.lang, catalog.name(k))) for k in products]


def _org(request):
    u = request.user
    if not u.is_authenticated or u.role != Role.AGENT:
        return None
    m = OrgMembership.objects.filter(user=u).select_related("organisation").first()
    return m.organisation if m else None


def _members(org):
    return list(User.objects.filter(farmer_profile__organisation=org, farmer_profile__org_status__in=["confirmed", "pending"]))


def fpo_list(request):
    org = _org(request)
    if org is None:
        return redirect("/login/?as=fpo")
    lines = stock.lines(_members(org))
    products = sorted({ln["product"] for ln in lines} | set(CROPS)) if lines else list(CROPS)
    have = {}
    for ln in lines:
        have[ln["product"]] = have.get(ln["product"], Decimal(0)) + ln["free_kg"]
    form = PoolForm(request.POST or None, lang=request.lang, products=sorted(have, key=lambda k: -have[k]) + [p for p in products if p not in have])
    if request.method == "POST" and form.is_valid():
        try:
            p = pools.create(request.user, org, form.cleaned_data)
            ok(request, "Lot started. Now add members' stock.")
            return redirect(f"/fpo/pools/{p.pk}/")
        except ApiError as e:
            form.add_error(None, error_text(request, e))
    rows = Pool.objects.filter(organisation=org).prefetch_related("shares")
    for p in rows:
        p.total_kg = pools.confirmed_kg(p)
        p.n = p.shares.filter(status="confirmed").count()
    return render(request, "web/pools/fpo_list.html", {"rows": rows, "form": form, "have": sorted(have.items(), key=lambda kv: -kv[1])[:8], "org": org})


def fpo_detail(request, pk):
    org = _org(request)
    pool = get_object_or_404(Pool, pk=pk, organisation=org) if org else None
    if pool is None:
        raise Http404
    shares = pool.shares.select_related("farmer__farmer_profile", "crop_cycle")
    in_pool = {s.crop_cycle_id for s in shares if s.status != "withdrawn"}
    candidates = [ln for ln in stock.lines(_members(org), crop=pool.product) if ln["cycle"].pk not in in_pool and ln["free_kg"] > 0]
    per = pools.per_unit_kg(pool.unit)
    for ln in candidates:
        ln["free_unit"] = (ln["free_kg"] / per).quantize(Decimal("0.01"))
    total = pools.confirmed_kg(pool)
    return render(request, "web/pools/fpo_detail.html", {"pool": pool, "shares": shares, "candidates": candidates, "total_kg": total, "total_unit": (total / per).quantize(Decimal("0.01")),
                                                         "value": ((total / per) * pool.price).quantize(Decimal("1")), "per": per, "org": org})


@require_POST
def fpo_act(request, pk, action):
    org = _org(request)
    pool = get_object_or_404(Pool, pk=pk, organisation=org) if org else None
    if pool is None:
        raise Http404
    P = request.POST
    try:
        if action == "add":
            cycle = get_object_or_404(CropCycle, pk=P.get("cycle"))
            pools.add_share(pool, cycle, Decimal(P.get("qty") or "0") * pools.per_unit_kg(pool.unit), request.user)
            ok(request, "Added. Members confirm on their phone; FPO-managed members are added straight away.")
        elif action == "withdraw":
            pools.withdraw(get_object_or_404(PoolShare, pk=P.get("share"), pool=pool), request.user)
        elif action == "publish":
            pools.publish(pool, request.user)
            ok(request, "The lot is listed in the marketplace.")
        elif action == "settle":
            pools.settle(pool, request.user, Decimal(P.get("sold") or "0") * pools.per_unit_kg(pool.unit), Decimal(P.get("price") or "0"), P.get("buyer", ""))
            ok(request, "Sold. Each member's share is written in their Farmer Book. Mark each one paid when you pay them.")
        elif action == "paid":
            pools.mark_paid(get_object_or_404(PoolShare, pk=P.get("share"), pool=pool), request.user)
        elif action == "cancel" and pool.status in ("open", "listed"):
            pool.status = "cancelled"
            pool.save()
            if pool.listing:
                pool.listing.status = "paused"
                pool.listing.save()
        else:
            raise Http404
    except (ApiError, InvalidOperation) as e:
        warn(request, error_text(request, e) if isinstance(e, ApiError) else "Enter a quantity more than zero.")
    return redirect(f"/fpo/pools/{pool.pk}/")


def farmer_pools(request):
    u = request.user
    if not u.is_authenticated or u.role != Role.FARMER:
        return redirect("/login/?as=farmer")
    fp = u.farmer_profile
    mine = PoolShare.objects.filter(farmer=u).select_related("pool__organisation", "crop_cycle")
    open_ = []
    if fp.organisation_id and fp.org_status == "confirmed":
        joined = {s.pool_id for s in mine if s.status != "withdrawn"}
        for p in Pool.objects.filter(organisation_id=fp.organisation_id, status__in=pools.ACTIVE).exclude(pk__in=joined):
            lines = stock.lines(u, crop=p.product)
            if lines:
                per = pools.per_unit_kg(p.unit)
                p.lines = [{**ln, "free_unit": (ln["free_kg"] / per).quantize(Decimal("0.01"))} for ln in lines if ln["free_kg"] > 0]
                if p.lines:
                    open_.append(p)
    for s in mine:
        s.unit_qty = (s.quantity_kg / pools.per_unit_kg(s.pool.unit)).quantize(Decimal("0.01"))
    return render(request, "web/pools/farmer.html", {"mine": mine, "open": open_})


@require_POST
def farmer_act(request, action):
    u = request.user
    if not u.is_authenticated or u.role != Role.FARMER:
        raise Http404
    P = request.POST
    try:
        if action == "join":
            pool = get_object_or_404(Pool, pk=P.get("pool"))
            cycle = get_object_or_404(CropCycle, pk=P.get("cycle"), owner=u)
            pools.add_share(pool, cycle, Decimal(P.get("qty") or "0") * pools.per_unit_kg(pool.unit), u)
            ok(request, "You are in the group lot. Your stock stays in your book until it sells.")
        elif action in ("yes", "no"):
            pools.answer(get_object_or_404(PoolShare, pk=P.get("share"), farmer=u), u, action == "yes")
            ok(request, "Saved.")
        elif action == "withdraw":
            pools.withdraw(get_object_or_404(PoolShare, pk=P.get("share"), farmer=u), u)
            ok(request, "Saved.")
        else:
            raise Http404
    except (ApiError, InvalidOperation) as e:
        warn(request, error_text(request, e) if isinstance(e, ApiError) else "Enter a quantity more than zero.")
    return redirect("/farmer/pools/")
