"""The feeds the news engine starts with. Public, free sources. Staff can add, switch off or re-rank them in the admin."""
from urllib.parse import quote

from django.conf import settings

from .models import Source

GOOGLE = "https://news.google.com/rss/search?q={q}&hl={hl}&gl=IN&ceid=IN:{hl}"
YT_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={id}"

# (name, kind, url or search words, language, state, trust)
BASE = [
    ("ICAR news", "rss", "https://icar.org.in/rss.xml", "en", "", 5),
    ("The Hindu: Agriculture", "rss", "https://www.thehindu.com/sci-tech/agriculture/feeder/default.rss", "en", "", 3),
    ("PIB: agriculture and farmers", "search", "site:pib.gov.in agriculture farmers", "en", "", 5),
    ("PIB: किसान और कृषि", "search", "site:pib.gov.in किसान कृषि", "hi", "", 5),
    ("Agriculture ministry", "search", "site:agriwelfare.gov.in OR site:agricoop.gov.in", "en", "", 5),
    ("ICAR and KVK sites", "search", "site:icar.org.in OR site:kvk.icar.gov.in", "en", "", 5),
    ("Krishi Vigyan Kendra news", "search", "KVK krishi vigyan kendra farmers training", "en", "", 4),
    ("Food processing ministry", "search", "site:mofpi.gov.in OR PMFME micro food processing", "en", "", 4),
    ("Farm schemes (English)", "search", "farmers scheme subsidy India", "en", "", 3),
    ("Mandi prices and MSP (English)", "search", "mandi prices MSP procurement farmers", "en", "", 3),
    ("Crop insurance (English)", "search", "crop insurance PMFBY farmers claim", "en", "", 3),
    ("FPO news (English)", "search", "FPO farmer producer organisation", "en", "", 3),
    ("किसान योजना", "search", "किसान योजना अनुदान", "hi", "", 3),
    ("मंडी भाव", "search", "मंडी भाव फसल समर्थन मूल्य", "hi", "", 3),
    ("फसल बीमा", "search", "फसल बीमा किसान", "hi", "", 3),
    ("एफपीओ किसान उत्पादक", "search", "एफपीओ किसान उत्पादक संगठन", "hi", "", 3),
    ("शेतकरी योजना", "search", "शेतकरी योजना अनुदान", "mr", "", 3),
    ("बाजारभाव शेतमाल", "search", "शेतमाल बाजारभाव हमीभाव", "mr", "", 3),
    ("DD Kisan (videos)", "youtube", "UCnDfmcUyhgJp6xC1LmBLfUg", "hi", "", 5),
]

STATE_QUERIES = {
    "Madhya Pradesh": [("मध्य प्रदेश किसान मंडी योजना", "hi"), ("Madhya Pradesh farmers mandi scheme", "en")],
    "Maharashtra": [("महाराष्ट्र शेतकरी बाजारभाव योजना", "mr"), ("Maharashtra farmers mandi scheme", "en")],
}


def feed_url(source: Source) -> str:
    if source.kind == Source.Kind.SEARCH:
        return GOOGLE.format(q=quote(source.url + " when:14d"), hl=source.language)
    if source.kind == Source.Kind.YOUTUBE:
        return YT_FEED.format(id=source.url)
    return source.url


def states() -> list[str]:
    return getattr(settings, "NEWS_STATES", None) or ["Madhya Pradesh", "Maharashtra"]


def seed() -> int:
    """Create or refresh the default sources. Existing ones keep their on/off switch and trust set by staff."""
    rows = list(BASE)
    for state in states():
        for words, lang in STATE_QUERIES.get(state, [(f"{state} farmers mandi scheme", "en")]):
            rows.append((f"{state}: farm news ({lang})", "search", words, lang, state, 3))
    made = 0
    for name, kind, url, lang, state, trust in rows:
        _, created = Source.objects.get_or_create(kind=kind, url=url, language=lang, defaults={"name": name, "state": state, "trust": trust})
        made += created
    return made
