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
           "rates_views.py", "market_views.py", "location.py", "rate_alerts.py")


def template_strings() -> set[str]:
    out = set()
    for path in (HERE / "templates").rglob("*.html"):
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

    from web import forms as wf

    out = set()
    for _, cls in inspect.getmembers(wf, inspect.isclass):
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
    return out


def all_strings() -> set[str]:
    s = template_strings() | python_strings() | form_strings()
    return {x.replace('\\"', '"') for x in s if x.strip()}
