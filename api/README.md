# Seedha Bazar API (foundation)

Django + Django REST Framework. Phone-OTP login, device-bound sessions, farmer and buyer profiles,
FPO/NGO linkage, agent-assisted onboarding, audit log. Not built on Frappe; runs on any host that can run
containers and PostgreSQL.

Scope of this drop: accounts, profiles, the Farmer Book and the website (three doors, landing pages, harvest calculator). Not built yet: payments and billing, photos on listings, ML price models,
billing, AI advisor, the Next.js app. See the architecture plan for the order.

## The website

Open `http://localhost:8000`. It is part of this same Django app: one deployment, no separate frontend, works on any host.
Hindi (default), Marathi and English: switch with the buttons at the top, or `?lang=mr`. Everything is mobile first.

| Door | Address | What it does |
| --- | --- | --- |
| Public and ads | `/`, `/for-farmers/`, `/for-fpos/`, `/for-buyers/`, `/calculator/`, `/privacy/` | Landing pages. Lead forms save to the database with the UTM tags of the ad that brought the visitor (first touch). GA4 and Meta pixel load only after the visitor allows cookies. |
| Sign in | `/login/` | One door for everyone: mobile number, code by SMS (or WhatsApp / call), done. No passwords. `?as=farmer`, `?as=fpo`, `?as=buyer` chooses what a new number becomes. |
| Farmer | `/farmer/` | Home shows the one next step to take. Profile, join an FPO (search, code or link), Farmer Book (crops, expenses, harvest, sales, reminders, profit), account and delete. |
| FPO / NGO | `/fpo/` | Register the organisation (needs staff approval), add farmers one by one or paste a list, review join requests, WhatsApp invite link `/join/<code>/`, auto-approve switch, members and crops at a glance. |
| Admin | `/console/` | Approve FPOs, create an FPO with its first agent, add farmers for any FPO, see leads (CSV download) and recent activity. Deep editing stays in `/admin/`. |
| Buyer | `/buyer/` | Business details and "coming soon". Buying is not built yet. |

How it runs itself: a farmer added by an FPO gets a code on their own phone and becomes active when they enter it. An FPO shares one link; farmers who
open it and sign in are sent to that FPO, and with auto-approve on they are confirmed at once. An unverified FPO has no powers (it cannot add farmers or
approve anyone, on the website or the JSON API) until staff approve it. Staff sign in the same way, with an account whose role is admin (`createsuperuser`).

Try it with sample data: `python manage.py seed_demo` creates a verified FPO, a farmer with a season of entries, a farmer waiting to confirm and a buyer.
Sign in at `/login/` with 9000000001 (FPO agent, `?as=fpo`), 9000000002 (farmer) or 9000000004 (buyer); the code appears in the server log.
Staff: the number from `createsuperuser`.

Text lives in `web/translations.py` (English sentence -> Hindi, Marathi). A test fails if a sentence on any page has no entry. Have native speakers read it before ads run.

## Run it

    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python manage.py migrate
    python manage.py seed_pilot                 # the four pilot FPOs (unverified)
    python manage.py createsuperuser            # phone number + password, for /admin/
    python manage.py create_agent 98XXXXXXXX naigarhi
    python manage.py runserver
    python manage.py test                       # 81 tests

Local runs print OTPs in the server log (`OTP_BACKEND=console`). Production refuses to start with that setting.
With Docker: copy `.env.example` to `.env`, then `docker compose up --build`.

## Flows

**1. Farmer signs in (self-serve).**
`POST /api/auth/otp/request` -> code arrives by SMS (or WhatsApp / voice call) ->
`POST /api/auth/otp/verify` with `device_id`, `consent: true` -> access token (15 min) + refresh token (90 days, rotates on every use).
A new number becomes a farmer or buyer account (`role`); privileged roles can never be self-assigned.

**2. Staying signed in.** The app refreshes silently with `POST /api/auth/token/refresh`. Each refresh returns a new refresh token.
Presenting an old one is treated as theft: that device is signed out and an audit event is written.
Optional 4-digit PIN (`POST /api/auth/pin`) lets the same phone re-enter via `POST /api/auth/pin/login`. A PIN never works on a new device, and locks for 15 minutes after 5 wrong tries.

**3. New phone.** Always needs a fresh OTP. The owner gets a text, and can list (`GET /api/auth/devices`) and sign out
(`DELETE /api/auth/devices/<id>`) any phone. Sign-out takes effect at once, even for unexpired access tokens.

**4. Assisted onboarding (FPO/NGO agent).** Agent signs in with their own account, then `POST /api/agent/farmers`
with the farmer's phone and details. The farmer is created as `pending` and gets a code on their own phone.
The farmer verifies it on their device, accepts consent, and the account becomes theirs and `active`; the FPO link becomes `confirmed`.
The agent never receives tokens for the farmer. A pending account cannot use the app. If the farmer's number is already registered, nothing is overwritten.
`contact_is_family` marks a family member's phone.

**5. Farmer joins an FPO later.** `POST /api/farmers/me/join-org` with the FPO's join code -> an agent of that FPO approves or rejects
(`/api/agent/join-requests/...`). Approval confirms the link.

