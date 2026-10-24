"""The bell: every notice a person gets, in one list. Also notification settings, the one-time question about phone
notifications, phone notifications (Web Push), the installable app manifest, and the Meta (Messenger) webhook."""
import hashlib
import hmac
import json

from django.conf import settings
from django.core import signing
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import User
from notify import push
from notify.models import InboxItem, Preference, PushSubscription

from .helpers import ok
from .market_views import base_for

SALT = "messenger-link"


def _pref(user) -> Preference:
    return Preference.objects.get_or_create(user=user)[0]


def inbox(request):
    """What the bell opens: newest first, unread marked, with a filter by kind."""
    if not request.user.is_authenticated:
        return redirect("/login/?next=/notifications/")
    qs = InboxItem.objects.filter(user=request.user)
    kinds = [(k, label) for k, label in InboxItem.Kind.choices if qs.filter(kind=k).exists()]
    kind = request.GET.get("kind", "")
    if kind in InboxItem.Kind.values:
        qs = qs.filter(kind=kind)
    return render(request, "web/inbox.html", {"rows": qs[:100], "kinds": kinds, "kind": kind, "base_tpl": base_for(request.user),
                                              "unread_n": InboxItem.objects.filter(user=request.user, read_at__isnull=True).count()})


def open_item(request, pk):
    item = InboxItem.objects.filter(pk=pk, user=request.user).first() if request.user.is_authenticated else None
    if item is None:
        return redirect("/notifications/")
    if item.read_at is None:
        item.read_at = timezone.now()
        item.save(update_fields=["read_at"])
    url = item.url if item.url.startswith("/") and not item.url.startswith("//") else ""
    return redirect(url or "/notifications/")


@require_POST
def read_all(request):
    if request.user.is_authenticated:
        InboxItem.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return redirect("/notifications/")


def unread(request):
    """For the bell's badge, checked every minute while the app is open; new items can also pop up as phone notifications."""
    if not request.user.is_authenticated:
        return JsonResponse({"unread": 0, "items": []})
    try:
        after = int(request.GET.get("after", "0"))
    except ValueError:
        after = 0
    qs = InboxItem.objects.filter(user=request.user, read_at__isnull=True)
    items = [{"id": i.pk, "title": i.title, "text": i.text, "url": f"/notifications/{i.pk}/", "critical": i.critical} for i in qs.filter(pk__gt=after).order_by("pk")[:5]]
    last = InboxItem.objects.filter(user=request.user).order_by("-pk").values_list("pk", flat=True).first() or 0
    return JsonResponse({"unread": qs.count(), "items": items, "last": last})


