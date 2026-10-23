"""Lists every English string the site can show, so tests (and translators) can check coverage."""
import re
from pathlib import Path

HERE = Path(__file__).parent
T_TAG = re.compile(r'\{%\s*t\s+"((?:[^"\\]|\\.)*)"')
BUTTON = re.compile(r'button="([^"]+)"')
CALL = re.compile(r'\b(?:ok|warn)\(\s*request,\s*"((?:[^"\\]|\\.)*)"')
FLASH_ARG = re.compile(r'\btr\([\w.]+,\s*"((?:[^"\\]|\\.)*)"')
ADD_ERROR = re.compile(r'add_error\([^,]+,\s*"((?:[^"\\]|\\.)*)"')
STEP = re.compile(r'"(?:title|text|button)":\s*"((?:[^"\\]|\\.)*)"')
RAISE = re.compile(r'ValidationError\(\s*"((?:[^"\\]|\\.)*)"')
ROW_ERR = re.compile(r'row\["error"\]\s*=\s*"((?:[^"\\]|\\.)*)"|ValueError\("((?:[^"\\]|\\.)*)"\)')
SCAN_PY = ("auth_views.py", "farmer_views.py", "fpo_views.py", "console_views.py", "buyer_views.py", "helpers.py", "public_views.py", "forms.py",
           "rates_views.py", "market_views.py", "location.py", "rate_alerts.py", "catalog_views.py", "knowledge_views.py", "insurance_views.py", "deals_views.py",
           "help_views.py", "../institution/views.py", "inputs_views.py", "engage_views.py",
           "weather_views.py", "pool_views.py", "storage_views.py", "statement_views.py",
           "share_views.py", "notify_views.py", "voice_views.py", "social.py", "group_views.py")


def template_strings() -> set[str]:
    out = set()
    for path in [*(HERE / "templates").rglob("*.html"), *(HERE.parent / "institution" / "templates").rglob("*.html")]:
        text = path.read_text()
        out.update(m for m in T_TAG.findall(text))
        out.update(BUTTON.findall(text))
    return out


def python_strings() -> set[str]:
    out = set()
    for name in SCAN_PY:
        text = (HERE / name).read_text()
        for rx in (CALL, FLASH_ARG, ADD_ERROR, STEP, RAISE):
            out.update(rx.findall(text))
        for a, b in ROW_ERR.findall(text):
            out.add(a or b)
    return out


def form_strings() -> set[str]:
    """Labels, choices and error messages declared on the forms."""
    import inspect

    from django import forms

    from institution import views as kvk_views
    from web import deals_views, group_views, help_views, insurance_views, pool_views
    from web import forms as wf

    out = set()
    classes = {cls for mod in (wf, deals_views, insurance_views, help_views, kvk_views, pool_views, group_views) for _, cls in inspect.getmembers(mod, inspect.isclass)}
    for cls in classes:
        if not issubclass(cls, forms.Form) or cls is forms.Form:
            continue
        try:
            form = cls(lang="en")
        except Exception:
            continue
        for field in form.fields.values():
            if field.label:
                out.add(field.label)
            for v, label in getattr(field, "choices", []) or []:
                if label and not str(label).startswith("-"):
                    out.add(str(label))
            out.update(str(m) for m in field.error_messages.values() if "%" not in str(m) and "{" not in str(m))
    out.update(wf.CROPS.values())
    import catalog

    out.update(v[0] for v in catalog.PRODUCTS.values())
    out.update(v[0] for v in catalog.NEEDS.values())
    from web.translations import API_ERRORS

    out.update(API_ERRORS.values())
    out.update({"kg", "tonne", "bag", "quintal"})  # units shown next to quantities
    from market.models import Enquiry, Listing
    from web.calc_strings import CALC_STRINGS

    out.update(label for _, label in Listing.Status.choices)
    out.update(label for _, label in Enquiry.Status.choices)
    out.update(label for _, label in Listing.Grade.choices)
    out.update(CALC_STRINGS)
    from web.voice_strings import VOICE_STRINGS

    out.update(VOICE_STRINGS)
    from web.market_views import KIND_TABS

    out.update(label for _, label in KIND_TABS)
    from web.knowledge_views import SCHEME_TOPICS, TOPIC_TABS
    from web.templatetags.web_tags import TOPIC_LABELS

    out.update(label for _, label in TOPIC_TABS + SCHEME_TOPICS)
    out.update(TOPIC_LABELS.values())
    from insurance import rules as ins_rules
    from insurance import services as ins_services
    from insurance.models import Application as InsApp, Plan as InsPlan
    from web.insurance_views import LOSS_CAUSES

    out.update(ins_rules.RISKS.values())
    from deals.models import Deal, DealEvent, Payment

    for choices in (Deal.Status.choices, DealEvent.Kind.choices, Payment.Kind.choices, Payment.Method.choices):
        out.update(label for _, label in choices)
    out.update(DEAL_TEXTS)
    from engagement import games as eg
    from extension.models import Centre, CentreMember, InputOffer, InputRequest
    from issues.models import Issue, Reply
    from web import menus
    from web.context import MAP_TEXT

    out.update(eg.ui_strings())
    out.update(label for rows in (menus.FARMER, menus.FPO, menus.BUYER, menus.KVK, menus.STAFF, menus.PUBLIC) for label, *_ in rows)
    for choices in (Issue.Category.choices, Issue.Status.choices, Reply.Kind.choices, InputOffer.Kind.choices, InputOffer.Audience.choices, InputRequest.Status.choices,
                    Centre.Kind.choices, CentreMember.Role.choices):
        out.update(label for _, label in choices)
    out.update(MAP_TEXT.values())
    out.update(SCORE_TEXTS + ISSUE_TEXTS + SHARE_TEXTS)
    from market.models import Pool, PoolShare
    from storage.models import Pledge
    from weather import rules as wx_rules
    from weather import stages as wx_stages
    from weather.models import Alert as WxAlert

    out.update(wx_rules.ALL_TEXTS)
    out.update(wx_stages.LABELS.values())
    for choices in (Pool.Status.choices, PoolShare.Status.choices, Pledge.Status.choices, WxAlert.Kind.choices):
        out.update(label for _, label in choices)
    out.update(label for _, label in ins_services.DOCS + LOSS_CAUSES)
    from advisory.models import Advisory
    from farming.models import PRACTICES, CropGroup
    from institution.models import Notice

    for choices in (Advisory.Source.choices, Advisory.Kind.choices, Advisory.Severity.choices, CropGroup.Season.choices, CropGroup.Status.choices, Notice.Audience.choices, PRACTICES):
        out.update(label for _, label in choices)
    out.update(GROUP_TEXTS)
    for choices in (InsPlan.Scheme.choices, InsPlan.Season.choices, InsPlan.Group.choices, InsApp.Status.choices, InsApp.Channel.choices):
        out.update(label for _, label in choices)
    return out