**6. Delete account.** `POST /api/me/delete {"confirm": "DELETE"}` signs out all devices, clears personal fields, frees the number.

## Farmer Book (`/api/farmerbook/`)

A private ledger for each farmer: plots, crop cycles, activities (harvest calendar), expenses, harvests and sales.
Only the farmer can read or change their records; buyers and agents get 403.

Endpoints (each supports list, create, read, patch, delete): `plots`, `cycles`, `activities`, `expenses`, `harvests`, `sales`.
Plus `GET ledger` (profit and loss per crop cycle, optional `?crop_cycle=<id>`) and `GET stock` (stock left and shelf-life days).

Built for patchy networks:
- The app makes each record's `client_id` (a UUID) and refers to related records by that id, so a whole season can be entered offline and pushed later in order (plot, cycle, then entries).
- Creating the same `client_id` twice is safe: the second call just returns the first record (HTTP 200).
- Deletes are soft. `GET <endpoint>?since=<ISO time>` returns everything changed after that time, including deletions (`deleted: true`), up to 500 rows, with `next_since` when there is more.

Numbers:
- Units are kg, quintal, tonne or bag (a bag needs `bag_weight_kg`). The server stores kg and computes it.
- A sale's `amount` is always quantity x rate, calculated by the server. Clients cannot send it.
- You cannot sell more than the stock in a crop cycle, and cannot shrink or delete a harvest below what was already sold (clear error codes: `insufficient_stock`, `stock_would_go_negative`). The app must push harvests before the sales that depend on them.
- The ledger separates costs tied to a crop cycle from general expenses, and gives cost per kg and average sale rate per quintal only when there is a harvest or a sale to base them on.

Not in this drop: voice entry (the app will turn speech into these same calls, with read-back before saving), subsidised input purchases, photo attachments, and sharing records with a buyer. Anything a buyer eventually sees must be something the farmer chooses to publish on a listing; the book itself stays private.

## Profile levels

Farmer: 0 phone only. 1 name, village, district, land size and at least one crop. 2 level 1 plus FPO/NGO confirmed (or land record verified by staff).
3 level 1 plus documents verified by staff. Levels are computed on the server; clients cannot set them.
Buyer: 0 phone. 1 business name, type and city. 2 level 1 plus GSTIN or FSSAI verified by staff.

## API summary

| Method and path | Who | What |
| --- | --- | --- |
| POST /api/auth/otp/request | anyone | send a code (`phone`, `channel`, `language`) |
| POST /api/auth/otp/verify | anyone | sign in (`phone`, `code`, `device_id`, `consent`, `role`) |
| POST /api/auth/token/refresh | anyone | rotate tokens |
| POST, DELETE /api/auth/pin | signed in | set or remove PIN |
| POST /api/auth/pin/login | anyone | PIN sign-in on a known device |
| GET /api/auth/devices, DELETE /api/auth/devices/<id>, POST /api/auth/logout | signed in | manage phones |
| GET, PATCH /api/me | signed in | account summary, language |
| POST /api/me/delete | signed in | delete account |
| GET, PATCH /api/farmers/me | farmer | farmer profile |
| POST /api/farmers/me/join-org | farmer | ask to join an FPO by code |
| GET, PATCH /api/buyers/me | buyer | buyer profile |
| GET /api/orgs?q= | signed in | verified FPOs/NGOs (no join codes) |
| GET, POST /api/agent/farmers | agent | list members, add a farmer |
| POST /api/agent/farmers/<id>/resend | agent | resend the farmer's confirmation code |
| GET /api/agent/join-requests, POST .../<id>/approve or /reject | agent | member requests |

Errors look like `{"error": {"code": "...", "message": "..."}}`. Codes are stable so the app can show Hindi/Marathi text.

## Safeguards built in

OTP: 6 digits, 5-minute life, hashed in the database, single use, newest code only, 30-second resend gap, 5 per phone per hour,
30 per network address per hour, 5 wrong guesses burn the code. The reply to "send code" never reveals whether a number is registered.
Numbers typed with +91, a leading 0, spaces or Devanagari digits are accepted. Refresh tokens are stored only as hashes.
Every sensitive action writes an audit event (never codes, PINs or tokens).

## Market rates, location and the calculator

**Rates.** Daily mandi prices come from Agmarknet (Govt. of India) through data.gov.in open data, stored in `MarketRate` (rupees per quintal) with the date,
state, district, mandi, variety and our crop key. `python manage.py update_rates` fetches them (safe to repeat); `python manage.py run_worker` is the always-on
process that does it about every 24 hours (retries a failure after an hour) and then sends rate alerts. In Docker it is the `worker` service. Get a free key at
https://data.gov.in (sign in, My Account) and set `DATA_GOV_IN_API_KEY`. Until then the pages say rates are coming; `/console/rates/` shows the feed status, recent
fetches and a Refresh button. Government MSP (`rates/data/msp.json`, copied from the PIB Cabinet releases for Rabi 2027-28 and Kharif 2026-27) loads with `load_msp`;
add each new announcement there. `seed_demo` adds clearly-labelled sample prices (hidden when `DEBUG` is off). To add another free source, write a class with
`name` and `fetch()` (see `rates/sources/datagov.py`) and list it in `rates/ingest.py`. Public JSON: `/api/rates/?crop=wheat&state=...&district=...`, `/api/rates/crops`,
`/api/rates/places`. Prices are what mandis report; the app says so wherever it shows them.

