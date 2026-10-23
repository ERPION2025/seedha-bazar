"""One menu per kind of user. Wide screens show it as a left-side menu; phones show the first four items in a bottom bar
and the rest behind "More". Each item: (label, icon, url, paths that light it up, badge key)."""

FARMER = [
    ("Home", "🏠", "/farmer/", ["=/farmer/"], ""), ("My book", "📒", "/farmer/book/", ["/farmer/book"], ""),
    ("Sell", "🏷️", "/farmer/sell/", ["/farmer/sell"], ""), ("Rates", "📈", "/rates/", ["/rates"], ""),
    ("Orders", "📦", "/deals/", ["/deals"], "deal_unread"), ("Messages", "💬", "/farmer/enquiries/", ["/farmer/enquiries", "/enquiry"], "unread"),
    ("Weather", "🌦️", "/weather/", ["/weather"], ""), ("Speak", "🎙️", "/voice/", ["/voice"], ""), ("Ask an expert", "🧑‍🔬", "/help/", ["/help"], ""),
    ("Seeds and inputs", "🌱", "/inputs/", ["/inputs"], ""), ("Group farming", "👥", "/farmer/groups/", ["/farmer/groups"], ""),
    ("Group selling", "🤝", "/farmer/pools/", ["/farmer/pools"], ""),
    ("Warehouse loans", "🏬", "/storage/", ["/storage"], ""), ("Income statement", "🧾", "/statement/", ["/statement"], ""),
    ("Insurance", "🛡️", "/insurance/", ["/insurance"], ""), ("Earn more", "💰", "/value/", ["/value"], ""),
    ("News", "📰", "/news/", ["/news", "/schemes", "/videos"], ""), ("My district", "📊", "/insights/", ["/insights"], ""),
    ("Games", "🎮", "/games/", ["/games"], ""), ("Map", "🗺️", "/map/", ["/map"], ""), ("Calculator", "🧮", "/calculator/", ["/calculator"], ""),
    ("My FPO", "🤝", "/farmer/fpo/", ["/farmer/fpo"], ""), ("Profile", "👤", "/farmer/profile/", ["/farmer/profile"], ""),
    ("My shared posts", "📣", "/shared/", ["/shared"], ""), ("Notifications", "🔔", "/notifications/", ["/notifications"], ""),
    ("Account", "⚙️", "/farmer/account/", ["/farmer/account"], ""),
]
FPO = [
    ("Home", "🏠", "/fpo/", ["=/fpo/"], ""), ("My farmers", "🧑‍🌾", "/fpo/farmers/", ["=/fpo/farmers/"], ""),
    ("Sell", "🏷️", "/fpo/sell/", ["/fpo/sell"], ""), ("Orders", "📦", "/deals/", ["/deals"], "deal_unread"),
    ("Group selling", "🤝", "/fpo/pools/", ["/fpo/pools"], ""), ("Group farming", "👥", "/fpo/groups/", ["/fpo/groups"], ""), ("Weather", "🌦️", "/weather/", ["/weather"], ""), ("My shared posts", "📣", "/shared/", ["/shared"], ""),
    ("Add farmer", "➕", "/fpo/farmers/add/", ["/fpo/farmers/add"], ""), ("Requests", "📥", "/fpo/requests/", ["/fpo/requests"], ""),
    ("Messages", "💬", "/fpo/enquiries/", ["/fpo/enquiries", "/enquiry"], "unread"), ("Ask an expert", "🧑‍🔬", "/help/", ["/help"], ""),
    ("Seeds and inputs", "🌱", "/inputs/", ["/inputs"], ""), ("Insurance", "🛡️", "/fpo/insurance/", ["/fpo/insurance", "/insurance"], ""),
    ("Rates", "📈", "/rates/", ["/rates"], ""), ("News", "📰", "/news/", ["/news", "/videos"], ""), ("Schemes", "🏛️", "/schemes/", ["/schemes"], ""),
    ("My district", "📊", "/insights/", ["/insights"], ""), ("Map", "🗺️", "/map/", ["/map"], ""), ("Notifications", "🔔", "/notifications/", ["/notifications"], ""),
]
BUYER = [
    ("Home", "🏠", "/buyer/", ["=/buyer/"], ""), ("Marketplace", "🛒", "/market/", ["/market"], ""),
    ("Find producers", "🧑‍🌾", "/buyer/producers/", ["/buyer/producers", "/producers"], ""), ("Orders", "📦", "/deals/", ["/deals"], "deal_unread"),
    ("Messages", "💬", "/buyer/enquiries/", ["/buyer/enquiries", "/enquiry"], "unread"), ("Rates", "📈", "/rates/", ["/rates"], ""),
    ("News", "📰", "/news/", ["/news", "/schemes", "/videos"], ""), ("Map", "🗺️", "/map/", ["/map"], ""),
    ("Business details", "👤", "/buyer/profile/", ["/buyer/profile"], ""), ("Notifications", "🔔", "/notifications/", ["/notifications"], ""),
]
KVK = [  # Institution Connect (its own site): only what a KVK or research agency does for its districts
    ("Control centre", "🏛️", "/", ["=/"], ""), ("Alerts and weather", "🌦️", "/weather/", ["/weather", "/advisories"], ""),
    ("Farmers", "🧑‍🌾", "/farmers/", ["/farmers"], ""), ("FPOs and NGOs", "🏢", "/orgs/", ["/orgs"], ""),
    ("Active loans", "🏦", "/loans/", ["/loans"], ""), ("Seeds and inputs", "🌱", "/offers/", ["/offers"], ""),
    ("Send a notice", "📣", "/notices/", ["/notices"], ""), ("Problems", "⚠️", "/issues/", ["/issues"], "kvk_open"),
    ("Group farming", "👥", "/groups/", ["/groups"], ""), ("Map", "🗺️", "/map/", ["/map"], ""),
    ("Notifications", "🔔", "/notifications/", ["/notifications"], ""),
]
STAFF = [
    ("Overview", "📊", "/console/", ["=/console/"], ""), ("FPOs and NGOs", "🏢", "/console/orgs/", ["/console/orgs"], "waiting_orgs"),
    ("Farmers", "🧑‍🌾", "/console/farmers/", ["/console/farmers"], ""), ("Listings", "🏷️", "/console/listings/", ["/console/listings"], ""),
    ("Buyers", "🛒", "/console/buyers/", ["/console/buyers"], ""), ("Institutions", "🏛️", "/console/institutions/", ["/console/institutions"], ""),
    ("Rates", "📈", "/console/rates/", ["/console/rates"], ""), ("News", "📰", "/console/news/", ["/console/news"], ""),
    ("System notices", "📢", "/console/notices/", ["/console/notices"], ""), ("Messages", "💬", "/console/messages/", ["/console/messages"], ""), ("Leads", "📥", "/console/leads/", ["/console/leads"], ""),
    ("Activity", "🕘", "/console/audit/", ["/console/audit"], ""), ("Data feeds", "🔄", "/console/feeds/", ["/console/feeds"], ""), ("Admins", "🔐", "/console/admins/", ["/console/admins"], ""),
    ("Settings", "⚙️", "/console/settings/", ["/console/settings", "/console/sessions"], ""), ("All records", "🗂️", "/admin/", ["/admin"], ""),
]
PUBLIC: list = []  # nothing before sign-in: the sign-in page comes first
MAIN = 4  # items in the phone's bottom bar before "More"


def items_for(user, site: str = "main"):
    """The menu for this person on this site. Institution Connect shows only its own menu; the main site never shows it."""
    if not user or not user.is_authenticated:
        return PUBLIC
    if site == "institution":
        return KVK if user.role == "agronomist" or user.is_staff else PUBLIC
    if user.is_staff or user.role == "admin":
        return STAFF
    return {"farmer": FARMER, "agent": FPO, "buyer": BUYER}.get(user.role, PUBLIC)


def _active(path: str, patterns) -> bool:
    return any(path == p[1:] if p.startswith("=") else path.startswith(p) for p in patterns)


def menu(request, badges: dict) -> dict:
    path = request.path
    rows = [{"label": l, "icon": i, "url": u, "active": _active(path, pats), "badge": badges.get(b, 0) if b else 0} for l, i, u, pats, b in items_for(getattr(request, "user", None), getattr(request, "site", "main"))]
    main, more = rows[:MAIN], rows[MAIN:]
    return {"all": rows, "main": main, "more": more, "more_active": any(r["active"] for r in more), "more_badge": sum(r["badge"] for r in more)}
