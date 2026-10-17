# Seedha Bazar API (foundation)

Django + Django REST Framework. Phone-OTP login, device-bound sessions, farmer and buyer profiles,
FPO/NGO linkage, agent-assisted onboarding, audit log. Not built on Frappe; runs on any host that can run
containers and PostgreSQL.

Scope of this drop: accounts, profiles and the Farmer Book. Not built yet: listings, search, chat and unlock,
billing, AI advisor, the Next.js app. See the architecture plan for the order.

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

## Before real users

1. Write an OTP backend for your SMS/WhatsApp/voice provider (see `accounts/messaging.py`; set `OTP_BACKEND` to its dotted path). SMS in India needs a DLT-registered sender and approved templates.
2. Set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, database settings; serve over HTTPS.
3. Throttles use the database, which is fine for the pilot. Move to Redis when traffic grows. Behind a proxy, make sure it sets `X-Forwarded-For` honestly, because the per-network limit trusts it.
4. Verify each FPO in /admin/ (they are hidden from farmer search until `verified`), and have a lawyer review the consent text and DPDP obligations. `CONSENT_VERSION` in settings records which text each user accepted.
5. Have an agronomist and a native speaker review any text shown to farmers.

## Known limits of this drop

- Agents cannot edit a farmer's profile after adding it; the farmer owns it.
- Join codes are not rate-limited beyond normal request limits; add throttling before public launch.
- No email, no passwords for farmers. Staff use the Django admin with phone number and password.