**Location.** The login page, calculator, rates page and farmer home offer "Use my location". The browser asks permission; the server turns the point into a state and
district with OpenStreetMap Nominatim (cached by ~1 km square, rate limited, identifies itself with `GEOCODER_USER_AGENT`) and keeps only the district in the session.
An empty farmer profile is filled with it; a typed district is never overwritten. People who say no pick a place from a list.

**Calculator (`/calculator/`).** One question per screen with big tiles and buttons: crop (with today's price on each tile), quantity (stepper, quick amounts), rate
(typical rate near you filled in, mandi cards, government MSP, or type your own), cuts, an optional comparison with the best-paying markets in the state or a buyer's
offer, then the result with a read-aloud button. It remembers progress if the page reloads or the person signs in. The sums are in `static/web/calculator.js` and
`rates/calc.py` (a test checks they agree).

**SMS and WhatsApp.** Trigger points: send the result to your own phone, daily rate alerts (`/alerts/`), and marketplace enquiry notices. Everything goes through
`notify.service.send(...)`, which records each message (`/console/messages/`), enforces opt-outs and a daily cap per number, and hands it to a backend. The default
`LogBackend` only records, and the app says so ("messages are not switched on yet") and opens WhatsApp click-to-chat as a fallback. To connect a provider, subclass
`notify.backends.Backend`, or set `NOTIFY_WEBHOOK_URL` (+ `NOTIFY_WEBHOOK_SECRET`, HMAC-signed JSON) to let n8n, Make or your own service send. Message wording per
language is in `notify/texts.py`; register each as a DLT template for SMS in India. Anonymous visitors can only send to a number they have signed in with.

## Marketplace

Farmers (profile level 1+) and agents of a verified FPO list produce: from the Farmer Book stock (quantity checked against stock not already listed), from the
calculator, or from scratch. Each listing shows the asking price per quintal next to today's mandi price. Buyers browse `/market/` (public; sellers shown by first name
and village, or FPO name), and send an enquiry once their business details are filled in. Phone numbers, emails and links in messages are hidden until the seller
accepts (the "unlock"; `Enquiry.unlock_fee_paise` is where billing plugs in, 0 in the pilot). After accepting, both sides see each other's contact and the seller can
record the sale in the Farmer Book with the fields filled in. Staff can hide listings and verify buyers in `/console/`. Listings expire after 30 days.

## Settings for the website

| Variable | Purpose |
| --- | --- |
| `SITE_URL` | Public address, used in the FPO invite link (`https://seedhabazar.in`). |
| `CSRF_TRUSTED_ORIGINS` | Your https origin(s), comma separated, in production. |
| `OTP_CHANNELS` | Which "send code" choices to offer: `sms,whatsapp,voice`. Offer only what your provider supports. |
| `GA4_ID`, `META_PIXEL_ID` | Ad tracking IDs. Empty means no tracking and no cookie bar. |
| `SUPPORT_WHATSAPP` | Number with country code, e.g. `919876543210`, for the Help on WhatsApp button. |

Static files are served by WhiteNoise from the same container. `python manage.py collectstatic` runs in the Dockerfile.

## Before real users

1. Write an OTP backend for your SMS/WhatsApp/voice provider (see `accounts/messaging.py`; set `OTP_BACKEND` to its dotted path). SMS in India needs a DLT-registered sender and approved templates.
2. Set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, database settings; serve over HTTPS.
3. Throttles use the database, which is fine for the pilot. Move to Redis when traffic grows. Behind a proxy, make sure it sets `X-Forwarded-For` honestly, because the per-network limit trusts it.
4. Verify each FPO in `/console/` (they are hidden from farmer search and cannot add farmers until `verified`), and have a lawyer review the consent text and DPDP obligations. `CONSENT_VERSION` in settings records which text each user accepted.
5. Have an agronomist and a native speaker review any text shown to farmers.

## Known limits of this drop

- Agents cannot edit a farmer's profile after adding it; the farmer owns it.
- Join codes are not rate-limited beyond normal request limits; add throttling before public launch.
- No email, no passwords for farmers. Staff use the Django admin with phone number and password.
- The privacy page and consent text are plain-language drafts. Have a lawyer review them (DPDP) before launch.
- Prices are only as good as what mandis report to Agmarknet; some mandis report late or not at all. The app shows the date and never presents old prices as today's.
- The data.gov.in feed is the one live source. eNAM and state mandi boards have no open API yet; the connector interface is ready for them.
- The website cannot work offline yet. The JSON API already supports offline sync for a future app.
- Reminders are shown on the farmer's home page only. SMS/WhatsApp reminders need a provider (same one as OTP).
- An agent belongs to one organisation in the website screens (the first one). The JSON API supports several.
