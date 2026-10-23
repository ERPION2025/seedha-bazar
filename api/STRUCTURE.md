# Seedha Bazar: structure (frozen 23 Oct 2026)

One codebase and one database serve **two separate sites**. Change this structure only by a deliberate decision, and record the decision here.

## 1. The two sites

| | Seedha Bazar (main site) | Seedha Bazar – Institution Connect |
|---|---|---|
| Who | Farmers, FPOs and NGOs, buyers, Seedha Bazar staff | KVKs, agricultural universities, research agencies |
| Address | `SITE_URL` (dev: `http://localhost:8000`) | `INSTITUTION_URL` (dev: `http://connect.localhost:8000`) |
| Hosts | everything not listed in `INSTITUTION_HOSTS` | `INSTITUTION_HOSTS` |
| URL map | `config/urls.py` → `web/urls.py` | `institution/urls.py` (paths start at `/`) |
| Look | green, `web/templates/web/base.html` | blue, `institution/templates/institution/base.html` |
| Sign-in | `/login/` with three doors: Farmer, FPO or NGO, Buyer (code by SMS) | `/login/`: a code by SMS or by email, as the person chooses; only people registered in the owner console |

- `web.middleware.SiteMiddleware` picks the site from the host and sets `request.site` and `request.urlconf`.
- Sessions never cross sites, because cookies are per host. The two sites also refuse each other's people:
  - a KVK staff number that tries the main site is told to use Institution Connect;
  - a farmer, FPO or buyer session that reaches Institution Connect is signed out.
- Old `/kvk/...` links on the main site redirect to the same page on Institution Connect.
- **Production:** point a second domain (for example `connect.seedhabazar.in`) at the same app. Set `INSTITUTION_HOSTS` and `INSTITUTION_URL`, and add the host to `DJANGO_ALLOWED_HOSTS`.

## 2. One owner console

`/console/` on the main site is the single place to run Seedha Bazar. It has its own password sign-in at `/console/login/`, using a mobile number or email plus a password.

| Page | What the owner and admins do there |
|---|---|
| Institutions | Add, change or remove KVKs, research centres, universities and agriculture offices: state, the districts each looks after, contacts, active or paused. Add, change or remove each institution's people (name, mobile, email, role). Removing a person or an institution stops their sign-in at once. |
| FPOs and NGOs, Farmers, Buyers, Listings | Verify, add and moderate |
| Admins | Owners add or remove admins, with or without owner rights |
| Data feeds, Settings | WDRA, mKisan and IMD feeds; session policy; integrations |
| All records (`/admin/`) | Every record of every kind, searchable, changeable and removable |

- Institutions are registered only here; nobody can sign up as one.
- `manage.py create_owner --phone ... --email ...` creates or resets an owner and prints a one-time password.

## 3. Sign-in comes first

- `web.middleware.LoginFirstMiddleware`: nothing is shown before sign-in. Every page sends the visitor to `/login/?next=...`, and after sign-in they land on the page they asked for.
- No menu is drawn before sign-in; `PUBLIC` in `web/menus.py` is empty.
- Open without sign-in, and nothing more:
  - the sign-in steps and the privacy notice;
  - FPO join links (`/join/`);
  - shared ad cards (`/s/`), so WhatsApp and Facebook can show the picture;
  - statement checks for banks (`/verify/`);
  - machine endpoints: `/api/`, `/hooks/`, `/static/`, the manifest, the service worker and `/health/`.

## 4. Menus: one per role, nothing else

Menus are defined in `web/menus.py`. Phones show the first 4 items in the bottom bar and the rest under "More".

- **Farmer:** Home, My book, Sell, Rates, Orders, Messages, Weather, Speak, Ask an expert, Seeds and inputs, Group farming, Group selling, Warehouse loans, Income statement, Insurance, Earn more, News, My district, Games, Map, Calculator, My FPO, Profile, My shared posts, Notifications, Account.
- **FPO / NGO:** Home, My farmers, Sell, Orders, Group selling, Group farming, Weather, My shared posts, Add farmer, Requests, Messages, Ask an expert, Seeds and inputs, Insurance, Rates, News, Schemes, My district, Map, Notifications.
- **Buyer:** Home, Marketplace, Find producers, Orders, Messages, Rates, News, Map, Business details, Notifications.
- **Owner console:** Overview, FPOs and NGOs, Farmers, Listings, Buyers, Institutions, Rates, News, Messages, Leads, Activity, Data feeds, Admins, Settings, All records.
- **Institution Connect:** Control centre, Alerts and weather, Farmers (and add), FPOs and NGOs (and add), Active loans, Seeds and inputs, Send a notice, Problems, Group farming, Map, Notifications.

## 5. Applications (Django apps)

| App | Owns |
|---|---|
| `accounts` | users and roles, OTP, consent, audit, login sessions (2 devices by default), site policy |
| `profiles` | farmer profiles, FPOs/NGOs, membership |
| `farmerbook` | the Farmer Book: crops, costs, harvests, sales, income statement |
| `market` | listings, enquiries, stock, group selling (pools) |
| `deals` | orders with signed agreements and advances; producer directory |
| `rates` | mandi rates, MSP, calculator; **`rates/worker.py` is the one background worker** |
| `catalog` / `knowledge` / `insurance` | products and ODOP / news, schemes, videos / crop insurance |
| `weather` | forecasts (Open-Meteo) and per-farm crop alerts |
| `advisory` | district advisories: from KVKs (Institution Connect), the mKisan feed, and IMD warnings (once IMD whitelists us) |
| `storage` | WDRA warehouses (crawled weekly), e-NWR pledges and loans |
| `farming` | group farming: crop groups, members, trust score |
| `extension` | KVK centres and their district geofence, input offers |
| `issues` | farmers' problems answered by KVKs |
| `engagement` | games, scores, shared ad cards, voice notes |
| `notify` | SMS, WhatsApp, Messenger and web-push delivery; message texts |
| `institution` | the Institution Connect site: views, URLs, templates, notices |
| `web` | the main site: views, templates, menus, translations, middleware |

## 6. Background worker

`python manage.py run_worker` loops through these jobs; each decides for itself whether it is due.

| Job | Does |
|---|---|
| `tick` | mandi rates (daily) and rate alerts |
| `news_tick` | news and video feeds |
| `issues_tick` | reminds KVKs about problems left unanswered |
| `weather_tick` | daily farm alerts, plus loan reminders and voice topics |
| `advisory_tick` | mKisan feed every 6 h; IMD every 3 h if `IMD_API_ENABLED` |
| `warehouse_tick` | WDRA list, a few states a day, so every state is refreshed weekly |

## 7. Rules that do not change

- Every visible string goes through `{% t %}` / `tr()`, with Hindi and Marathi in `web/translations*.py`. A test fails otherwise.
- A KVK sees a farmer's book only if that farmer said yes (`share_with_extension`). Totals never name anyone.
- Feeds are read gently: `robots.txt` is respected, there are pauses between requests, and nothing behind a captcha is scraped.
