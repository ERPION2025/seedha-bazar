import csv
from datetime import timedelta

from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import audit
from accounts.errors import ApiError
from accounts.models import AuditEvent, Role, User, UserStatus
from profiles import services
from profiles.models import FarmerProfile, Organisation

from . import forms as f
from .fpo_views import farmer_data
from .helpers import error_text, ok, role_required
from .models import Lead

staff_only = role_required(staff=True)


@staff_only
def dashboard(request):
    week = timezone.now() - timedelta(days=7)
    farmers = FarmerProfile.objects.filter(user__status=UserStatus.ACTIVE)
    ctx = {
        "farmers": farmers.count(), "farmers_week": farmers.filter(user__date_joined__gte=week).count(),
        "waiting": User.objects.filter(role=Role.FARMER, status=UserStatus.PENDING).count(),
        "buyers": User.objects.filter(role=Role.BUYER, status=UserStatus.ACTIVE).count(),
        "orgs_verified": Organisation.objects.filter(verified=True).count(),
        "leads_week": Lead.objects.filter(created_at__gte=week).count(),
        "to_verify": Organisation.objects.filter(verified=False).order_by("-created_at"),
        "districts": farmers.values("district").annotate(n=Count("pk")).order_by("-n")[:6],
        "recent_leads": Lead.objects.all()[:5],
    }
    return render(request, "web/console/dashboard.html", ctx)


@staff_only
def orgs(request):
    return render(request, "web/console/orgs.html", {"orgs": Organisation.objects.annotate(members=Count("farmers")).order_by("verified", "name")})


@staff_only
@require_POST
def verify_org(request, pk):
    org = get_object_or_404(Organisation, pk=pk)
    org.verified = request.POST.get("verified") == "1"
    org.save(update_fields=["verified"])
    audit.log("org_verified" if org.verified else "org_unverified", actor=request.user, target=org, request=request)
    ok(request, "Saved.")
    return redirect(request.POST.get("back") if request.POST.get("back") in ("/console/", "/console/orgs/") else "/console/orgs/")


@staff_only
def new_org(request):
    form = f.ConsoleOrgForm(request.POST or None, lang=request.lang)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        org = Organisation.objects.create(
            name=d["name"], kind=d["kind"], code=services.make_org_code(d["name"]), district=d["district"], block=d["block"],
            registration_no=d["registration_no"], contact_name=d["contact_name"], verified=d["verified"],
        )
        try:
            services.provision_agent(d["agent_phone"], org, request.user, request)
        except ApiError as e:
            org.delete()
            form.add_error("agent_phone", error_text(request, e))
        else:
            audit.log("org_created_by_staff", actor=request.user, target=org, request=request)
            ok(request, "Organisation created. Its agent signs in with their own phone code. Join code: {code}", code=org.code)
            return redirect("/console/orgs/")
    return render(request, "web/console/new_org.html", {"form": form})


@staff_only
def farmers(request):
    q = (request.GET.get("q") or "").strip()
    qs = FarmerProfile.objects.select_related("user", "organisation").order_by("-updated_at")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(village__icontains=q) | Q(district__icontains=q) | Q(user__phone__icontains=q))
    return render(request, "web/console/farmers.html", {"rows": qs[:300], "q": q})


@staff_only
def add_farmer(request):
    form = f.ConsoleAddFarmerForm(request.POST or None, lang=request.lang)
    if request.method == "POST" and form.is_valid():
        org = get_object_or_404(Organisation, pk=form.cleaned_data["organisation"])
        data = farmer_data({k: v for k, v in form.cleaned_data.items() if k != "organisation"})
        try:
            services.create_assisted_farmer(request.user, data, request, org=org)
        except ApiError as e:
            form.add_error("phone" if e.code == "already_registered" else None, error_text(request, e))
        else:
            ok(request, "Added. A code was sent to the farmer's phone. The farmer confirms it to activate the account.")
            return redirect("/console/farmers/")
    return render(request, "web/console/add_farmer.html", {"form": form})


