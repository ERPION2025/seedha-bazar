"""One menu per kind of user. Wide screens show it as a left-side menu; phones show the first four items in a bottom bar
and the rest behind "More". Each item: (label, icon, url, paths that light it up, badge key)."""

FARMER = [
    ("Home", "🏠", "/farmer/", ["=/farmer/"], ""), ("My book", "📒", "/farmer/book/", ["/farmer/book"], ""),
    ("Sell", "🏷️", "/farmer/sell/", ["/farmer/sell"], ""), ("Rates", "📈", "/rates/", ["/rates"], ""),
    ("Orders", "📦", "/deals/", ["/deals"], "deal_unread"), ("Messages", "💬", "/farmer/enquiries/", ["/farmer/enquiries", "/enquiry"], "unread"),
    ("Ask an expert", "🧑‍🔬", "/help/", ["/help"], ""), ("Seeds and inputs", "🌱", "/inputs/", ["/inputs"], ""),
    ("Insurance", "🛡️", "/insurance/", ["/insurance"], ""), ("Earn more", "💰", "/value/", ["/value"], ""),
    ("News", "📰", "/news/", ["/news", "/schemes", "/videos"], ""), ("My district", "📊", "/insights/", ["/insights"], ""),
    ("Games", "🎮", "/games/", ["/games"], ""), ("Map", "🗺️", "/map/", ["/map"], ""), ("Calculator", "🧮", "/calculator/", ["/calculator"], ""),
    ("My FPO", "🤝", "/farmer/fpo/", ["/farmer/fpo"], ""), ("Profile", "👤", "/farmer/profile/", ["/farmer/profile"], ""),
    ("Account", "⚙️", "/farmer/account/", ["/farmer/account"], ""),
]
FPO = [
    ("Home", "🏠", "/fpo/", ["=/fpo/"], ""), ("My farmers", "🧑‍🌾", "/fpo/farmers/", ["=/fpo/farmers/"], ""),
    ("Sell", "🏷️", "/fpo/sell/", ["/fpo/sell"], ""), ("Orders", "📦", "/deals/", ["/deals"], "deal_unread"),
    ("Add farmer", "➕", "/fpo/farmers/add/", ["/fpo/farmers/add"], ""), ("Requests", "📥", "/fpo/requests/", ["/fpo/requests"], ""),
    ("Messages", "💬", "/fpo/enquiries/", ["/fpo/enquiries", "/enquiry"], "unread"), ("Ask an expert", "🧑‍🔬", "/help/", ["/help"], ""),
    ("Seeds and inputs", "🌱", "/inputs/", ["/inputs"], ""), ("Insurance", "🛡️", "/fpo/insurance/", ["/fpo/insurance", "/insurance"], ""),
    ("Rates", "📈", "/rates/", ["/rates"], ""), ("News", "📰", "/news/", ["/news", "/videos"], ""), ("Schemes", "🏛️", "/schemes/", ["/schemes"], ""),
    ("My district", "📊", "/insights/", ["/insights"], ""), ("Map", "🗺️", "/map/", ["/map"], ""),
]
BUYER = [
    ("Home", "🏠", "/buyer/", ["=/buyer/"], ""), ("Marketplace", "🛒", "/market/", ["/market"], ""),
    ("Find producers", "🧑‍🌾", "/buyer/producers/", ["/buyer/producers", "/producers"], ""), ("Orders", "📦", "/deals/", ["/deals"], "deal_unread"),
    ("Messages", "💬", "/buyer/enquiries/", ["/buyer/enquiries", "/enquiry"], "unread"), ("Rates", "📈", "/rates/", ["/rates"], ""),
    ("News", "📰", "/news/", ["/news", "/schemes", "/videos"], ""), ("Map", "🗺️", "/map/", ["/map"], ""),
    ("Business details", "👤", "/buyer/profile/", ["/buyer/profile"], ""),
]
KVK = [
    ("Control centre", "🏛️", "/kvk/", ["=/kvk/"], ""), ("Problems", "⚠️", "/kvk/issues/", ["/kvk/issues"], "kvk_open"),
    ("Input offers", "🌱", "/kvk/offers/", ["/kvk/offers"], ""), ("Map", "🗺️", "/kvk/map/", ["/kvk/map"], ""),
    ("Farmers", "🧑‍🌾", "/kvk/farmers/", ["/kvk/farmers"], ""), ("FPOs and NGOs", "🏢", "/kvk/orgs/", ["/kvk/orgs"], ""),
    ("Rates", "📈", "/rates/", ["/rates"], ""), ("News", "📰", "/news/", ["/news", "/schemes", "/videos"], ""),
]
STAFF = [
    ("Overview", "📊", "/console/", ["=/console/"], ""), ("FPOs and NGOs", "🏢", "/console/orgs/", ["/console/orgs"], "waiting_orgs"),
    ("Farmers", "🧑‍🌾", "/console/farmers/", ["/console/farmers"], ""), ("Listings", "🏷️", "/console/listings/", ["/console/listings"], ""),
    ("Buyers", "🛒", "/console/buyers/", ["/console/buyers"], ""), ("KVKs", "🏛️", "/console/centres/", ["/console/centres"], ""),
    ("Rates", "📈", "/console/rates/", ["/console/rates"], ""), ("News", "📰", "/console/news/", ["/console/news"], ""),
    ("Messages", "💬", "/console/messages/", ["/console/messages"], ""), ("Leads", "📥", "/console/leads/", ["/console/leads"], ""),
    ("Activity", "🕘", "/console/audit/", ["/console/audit"], ""),
]
PUBLIC = [
    ("Home", "🏠", "/", ["=/"], ""), ("Rates", "📈", "/rates/", ["/rates"], ""), ("Marketplace", "🛒", "/market/", ["/market"], ""),
    ("Calculator", "🧮", "/calculator/", ["/calculator"], ""), ("News", "📰", "/news/", ["/news"], ""), ("Government schemes", "🏛️", "/schemes/", ["/schemes"], ""),
    ("Crop insurance", "🛡️", "/insurance/", ["/insurance"], ""), ("Earn more", "💰", "/value/", ["/value"], ""), ("Videos", "🎬", "/videos/", ["/videos"], ""),
    ("Games", "🎮", "/games/", ["/games"], ""), ("Map", "🗺️", "/map/", ["/map"], ""), ("For farmers", "🧑‍🌾", "/for-farmers/", ["/for-farmers"], ""),
    ("For FPOs and NGOs", "🤝", "/for-fpos/", ["/for-fpos"], ""), ("For buyers", "🛒", "/for-buyers/", ["/for-buyers"], ""), ("Sign in", "🔑", "/login/", ["/login"], ""),
]
MAIN = 4  # items in the phone's bottom bar before "More"


def items_for(user):
    if not user or not user.is_authenticated:
        return PUBLIC
    if user.is_staff or user.role == "admin":
        return STAFF
    return {"farmer": FARMER, "agent": FPO, "buyer": BUYER, "agronomist": KVK}.get(user.role, PUBLIC)


def _active(path: str, patterns) -> bool:
    return any(path == p[1:] if p.startswith("=") else path.startswith(p) for p in patterns)


def menu(request, badges: dict) -> dict:
    path = request.path
    rows = [{"label": l, "icon": i, "url": u, "active": _active(path, pats), "badge": badges.get(b, 0) if b else 0} for l, i, u, pats, b in items_for(getattr(request, "user", None))]
    main, more = rows[:MAIN], rows[MAIN:]
    return {"all": rows, "main": main, "more": more, "more_active": any(r["active"] for r in more), "more_badge": sum(r["badge"] for r in more)}
