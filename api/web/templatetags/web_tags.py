from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html, format_html_join

from rates import fmt
from web.i18n import tr

register = template.Library()


@register.simple_tag(takes_context=True)
def t(context, text, **kw):
    """Translate an English sentence (or a variable holding one) into the visitor's language."""
    return tr(context.get("lang", "hi"), text, **kw)


@register.filter
def inr(value, places=0):
    return fmt.inr(value, int(places))


@register.filter
def num(value, places=2):
    """Trim trailing zeros: 12.500 -> 12.5"""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError):
        return value
    s = f"{d:.{int(places)}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


@register.filter
def quintal(kg):
    """Kg -> quintal for display, rounded down so it never promises more than the stock."""
    try:
        d = Decimal(str(kg))
    except (InvalidOperation, TypeError):
        return kg
    return num((d / 100).quantize(Decimal("0.001"), rounding="ROUND_DOWN"), 3)


@register.filter
def stripzeros(value):
    return num(value, 3) if value is not None else ""


@register.simple_tag(takes_context=True)
def field(context, bound, hint="", **attrs):
    """One labelled input with its errors, in the visitor's language."""
    lang = context.get("lang", "hi")
    widget = bound.field.widget
    for k, v in attrs.items():
        widget.attrs[k.replace("_", "-")] = v
    if bound.errors:
        widget.attrs["aria-invalid"] = "true"
    label = tr(lang, bound.field.label or bound.name)
    errors = format_html_join("", '<p class="err">{}</p>', ((tr(lang, e),) for e in bound.errors))
    hint_html = format_html('<p class="hint">{}</p>', tr(lang, hint)) if hint else ""
    kind = "check" if getattr(widget, "input_type", "") == "checkbox" and not getattr(widget, "allow_multiple_selected", False) else "field"
    if kind == "check":
        return format_html('<div class="check"><label>{} <span>{}</span></label>{}{}</div>', bound.as_widget(), label, hint_html, errors)
    return format_html('<div class="field"><label for="{}">{}</label>{}{}{}</div>', bound.id_for_label, label, bound.as_widget(), hint_html, errors)


@register.simple_tag(takes_context=True)
def crop(context, value):
    from web.forms import crop_label
    return crop_label(context.get("lang", "hi"), value)


TOPIC_LABELS = {"scheme": "Schemes", "price": "Prices and MSP", "insurance": "Insurance", "fpo": "FPO and NGO", "weather": "Weather", "advisory": "Advisories",
                "processing": "Processing and storage", "credit": "Credit", "technology": "New methods", "market": "Selling", "inputs": "Inputs and equipment", "farming": "Farming"}


@register.filter
def topic_label(key):
    return TOPIC_LABELS.get(key, key)



@register.inclusion_tag("web/partials/news_strip.html", takes_context=True)
def news_for_home(context, limit=3):
    """Announcements from staff and the top headlines for this person, for the top of a home page."""
    from knowledge import services

    request = context["request"]
    lang = context.get("lang", "hi")
    rows, _ = services.ranked_articles(request.user, lang, limit=limit)
    return {"announcements": services.announcements_for(request.user, lang, 2), "rows": rows, "lang": lang}



@register.filter
def emoji_of(key):
    import catalog
    return catalog.emoji(key)


@register.filter
def crop_name(key, lang="hi"):
    from web.forms import crop_label
    return crop_label(lang, key)



@register.filter
def first_name(name):
    """Only the first word of a name: what the other side sees before an agreement is signed."""
    return (name or "").split()[0] if (name or "").split() else ""



@register.filter
def jsonify(value):
    import json

    from django.utils.safestring import mark_safe
    return mark_safe(json.dumps(value).replace("<", "\\u003c").replace("'", "\\u0027"))