@staff_only
def leads(request):
    kind = request.GET.get("kind", "")
    qs = Lead.objects.all()
    if kind in Lead.Kind.values:
        qs = qs.filter(kind=kind)
    if request.GET.get("format") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="seedha-bazar-leads.csv"'
        w = csv.writer(resp)
        w.writerow(["when", "type", "name", "phone", "city", "message", "language", "source", "medium", "campaign"])
        for ld in qs[:5000]:
            a = ld.attribution or {}
            w.writerow([ld.created_at.isoformat(), ld.kind, ld.name, ld.phone, ld.city, ld.message, ld.language, a.get("utm_source", ""), a.get("utm_medium", ""), a.get("utm_campaign", "")])
        return resp
    return render(request, "web/console/leads.html", {"rows": qs[:200], "kind": kind, "kinds": Lead.Kind.choices})


@staff_only
def audit_log(request):
    return render(request, "web/console/audit.html", {"rows": AuditEvent.objects.select_related("actor")[:150]})


@staff_only
def listings(request):
    from market.models import Listing

    status = request.GET.get("status", "")
    qs = Listing.objects.select_related("seller", "organisation")
    if status in Listing.Status.values:
        qs = qs.filter(status=status)
    return render(request, "web/console/listings.html", {"rows": qs[:200], "status": status, "statuses": Listing.Status.choices})


@staff_only
@require_POST
def listing_visibility(request, pk):
    from market.models import Listing

    li = get_object_or_404(Listing, pk=pk)
    li.status = Listing.Status.HIDDEN if request.POST.get("hide") == "1" else Listing.Status.ACTIVE
    li.save()
    audit.log("listing_hidden" if li.status == "hidden" else "listing_restored", actor=request.user, target=li, request=request)
    ok(request, "Saved.")
    return redirect("/console/listings/")


@staff_only
def buyers(request):
    from profiles.models import BuyerProfile

    return render(request, "web/console/buyers.html", {"rows": BuyerProfile.objects.select_related("user").order_by("-updated_at")[:200]})


@staff_only
@require_POST
def verify_buyer(request, pk):
    from profiles.models import BuyerProfile

    bp = get_object_or_404(BuyerProfile, pk=pk)
    bp.documents_verified = request.POST.get("verified") == "1"
    bp.save()
    audit.log("buyer_verified" if bp.documents_verified else "buyer_unverified", actor=request.user, target=bp, request=request)
    ok(request, "Saved.")
    return redirect("/console/buyers/")


@staff_only
def messages_log(request):
    from notify.models import Message

    return render(request, "web/console/messages.html", {"rows": Message.objects.all()[:150]})


@staff_only
def rates_status(request):
    from django.conf import settings

    from rates.models import MarketRate, MspPrice, RateFetchLog
    from rates import services as rate_services

    return render(request, "web/console/rates.html", {
        "logs": RateFetchLog.objects.all()[:15], "key_set": bool(settings.DATA_GOV_IN_API_KEY), "rows": MarketRate.objects.exclude(source="demo").count(),
        "demo_rows": MarketRate.objects.filter(source="demo").count(), "latest": MarketRate.objects.exclude(source="demo").order_by("-date").values_list("date", flat=True).first(),
        "msp": MspPrice.objects.count(), "updated": rate_services.last_update(), "hours": settings.RATES_REFRESH_HOURS,
    })


@staff_only
@require_POST
def rates_refresh(request):
    """Start a fetch in the background so the page returns at once."""
    import threading

    from rates import ingest

    threading.Thread(target=ingest.run_update, daemon=True).start()
    audit.log("rates_refresh_started", actor=request.user, request=request)
    ok(request, "Fetching rates now. Reload this page in a minute.")
    return redirect("/console/rates/")