# Fixed sentences the order timeline and texts use (written by deals/services.py, shown translated).
DEAL_TEXTS = [
    "New terms offered", "Terms agreed. Both sides now sign the agreement.", "Terms agreed. Please sign the agreement.", "Agreement signed by both",
    "Agreement signed by both. Contacts are now visible.", "Agreement signed by both. Contacts are now visible. Waiting for the advance.",
    "The other side signed. Please sign too.", "Payment marked as paid. Please confirm you received it.", "Seller has not received the payment.",
    "The seller has not received your payment. Please check.", "Advance received. Work has started.", "Paid in full. Order completed.", "Order completed",
    "New message", "Update on your order", "A problem was reported", "Goods sent", "Your order has been sent", "The buyer confirmed delivery",
    "The buyer reported a problem with the delivery", "Declined by the seller.", "Cancelled by the buyer.", "The request was closed",
    "e.g. moisture below 10%, cleaned, no stones", "Message to the seller (optional)",
]


SCORE_TEXTS = ["Days you used the app", "Farmer Book entries", "Selling: listings and orders", "Learning: games and expert questions", "Profile level",
               "Harvest per acre against your district", "Money earned against money spent", "Your sale price against the mandi", "Orders completed and buyer ratings", "Crops insured"]
GROUP_TEXTS = ["Group farming", "Members whose profile is checked", "Members who keep the Farmer Book for this crop", "Run with a verified FPO or NGO", "Guided by a KVK",
               "Practices agreed", "Seedha Bazar – Institution Connect", "This site is for KVKs and research agencies. Farmers, FPOs and buyers use Seedha Bazar.", "This number belongs to Institution Connect. Sign in there: {url}"]
SHARE_TEXTS = ["Direct from the farmer, no middlemen", "Pooled from {n} farmers", "Fresh from my farm", "I scored {n} points!", "Play free farming games on Seedha Bazar",
               "My farm scores", "Activity", "Performance", "Growing better with Seedha Bazar", "Share as a free ad", "Share my stock", "Share my scores", "Speak",
               "Notifications are working. You will hear about weather, prices and orders here.",
               "Your voice notes are deleted and the microphone permission is withdrawn here. You can also block the microphone in your browser settings."]
ISSUE_TEXTS = ["Urgent problem raised", "New problem raised", "The farmer replied", "A problem has waited a day for an answer",
               "Your request was approved. Collect it.", "Your request was not approved.", "Marked as collected.",
               "This number is not registered for a KVK or research centre. Ask Seedha Bazar to add your centre."]


def all_strings() -> set[str]:
    s = template_strings() | python_strings() | form_strings()
    return {x.replace('\\"', '"') for x in s if x.strip()}
