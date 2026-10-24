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
    kind = "check" if getattr(widget, "input_type", "") == "checkbox" else "field"
    if kind == "check":
        return format_html('<div class="check"><label>{} <span>{}</span></label>{}{}</div>', bound.as_widget(), label, hint_html, errors)
    return format_html('<div class="field"><label for="{}">{}</label>{}{}{}</div>', bound.id_for_label, label, bound.as_widget(), hint_html, errors)


@register.simple_tag(takes_context=True)
def crop(context, value):
    from web.forms import crop_label
    return crop_label(context.get("lang", "hi"), value)
