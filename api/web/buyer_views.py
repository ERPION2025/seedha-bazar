from django.shortcuts import redirect, render

from accounts.models import Role
from market.models import Enquiry, Listing

from . import location
from .forms import BuyerProfileForm
from .helpers import ok, role_required
from .market_views import card
from .rates_views import rate_context

buyer_only = role_required(Role.BUYER)


@buyer_only
def home(request):
    bp = request.user.buyer_profile
    loc = location.current(request)
    qs = Listing.live().select_related("organisation", "seller__farmer_profile")
    near = qs.filter(state__iexact=loc["state"]) if loc.get("state") else qs
    memo: dict = {}
    enquiries = Enquiry.objects.filter(buyer=request.user)
    ctx = {"profile": bp, "listings": [card(li, memo) for li in near.order_by("-created_at")[:6]], "near": bool(loc.get("state")),
           "open_enquiries": enquiries.filter(status__in=["new", "accepted"]).count(), "accepted": enquiries.filter(status="accepted").count(), **rate_context(request)}
    return render(request, "web/buyer/home.html", ctx)


@buyer_only
def profile(request):
    bp = request.user.buyer_profile
    initial = {"contact_name": bp.contact_name, "business_name": bp.business_name, "business_type": bp.business_type, "city": bp.city, "gstin": bp.gstin, "fssai": bp.fssai}
    form = BuyerProfileForm(request.POST or None, initial=initial, lang=request.lang)
    if request.method == "POST" and form.is_valid():
        for k, v in form.cleaned_data.items():
            setattr(bp, k, v)
        bp.save()
        ok(request, "Saved.")
        return redirect("/buyer/")
    return render(request, "web/buyer/profile.html", {"form": form, "profile": bp})