# ---------- news engine and announcements ----------
@staff_only
def knowledge_status(request):
    from knowledge.models import Announcement, Article, Scheme, Source, Video

    sources = Source.objects.annotate(n=Count("articles")).order_by("-active", "-trust", "name")
    recent = Article.objects.order_by("-fetched_at")[:30]
    return render(request, "web/console/knowledge.html", {
        "sources": sources, "recent": recent, "articles": Article.objects.filter(hidden=False).count(), "videos": Video.objects.count(),
        "schemes": Scheme.objects.filter(active=True).count(), "hidden": Article.objects.filter(hidden=True).count(),
        "last": Source.objects.exclude(last_run=None).order_by("-last_run").values_list("last_run", flat=True).first(),
        "announcements": Announcement.objects.all()[:20], "form": f.AnnouncementForm(lang=request.lang),
    })


@staff_only
@require_POST
def knowledge_refresh(request):
    import threading

    from django.db import connection

    from knowledge import engine

    def run():
        try:
            engine.run_all()
        finally:
            connection.close()

    threading.Thread(target=run, daemon=True).start()
    audit.log("news_refresh_started", actor=request.user, request=request)
    ok(request, "Reading the news feeds now. Reload this page in a minute.")
    return redirect("/console/news/")


@staff_only
@require_POST
def knowledge_toggle(request, what, pk):
    from knowledge.models import Article, Source, Video

    model = {"source": Source, "article": Article, "video": Video}.get(what)
    if model is None:
        return redirect("/console/news/")
    obj = get_object_or_404(model, pk=pk)
    if what == "source":
        obj.active = not obj.active
        obj.save(update_fields=["active"])
    else:
        obj.hidden = not obj.hidden
        obj.save(update_fields=["hidden"])
    audit.log(f"{what}_toggled", actor=request.user, target=obj, request=request)
    ok(request, "Saved.")
    return redirect("/console/news/")


@staff_only
@require_POST
def announcement_save(request):
    from knowledge.models import Announcement

    form = f.AnnouncementForm(request.POST, lang=request.lang)
    if form.is_valid():
        a = Announcement.objects.create(created_by=request.user, **form.cleaned_data)
        audit.log("announcement_posted", actor=request.user, target=a, request=request)
        ok(request, "Announcement posted.")
    else:
        messages.error(request, "; ".join(str(e) for errs in form.errors.values() for e in errs))
    return redirect("/console/news/")


@staff_only
@require_POST
def announcement_end(request, pk):
    from knowledge.models import Announcement

    a = get_object_or_404(Announcement, pk=pk)
    a.ends_at = timezone.now()
    a.save(update_fields=["ends_at"])
    ok(request, "Announcement taken down.")
    return redirect("/console/news/")


# ---------- KVKs and research centres ----------
@staff_only
def centres(request):
    from extension.models import Centre

    form = f.CentreForm(request.POST or None, lang=request.lang)
    if request.method == "POST" and request.POST.get("form") == "centre" and form.is_valid():
        d = dict(form.cleaned_data)
        d["districts"] = [x.strip() for x in d["districts"].split(",") if x.strip()]
        c = Centre.objects.create(**d)
        audit.log("centre_created", actor=request.user, target=c, request=request)
        ok(request, "Saved.")
        return redirect("/console/centres/")
    rows = Centre.objects.prefetch_related("members__user").order_by("state", "name")
    return render(request, "web/console/centres.html", {"rows": rows, "form": form, "staff_form": f.CentreStaffForm(lang=request.lang)})


@staff_only
@require_POST
def centre_staff(request, pk):
    from extension import services as ext
    from extension.models import Centre

    c = get_object_or_404(Centre, pk=pk)
    form = f.CentreStaffForm(request.POST, lang=request.lang)
    if form.is_valid():
        try:
            ext.provision_staff(form.cleaned_data["phone"], c, form.cleaned_data["role"], form.cleaned_data["speciality"], request.user, request)
            ok(request, "Saved. They sign in at /login/?as=kvk with their own phone code.")
        except ApiError as e:
            messages.error(request, error_text(request, e))
    else:
        messages.error(request, "; ".join(str(e) for errs in form.errors.values() for e in errs))
    return redirect("/console/centres/")


