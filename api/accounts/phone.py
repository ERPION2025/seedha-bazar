"""Indian mobile number normalisation.

Farmers type numbers in many ways: with +91, with a leading 0, with spaces, or
even in Devanagari digits. Everything is reduced to the 10-digit national number.
"""
import re

_DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")


class InvalidPhone(ValueError):
    pass


def normalise_phone(raw: str) -> str:
    if not isinstance(raw, str):
        raise InvalidPhone("Phone must be text")
    s = raw.translate(_DEVANAGARI)
    s = re.sub(r"[\s\-().]", "", s)
    if s.startswith("+91"):
        s = s[3:]
    elif s.startswith("0091"):
        s = s[4:]
    elif s.startswith("91") and len(s) == 12:
        s = s[2:]
    elif s.startswith("0") and len(s) == 11:
        s = s[1:]
    if not re.fullmatch(r"[6-9]\d{9}", s):
        raise InvalidPhone("Enter a valid 10-digit Indian mobile number")
    return s
