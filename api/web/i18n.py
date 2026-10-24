"""Hindi, Marathi and English text.

Templates and views use the English sentence as the key: `{% t "Add expense" %}`. English shows as written;
Hindi and Marathi come from translations.py, and a missing entry falls back to English so nothing breaks.
A test fails if any literal in a template has no Hindi or Marathi entry.
"""
from .translations import API_ERRORS, TRANSLATIONS

LANGS = ("hi", "mr", "en")
LANG_NAMES = {"hi": "हिन्दी", "mr": "मराठी", "en": "English"}
DEFAULT_LANG = "hi"


def tr(lang: str, text, **kw) -> str:
    text = str(text)
    out = text
    if lang in ("hi", "mr"):
        pair = TRANSLATIONS.get(text)
        if pair:
            out = pair[0] if lang == "hi" else pair[1]
    return out.format(**kw) if kw else out


def api_error_text(lang: str, code: str, fallback: str) -> str:
    en = API_ERRORS.get(code)
    return tr(lang, en) if en else fallback
