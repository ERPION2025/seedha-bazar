from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import audit
from accounts.errors import ApiError
from accounts.models import Role
from farmerbook import serializers as fb
from farmerbook.models import Activity, CropCycle, Expense, Harvest, Plot, Sale
from farmerbook.views import cycle_summary, ledger_for, stock_for
from profiles import services
from profiles.models import Organisation, OrgStatus

from . import forms as f
from .helpers import error_text, ok, payload, role_required, warn
from .rates_views import rate_context

farmer_only = role_required(Role.FARMER)

KINDS = {  # record kind -> (form, serializer, model)
    "expense": (f.ExpenseForm, fb.ExpenseSerializer, Expense),
    "harvest": (f.HarvestForm, fb.HarvestSerializer, Harvest),
    "sale": (f.SaleForm, fb.SaleSerializer, Sale),
    "task": (f.TaskForm, fb.ActivitySerializer, Activity),
}


def get_cycle(request, cid) -> CropCycle:
    c = CropCycle.objects.filter(owner=request.user, client_id=cid, deleted_at__isnull=True).select_related("plot").first()
    if c is None:
        raise Http404
    return c


def next_step(fp, cycles_count, has_records):
    """The one thing to do next. This is what makes the home page feel like it runs itself."""
    if fp.level == 0:
        return {"title": "Complete your profile", "text": "It takes one minute. Buyers and your FPO will know who you are.", "url": "/farmer/profile/", "button": "Complete profile"}
    if fp.org_status == OrgStatus.NONE:
        return {"title": "Join your FPO or NGO", "text": "Members of a verified group reach buyers sooner. Ask your FPO for its code or link.", "url": "/farmer/fpo/", "button": "Find my FPO"}
    if cycles_count == 0:
        return {"title": "Add your first crop", "text": "Start your Farmer Book. Costs, harvest and sales all in one place.", "url": "/farmer/book/new/", "button": "Add crop"}
    if not has_records:
        return {"title": "Write down today's work", "text": "Add an expense, so you can see your profit at the end of the season.", "url": "/farmer/book/", "button": "Open my book"}
    return None


@farmer_only
def home(request):
    fp = request.user.farmer_profile
    cycles = CropCycle.objects.filter(owner=request.user, deleted_at__isnull=True)
    has_records = Expense.objects.filter(owner=request.user, deleted_at__isnull=True).exists() or Harvest.objects.filter(owner=request.user, deleted_at__isnull=True).exists()
    today = timezone.localdate()
    tasks = Activity.objects.filter(owner=request.user, deleted_at__isnull=True, done=False).select_related("crop_cycle").order_by("date")[:5]
    ctx = {
        "fp": fp, "step": next_step(fp, cycles.count(), has_records), "ledger": ledger_for(request.user)["totals"],
        "stock": stock_for(request.user)[:4], "tasks": tasks, "today": today, "cycle_count": cycles.count(),
        "quick": cycles.exclude(status="closed").order_by("-created_at").first(),
        **rate_context(request),
    }
    return render(request, "web/farmer/home.html", ctx)


@farmer_only
def profile(request):
    fp = request.user.farmer_profile
    form = f.FarmerProfileForm(request.POST, lang=request.lang) if request.method == "POST" else f.FarmerProfileForm.from_profile(fp, request.lang)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        for k in ("name", "village", "block", "district", "land_acres"):
            setattr(fp, k, d[k])
        fp.crops = f.split_crops(d["crops"], d["other_crops"])
        fp.save()
        audit.log("farmer_profile_updated", actor=request.user, target=fp, request=request, via="web")
        ok(request, "Profile saved.")
        return redirect("/farmer/")
    return render(request, "web/farmer/profile.html", {"form": form, "fp": fp})


@farmer_only
def fpo(request):
    fp = request.user.farmer_profile
    if request.method == "POST":
        form = f.JoinCodeForm(request.POST, lang=request.lang)
        if form.is_valid():
            try:
                link = services.request_join(fp, form.cleaned_data["code"], request)
            except ApiError as e:
                form.add_error("code", error_text(request, e))
            else:
                if link.status == "approved":
                    ok(request, "You are now a member of {org}.", org=link.organisation.name)
                else:
                    ok(request, "Your request was sent to {org}. They will confirm you.", org=link.organisation.name)
                return redirect("/farmer/fpo/")
    else:
        form = f.JoinCodeForm(lang=request.lang)
    q = (request.GET.get("q") or "").strip()
    orgs = Organisation.objects.filter(verified=True)
    if q:
        orgs = orgs.filter(name__icontains=q) | orgs.filter(district__icontains=q)
    pending = fp.link_requests.filter(status="pending").select_related("organisation")
    return render(request, "web/farmer/fpo.html", {"fp": fp, "form": form, "orgs": orgs.order_by("name")[:20], "q": q, "pending": pending})


@farmer_only
def book(request):
    ledger = ledger_for(request.user)
    return render(request, "web/farmer/book.html", {"ledger": ledger, "stock": {s["crop_cycle"]: s for s in stock_for(request.user)}})


