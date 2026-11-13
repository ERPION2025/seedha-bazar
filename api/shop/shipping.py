"""Delivery zones, promised days (SLA) and charges, worked out from PIN codes.

From a seller's PIN code, or the Seedha Bazar warehouse in Jabalpur, to the buyer's PIN code:
  local     same area (first three digits)        1-2 days
  state     same state                            2-3 days
  near      a neighbouring state                  3-4 days
  metro     a metro city further away             3-5 days
  national  anywhere else                         4-6 days
  remote    J&K, Ladakh, the North East, islands  6-9 days
The charge is per parcel: a base for the zone plus a step for every 500 g above the first 500 g (SHOP_ZONE_FEES).
The states come from the first two digits of a PIN code, which India Post assigns by region.
"""
from decimal import Decimal

from django.conf import settings

PIN_STATE = {}
for prefixes, state in (
    (["11"], "Delhi"), (["12", "13"], "Haryana"), (["14", "15", "16"], "Punjab"), (["17"], "Himachal Pradesh"), (["18", "19"], "Jammu and Kashmir"),
    (["20", "21", "22", "23", "24", "25", "26", "27", "28"], "Uttar Pradesh"), (["30", "31", "32", "33", "34"], "Rajasthan"),
    (["36", "37", "38", "39"], "Gujarat"), (["40", "41", "42", "43", "44"], "Maharashtra"), (["45", "46", "47", "48"], "Madhya Pradesh"),
    (["49"], "Chhattisgarh"), (["50"], "Telangana"), (["51", "52", "53"], "Andhra Pradesh"), (["56", "57", "58", "59"], "Karnataka"),
    (["60", "61", "62", "63", "64"], "Tamil Nadu"), (["67", "68", "69"], "Kerala"), (["70", "71", "72", "73", "74"], "West Bengal"),
    (["75", "76", "77"], "Odisha"), (["78"], "Assam"), (["79"], "North East"), (["80", "81", "82", "83", "84", "85"], "Bihar and Jharkhand"),
):
    for p in prefixes:
        PIN_STATE[p] = state
NEIGHBOURS = {
    "Madhya Pradesh": {"Uttar Pradesh", "Rajasthan", "Gujarat", "Maharashtra", "Chhattisgarh"},
    "Maharashtra": {"Madhya Pradesh", "Gujarat", "Chhattisgarh", "Telangana", "Karnataka"},
    "Uttar Pradesh": {"Madhya Pradesh", "Delhi", "Haryana", "Rajasthan", "Bihar and Jharkhand", "Chhattisgarh"},
    "Chhattisgarh": {"Madhya Pradesh", "Maharashtra", "Odisha", "Telangana", "Bihar and Jharkhand", "Uttar Pradesh"},
    "Rajasthan": {"Madhya Pradesh", "Gujarat", "Haryana", "Punjab", "Uttar Pradesh", "Delhi"},
    "Gujarat": {"Madhya Pradesh", "Maharashtra", "Rajasthan"},
}
METRO_PREFIXES = ("110", "400", "560", "600", "700", "500", "411", "380")
REMOTE_PREFIXES = ("18", "19", "78", "79", "744")
SLA = {"local": "1-2", "state": "2-3", "near": "3-4", "metro": "3-5", "national": "4-6", "remote": "6-9"}


def state_of(pin: str) -> str:
    return PIN_STATE.get((pin or "")[:2], "")


def zone(from_pin: str, to_pin: str) -> str:
    if not (from_pin and to_pin):
        return "national"
    if to_pin.startswith(REMOTE_PREFIXES):
        return "remote"
    if from_pin[:3] == to_pin[:3]:
        return "local"
    a, b = state_of(from_pin), state_of(to_pin)
    if a and a == b:
        return "state"
    if b in NEIGHBOURS.get(a, set()):
        return "near"
    if to_pin.startswith(METRO_PREFIXES):
        return "metro"
    return "national"


def charge(z: str, weight_g: int) -> Decimal:
    base, step = settings.SHOP_ZONE_FEES.get(z, settings.SHOP_ZONE_FEES["national"])
    extra = max(0, (weight_g - 1) // 500)  # every 500 g above the first 500 g
    return Decimal(base + step * extra)


def quote(from_pin: str, to_pin: str, weight_g: int) -> dict:
    z = zone(from_pin, to_pin)
    return {"zone": z, "days": SLA[z], "fee": charge(z, weight_g)}


def valid_pin(pin: str) -> bool:
    return bool(pin) and len(pin) == 6 and pin.isdigit() and pin[0] != "0"
