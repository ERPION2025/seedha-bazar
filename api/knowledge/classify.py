"""Decide what a headline is about, and whether it is worth showing. Plain rules, no model: easy to read and to fix.

A headline needs a farming angle (a topic or a crop) to be kept. Government and institute sources rank higher.
Words are matched in English, Hindi and Marathi.
"""
import re
from datetime import timedelta

from django.utils import timezone

import catalog
from catalog import PRODUCTS

TOPICS = {
    "scheme": ["scheme", "yojana", "subsidy", "grant", "pm-kisan", "pm kisan", "kisan samman", "benefit", "योजना", "अनुदान", "सब्सिडी", "सम्मान निधि", "लाभ", "शासन निर्णय", "अनुदान"],
    "insurance": ["insurance", "pmfby", "fasal bima", "bima", "claim", "crop loss", "बीमा", "फसल बीमा", "विमा", "पीक विमा", "दावा"],
    "price": ["mandi", "msp", "minimum support", "price", "prices", "rate", "rates", "procure", "procurement", "bhav", "मंडी", "भाव", "एमएसपी", "समर्थन मूल्य", "खरीद", "हमीभाव", "बाजारभाव", "दर", "खरेदी"],
    "weather": ["rain", "monsoon", "weather", "drought", "flood", "hail", "frost", "cyclone", "heatwave", "मौसम", "बारिश", "बरसात", "सूखा", "बाढ़", "ओला", "हवामान", "पाऊस", "दुष्काळ", "गारपीट"],
    "advisory": ["advisory", "pest", "disease", "outbreak", "locust", "armyworm", "whitefly", "blight", "एडवाइजरी", "कीट", "रोग", "इल्ली", "सलाह", "कीड", "रोग", "सल्ला"],
    "fpo": ["fpo", "farmer producer", "producer organisation", "producer company", "cooperative", "sfac", "एफपीओ", "किसान उत्पादक", "सहकारी", "शेतकरी उत्पादक", "सहकारी"],
    "credit": ["kisan credit", "kcc", "loan", "interest subvention", "credit", "किसान क्रेडिट", "ऋण", "कर्ज", "कर्जमाफी", "पीककर्ज"],
    "processing": ["processing", "value addition", "food processing", "pmfme", "post-harvest", "warehouse", "storage", "cold chain", "agri infra", "प्रसंस्करण", "भंडारण", "गोदाम", "प्रक्रिया उद्योग"],
    "market": ["enam", "e-nam", "apmc", "export", "exports", "buyer", "market access", "निर्यात", "ई-नाम", "बाजार समिति", "निर्यात"],
    "inputs": ["fertiliser", "fertilizer", "urea", "dap", "seed", "seeds", "खाद", "उर्वरक", "यूरिया", "बीज", "बियाणे", "खत"],
    "technology": ["drone", "solar pump", "natural farming", "organic", "millet", "mushroom", "ड्रोन", "जैविक", "प्राकृतिक खेती", "श्री अन्न", "ऑर्गेनिक", "सेंद्रिय", "भरड धान्य"],
    "farming": ["farmer", "farmers", "kisan", "agriculture", "agricultural", "krishi", "crop", "crops", "harvest", "kvk", "icar", "किसान", "कृषि", "फसल", "खेती", "शेतकरी", "शेती", "पीक"],
}
FARMING_ONLY = {"farming"}
STATES = ["Andhra Pradesh", "Bihar", "Chhattisgarh", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Odisha",
          "Punjab", "Rajasthan", "Tamil Nadu", "Telangana", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Assam", "Delhi", "Jammu", "Kashmir"]
STATE_WORDS = {
    "मध्य प्रदेश": "Madhya Pradesh", "मध्यप्रदेश": "Madhya Pradesh", "मप्र": "Madhya Pradesh", "महाराष्ट्र": "Maharashtra", "उत्तर प्रदेश": "Uttar Pradesh", "उत्तरप्रदेश": "Uttar Pradesh",
    "यूपी": "Uttar Pradesh", "उप्र": "Uttar Pradesh", "योगी": "Uttar Pradesh", "राजस्थान": "Rajasthan", "छत्तीसगढ़": "Chhattisgarh", "छत्तीसगढ": "Chhattisgarh", "बिहार": "Bihar",
    "गुजरात": "Gujarat", "हरियाणा": "Haryana", "पंजाब": "Punjab", "झारखंड": "Jharkhand", "ओडिशा": "Odisha", "कर्नाटक": "Karnataka", "तेलंगाना": "Telangana", "हिमाचल": "Himachal Pradesh",
    "उत्तराखंड": "Uttarakhand", "पश्चिम बंगाल": "West Bengal", "आंध्र प्रदेश": "Andhra Pradesh", "तमिलनाडु": "Tamil Nadu", "केरल": "Kerala", "असम": "Assam", "दिल्ली": "Delhi",
    "मोहन यादव": "Madhya Pradesh", "फडणवीस": "Maharashtra", "महाराष्ट्रात": "Maharashtra", "मध्य प्रदेशात": "Madhya Pradesh",
}
TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")


def clean_text(html: str, limit: int = 300) -> str:
    text = SPACE.sub(" ", TAG.sub(" ", html or "")).replace("&nbsp;", " ").replace("&amp;", "&").strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _has(text: str, word: str) -> bool:
    if word.isascii():
        return re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", text) is not None
    return word in text


def topics_of(text: str) -> list[str]:
    t = text.lower()
    return [k for k, words in TOPICS.items() if any(_has(t, w) for w in words)]


def crops_of(text: str) -> list[str]:
    t = text.lower()
    out = []
    for key, (en, hi, mr, *_rest) in PRODUCTS.items():
        names = {n.lower().split("(")[0].strip() for n in (en, hi, mr)} | {key.replace("_", " ")}
        names = {n for n in names if len(n) >= 3}
        if any(_has(t, n) for n in names):
            out.append(key)
    return out[:6]


def state_of(text: str, default: str = "") -> str:
    """The state a headline is about: one it names, else the state of the search that found it, else nothing (national)."""
    for word, state in STATE_WORDS.items():
        if word in text:
            return state
    t = text.lower()
    for s in STATES:
        if s.lower() in t:
            return s
    return default


DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def language_of(text: str, declared: str) -> str:
    """The feed says what language it is, but search feeds mix. Trust the script: Devanagari is hi or mr, anything else is English."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return declared
    share = len(DEVANAGARI.findall(text)) / len(letters)
    if share > 0.4:
        return declared if declared in ("hi", "mr") else "hi"
    return "en"


def score(title: str, summary: str, trust: int, published, now=None) -> tuple[int, list[str], list[str]]:
    """(score, topics, crops). A score under MIN_SCORE means "not about farming": the engine drops it."""
    now = now or timezone.now()
    text = f"{title} {summary}"
    topics = topics_of(text)
    crops = crops_of(text)
    specific = [t for t in topics if t not in FARMING_ONLY]
    s = trust * 2 + len(specific) * 3 + (2 if "farming" in topics else 0) + min(len(crops), 3) * 2
    age = now - published
    s += 3 if age < timedelta(days=2) else 1 if age < timedelta(days=7) else 0
    if not topics and not crops:
        s = 0
    return s, topics, crops


MIN_SCORE = 9