# ---------- settings: user policies, integrations, sessions ----------
@staff_only
def site_settings(request):
    from accounts.models import SitePolicy

    from . import integrations

    policy = SitePolicy.current()
    form = f.PolicyForm(request.POST or None, lang=request.lang, initial={"max_sessions": policy.max_sessions, "session_days": policy.session_days,
                                                                         "facebook_login": policy.facebook_login})
    if request.method == "POST" and form.is_valid():
        for k, v in form.cleaned_data.items():
            setattr(policy, k, v)
        policy.updated_by = request.user
        policy.save()
        audit.log("policy_changed", actor=request.user, target=policy, request=request, **{k: str(v) for k, v in form.cleaned_data.items()})
        if request.POST.get("apply_now"):
            from accounts import sessions
            from accounts.models import LoginSession
            for uid in set(LoginSession.objects.filter(ended_at__isnull=True).values_list("user_id", flat=True)):
                sessions.enforce(User.objects.get(pk=uid), policy.max_sessions)
        ok(request, "Saved.")
        return redirect("/console/settings/")
    return render(request, "web/console/settings.html", {"form": form, "policy": policy, "integrations": integrations.status()})


@staff_only
def login_sessions(request):
    from accounts.models import LoginSession

    q = (request.GET.get("q") or "").strip()
    rows = LoginSession.objects.select_related("user")
    if q:
        rows = rows.filter(user__phone__icontains=q)
    if request.GET.get("active"):
        rows = rows.filter(ended_at__isnull=True)
    return render(request, "web/console/sessions.html", {"rows": rows[:300], "q": q, "active": request.GET.get("active", "")})


@staff_only
@require_POST
def end_session(request, pk):
    from accounts import sessions
    from accounts.models import LoginSession

    ls = get_object_or_404(LoginSession, pk=pk, ended_at__isnull=True)
    sessions.end(ls, "staff")
    audit.log("session_ended_by_staff", actor=request.user, target=ls.user, request=request)
    ok(request, "Signed out.")
    return redirect(request.POST.get("back") if (request.POST.get("back") or "").startswith("/console/") else "/console/sessions/")


# ---------- data feeds: WDRA warehouses, mKisan advisories, IMD warnings ----------
@staff_only
def feeds(request):
    from django.conf import settings

    from advisory.models import Advisory, FeedRun
    from storage import wdra
    from storage.models import Warehouse

    if request.method == "POST":
        what = request.POST.get("feed")
        if what == "mkisan":
            from advisory import mkisan
            out = mkisan.sync()
            ok(request, "Read {n} posts, {m} new.", n=out["fetched"], m=out["saved"])
        elif what == "wdra" and request.POST.get("state"):
            runs = wdra.sync_states([request.POST["state"]], pause=0)
            r = runs[0] if runs else None
            if r and r.ok:
                ok(request, "Read {n} warehouses, {m} new.", n=r.rows, m=r.added)
            else:
                messages.error(request, (r.error if r else "Unknown state") or "Failed")
        return redirect("/console/feeds/")
    from django.db.models import Count
    return render(request, "web/console/feeds.html", {
        "wdra": wdra.status(), "wdra_total": Warehouse.objects.filter(source="wdra").count(), "wdra_active": Warehouse.objects.filter(source="wdra", wdra_status__iexact="Active").count(),
        "states": __import__("extension.geo", fromlist=["states"]).states(), "refresh_days": settings.WDRA_REFRESH_DAYS,
        "runs": FeedRun.objects.all()[:15], "imd_on": settings.IMD_API_ENABLED, "mkisan_on": settings.MKISAN_ENABLED,
        "by_source": list(Advisory.objects.values("source").annotate(n=Count("id"), placed=Count("id", filter=~Q(district=""))).order_by("source")),
    })
