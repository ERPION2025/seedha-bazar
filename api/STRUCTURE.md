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
  - read-only pages for visitors and search engines: For farmers, For FPOs, For NGOs, For buyers, and the marketplace by produce (`/produce/`, `/produce/<crop>/`, sellers shown by first name and village only); these have no menus, and asking or buying still needs sign-in. `sitemap.xml` and `robots.txt` list them;
  - FPO join links (`/join/`);
  - shared ad cards (`/s/`), so WhatsApp and Facebook can show the picture;
  - statement checks for banks (`/verify/`);
  - machine endpoints: `/api/`, `/hooks/`, `/static/`, the manifest, the service worker and `/health/`.

## 4. Notifications: the bell

- After sign-in, every role on both sites has a 🔔 bell in the header with the unread count. It opens `/notifications/`, the one list of everything sent to that person:
  - notices from their KVK and from Seedha Bazar ("system" notices, sent from Console → System notices);
  - advice, weather warnings, orders, groups, inputs and problems.
- Every message to a known person goes to the bell. SMS, WhatsApp and phone notifications are extra channels on top.
- Seedha Bazar notices use the bell and phone notifications only, never paid SMS.
- Phone notifications are asked for **once**, after sign-in (never on sign-in screens), through a small card: Allow or Not now. The answer is kept on the account and the device, and can be changed in Notifications → Settings.

## 4b. Livelihoods: one pattern, many businesses

- Farmers and FPOs/NGOs choose their livelihoods before setting up: crops, dairy, poultry, fisheries, beekeeping, sericulture, piggery. Two or more is integrated farming.
  - New farmers are asked first.
  - A new FPO is asked right after registering. Older FPOs see a card asking them.
  - Older crop accounts count as crop farmers until they choose.
- Everything that differs between livelihoods lives in one place, `farming/livelihoods.py`: unit types, what is counted, the ID field (ear tag, Madhukranti, licence), what is produced, which products are sold in which units, and the reminder schedule. A new livelihood is a new entry there, not new code.
- **What each person sees:** menus and pages show only what fits.
  - Crop-only tools are hidden from people without crops: Farmer Book, mandi rates, warehouse loans, insurance, group farming and selling, seeds, calculator.
  - My farm is hidden from crop-only farmers.
- **My farm** (`/farm/`) is one diary for every livelihood:
  - units (herd, batch, pond, apiary, rearing, pig unit) with one-tap entries (produced, sold, feed, treatment, other cost, died, born);
  - reminders from the schedule, sent to the bell and phone each morning, marked done with one tap.
  - Reminders give general practice only; medicines and doses are always "with your vet" or "with the department".
- **Connected to the existing modules:**
  - farm money joins the Farmer Book profit and loss and the income statement;
  - the farm sells into the marketplace (milk by the litre, eggs by the tray, fish, honey, cocoons, pigs);
  - FPOs see members' farms, production and reminders; FPO and Institution farmer lists filter by livelihood;
  - "Animals and livestock" problems go to the KVK as before.
- No hardware, sensors or outside registries are needed; government IDs are optional text fields.

## 4a. Menus: one per role, nothing else

Menus are defined in `web/menus.py`. Phones show the first 4 items in the bottom bar and the rest under "More".

- **Farmer:** Home, My book, Sell, Rates, Orders, Messages, Weather, Speak, Ask an expert, Seeds and inputs, Group farming, Group selling, Warehouse loans, Income statement, Insurance, Earn more, News, My district, Games, Map, Calculator, My FPO, Profile, My shared posts, Notifications, Account.
- **FPO / NGO:** Home, My farmers, Sell, Orders, Group selling, Group farming, Weather, My shared posts, Add farmer, Requests, Messages, Ask an expert, Seeds and inputs, Insurance, Rates, News, Schemes, My district, Map, Notifications.
- **Buyer:** Home, Marketplace, Find producers, Orders, Messages, Rates, News, Map, Business details, Notifications.
- **Owner console:** Overview, FPOs and NGOs, Farmers, Listings, Buyers, Institutions, Rates, News, System notices, Messages, Leads, Activity, Data feeds, Admins, Settings, All records.
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
- Every page of both sites has the same footer (`web/partials/footer.html`): who it is for, produce links, services, and the company (Vindhyachal Farms LLP, address, email and phone, set in `COMPANY_*` settings and published for search engines as Organization data).
- Every screen of both sites carries the loader (`web/partials/loader.html`, `web/static/web/loader.js`). It is a small farming scene matched to where the person is going, shown only when a page or form takes more than about a third of a second, and still for people who turn off motion. Scripts doing slow work call `SBLoader.show("rain")` and `SBLoader.hide()`; links or forms that should never show it get `data-no-loader`.
- Feeds are read gently: `robots.txt` is respected, there are pauses between requests, and nothing behind a captcha is scraped.