@farmer_only
def new_crop(request):
    fp = request.user.farmer_profile
    form = f.NewCropForm(request.POST or None, lang=request.lang, initial={"area_acres": fp.land_acres})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        plot = Plot.objects.filter(owner=request.user, name=d["field_name"], deleted_at__isnull=True).first()
        if plot is None:
            plot = Plot.objects.create(owner=request.user, name=d["field_name"], area_acres=d["area_acres"])
        cycle = CropCycle(owner=request.user, plot=plot, crop=form.crop_name(), season=d["season"],
                          sowing_date=d["sowing_date"], expected_harvest_date=d["expected_harvest_date"])
        cycle.save()
        if cycle.expected_harvest_date:
            Activity.objects.create(owner=request.user, crop_cycle=cycle, kind="harvest", date=cycle.expected_harvest_date, note="", done=False)
        ok(request, "Crop added to your book.")
        return redirect(f"/farmer/book/{cycle.client_id}/")
    return render(request, "web/farmer/new_crop.html", {"form": form})


def _timeline(cycle, owner):
    rows = []
    for e in Expense.objects.filter(owner=owner, crop_cycle=cycle, deleted_at__isnull=True):
        rows.append({"kind": "expense", "date": e.date, "label": e.get_category_display(), "amount": e.amount, "note": e.note, "id": e.client_id, "sign": "-"})
    for h in Harvest.objects.filter(owner=owner, crop_cycle=cycle, deleted_at__isnull=True):
        rows.append({"kind": "harvest", "date": h.date, "label": h.get_grade_display(), "qty": h.quantity, "unit": h.unit, "note": h.storage_note, "id": h.client_id})
    for s in Sale.objects.filter(owner=owner, crop_cycle=cycle, deleted_at__isnull=True):
        rows.append({"kind": "sale", "date": s.date, "label": s.get_channel_display(), "qty": s.quantity, "unit": s.unit, "amount": s.amount, "note": s.buyer_note, "id": s.client_id, "sign": "+"})
    for a in Activity.objects.filter(owner=owner, crop_cycle=cycle, deleted_at__isnull=True):
        rows.append({"kind": "task", "date": a.date, "label": a.get_kind_display(), "note": a.note, "done": a.done, "id": a.client_id})
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


@farmer_only
def cycle(request, cid):
    c = get_cycle(request, cid)
    summary = cycle_summary(c)
    return render(request, "web/farmer/cycle.html", {"cycle": c, "s": summary, "rows": _timeline(c, request.user), "today": timezone.localdate()})


@farmer_only
def add_record(request, cid, kind):
    if kind not in KINDS:
        raise Http404
    c = get_cycle(request, cid)
    form_cls, ser_cls, _ = KINDS[kind]
    prefill = {k: request.GET[k] for k in ("quantity", "unit", "rate", "channel", "buyer_note") if k in request.GET} if kind == "sale" and request.method == "GET" else {}
    form = form_cls(request.POST or None, initial=prefill, lang=request.lang)
    if request.method == "POST" and form.is_valid():
        data = payload(form.cleaned_data)
        data["crop_cycle"] = str(c.client_id)
        if kind == "task":
            data["done"] = not data.pop("planned", False)
            data.pop("planned", None)
        s = ser_cls(data=data, context={"request": request})
        try:
            valid = s.is_valid()
        except ApiError as e:  # business rules such as "not enough stock"
            form.add_error(None, error_text(request, e))
        else:
            if valid:
                s.save(owner=request.user)
                if kind == "harvest" and c.status == CropCycle.Status.ACTIVE:
                    c.status = CropCycle.Status.HARVESTED
                    c.save()
                ok(request, "Saved.")
                return redirect(f"/farmer/book/{c.client_id}/")
            for name, errs in s.errors.items():
                for msg in errs:
                    form.add_error(name if name in form.fields else None, str(msg))
    return render(request, "web/farmer/add_record.html", {"form": form, "cycle": c, "kind": kind})


@farmer_only
@require_POST
def delete_record(request, cid, kind, rid):
    c = get_cycle(request, cid)
    if kind not in KINDS:
        raise Http404
    model = KINDS[kind][2]
    rec = model.objects.filter(owner=request.user, crop_cycle=c, client_id=rid, deleted_at__isnull=True).first()
    if rec is None:
        raise Http404
    if kind == "harvest" and fb.stock_kg(c, exclude_harvest=rec) < 0:
        warn(request, "Sales already recorded are more than the remaining harvest. Remove those sales first.")
    else:
        rec.deleted_at = timezone.now()
        rec.save()
        ok(request, "Removed.")
    return redirect(f"/farmer/book/{c.client_id}/")


@farmer_only
@require_POST
def task_done(request, cid, rid):
    c = get_cycle(request, cid)
    a = Activity.objects.filter(owner=request.user, crop_cycle=c, client_id=rid, deleted_at__isnull=True).first()
    if a is None:
        raise Http404
    a.done = True
    a.save()
    return redirect("/farmer/" if request.POST.get("back") == "home" else f"/farmer/book/{c.client_id}/")


@farmer_only
@require_POST
def set_status(request, cid):
    c = get_cycle(request, cid)
    new = request.POST.get("status")
    if new in CropCycle.Status.values:
        c.status = new
        c.save()
        ok(request, "Saved.")
    return redirect(f"/farmer/book/{c.client_id}/")


@farmer_only
def account(request):
    return render(request, "web/farmer/account.html")


@farmer_only
@require_POST
def delete_account(request):
    if request.POST.get("confirm", "").strip().upper() != "DELETE":
        warn(request, "Type DELETE to confirm.")
        return redirect("/farmer/account/")
    services.delete_account(request.user, request)
    from django.contrib.auth import logout
    logout(request)
    return redirect("/")