@require_POST
def prompt_answer(request):
    """The one-time question 'Turn on notifications on this phone?' was answered. It is not asked again."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "sign_in"}, status=401)
    pref = _pref(request.user)
    answer = request.POST.get("answer", "")
    pref.prompt_answer = answer if answer in ("yes", "no") else "no"
    pref.prompted_at = timezone.now()
    if pref.prompt_answer == "yes":
        pref.push = True
    pref.save(update_fields=["prompt_answer", "prompted_at", "push"])
    return JsonResponse({"ok": True})


def page(request):
    """Notification settings."""
    if not request.user.is_authenticated:
        return redirect("/login/?next=/notifications/settings/")
    pref = _pref(request.user)
    if request.method == "POST":
        pref.alarm_sound = request.POST.get("alarm_sound") == "1"
        pref.whatsapp = request.POST.get("whatsapp") == "1"
        pref.sms = request.POST.get("sms") == "1"
        pref.save()
        ok(request, "Saved.")
        return redirect("/notifications/settings/")
    m_link = ""
    if settings.FACEBOOK_PAGE_ID:
        m_link = f"https://m.me/{settings.FACEBOOK_PAGE_ID}?ref=" + signing.dumps(request.user.pk, salt=SALT)
    return render(request, "web/notifications.html", {"pref": pref, "push_ready": push.configured(), "vapid": settings.VAPID_PUBLIC_KEY,
                                                      "devices": PushSubscription.objects.filter(user=request.user).count(), "messenger_link": m_link,
                                                      "whatsapp_ready": "WhatsAppCloud" in settings.NOTIFY_BACKENDS.get("whatsapp", ""),
                                                      "base_tpl": base_for(request.user)})


@require_POST
def subscribe(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "sign_in"}, status=401)
    try:
        d = json.loads(request.body)
        endpoint, keys = d["endpoint"], d["keys"]
        if not endpoint.startswith("https://"):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"error": "bad"}, status=400)
    PushSubscription.objects.update_or_create(endpoint=endpoint[:600], defaults={"user": request.user, "p256dh": keys["p256dh"][:200], "auth": keys["auth"][:100],
                                                                                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:200]})
    pref = _pref(request.user)
    pref.push = True
    pref.save(update_fields=["push"])
    return JsonResponse({"ok": True})


@require_POST
def test_push(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "sign_in"}, status=401)
    from .i18n import tr
    n = push.send(request.user, "Seedha Bazar", tr(request.lang, "Notifications are working. You will hear about weather, prices and orders here."), "/notifications/")
    return JsonResponse({"sent": n})


def manifest(request):
    """Lets phones install Seedha Bazar like an app (Add to Home Screen)."""
    data = {"name": "Seedha Bazar", "short_name": "Seedha Bazar", "start_url": "/?source=app", "scope": "/", "display": "standalone",
            "background_color": "#fbf9f4", "theme_color": "#14532d", "lang": "hi",
            "icons": [{"src": static("web/icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
                      {"src": static("web/icons/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]}
    return JsonResponse(data, content_type="application/manifest+json")


SW = """/* Seedha Bazar service worker: shows notifications and opens the right page when tapped. */
self.addEventListener("push", function (e) {
  var d = {}; try { d = e.data.json(); } catch (x) { d = { title: "Seedha Bazar", body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "Seedha Bazar", {
    body: d.body || "", tag: d.tag || "seedha", renotify: true, requireInteraction: !!d.critical,
    icon: "%(icon)s", badge: "%(badge)s", vibrate: d.critical ? [400, 200, 400, 200, 800] : [200, 100, 200], data: { url: d.url || "/" }
  }));
});
self.addEventListener("notificationclick", function (e) {
  e.notification.close();
  var url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (list) {
    for (var i = 0; i < list.length; i++) { if ("focus" in list[i]) { list[i].navigate(url); return list[i].focus(); } }
    return clients.openWindow(url);
  }));
});
self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (e) { e.waitUntil(self.clients.claim()); });
"""


def service_worker(request):
    resp = HttpResponse(SW % {"icon": static("web/icons/icon-192.png"), "badge": static("web/icons/badge-72.png")}, content_type="application/javascript")
    resp["Service-Worker-Allowed"] = "/"
    resp["Cache-Control"] = "no-cache"
    return resp


@csrf_exempt
def meta_webhook(request):
    """Messenger: Meta checks the URL with GET; POSTs bring messages. A message that came from our m.me link carries a signed ref
    with the user's id, which links their Messenger id (PSID). Every message also restarts Meta's 24-hour window."""
    if request.method == "GET":
        if request.GET.get("hub.mode") == "subscribe" and settings.META_VERIFY_TOKEN and request.GET.get("hub.verify_token") == settings.META_VERIFY_TOKEN:
            return HttpResponse(request.GET.get("hub.challenge", ""))
        return HttpResponse(status=403)
    sig = request.META.get("HTTP_X_HUB_SIGNATURE_256", "")
    expected = "sha256=" + hmac.new(settings.FACEBOOK_APP_SECRET.encode(), request.body, hashlib.sha256).hexdigest() if settings.FACEBOOK_APP_SECRET else ""
    if not expected or not hmac.compare_digest(sig, expected):
        return HttpResponse(status=403)
    try:
        body = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    for entry in body.get("entry", []):
        for ev in entry.get("messaging", []):
            psid = (ev.get("sender") or {}).get("id")
            if not psid:
                continue
            ref = (ev.get("referral") or {}).get("ref") or ((ev.get("postback") or {}).get("referral") or {}).get("ref") or ((ev.get("optin") or {}).get("ref"))
            if ref:
                try:
                    uid = signing.loads(ref, salt=SALT, max_age=7 * 86400)
                except signing.BadSignature:
                    uid = None
                if uid and User.objects.filter(pk=uid).exists():
                    Preference.objects.update_or_create(user_id=uid, defaults={"messenger_psid": psid, "messenger_last_in": timezone.now()})
                    continue
            Preference.objects.filter(messenger_psid=psid).update(messenger_last_in=timezone.now())
    return HttpResponse("ok")
