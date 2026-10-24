import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me-0123456789abcdef")
if not DEBUG and SECRET_KEY.startswith("dev-only"):
    raise RuntimeError("Set DJANGO_SECRET_KEY in production")
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts",
    "profiles",
    "farmerbook",
    "rates",
    "notify",
    "catalog",
    "knowledge",
    "insurance",
    "deals",
    "extension",
    "issues",
    "engagement",
    "weather",
    "storage",
    "advisory",
    "farming",
    "institution",
    "market",
    "web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "web.middleware.SiteMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.sessions.SessionGuardMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "web.middleware.LanguageMiddleware",
    "web.middleware.AttributionMiddleware",
    "web.middleware.LoginFirstMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "web.context.site",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

if os.environ.get("DB_HOST"):
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "seedha"),
        "USER": os.environ.get("DB_USER", "seedha"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ["DB_HOST"],
        "PORT": os.environ.get("DB_PORT", "5432"),
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_USER_MODEL = "accounts.User"
LANGUAGE_CODE = "en"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Uploaded files (voice notes, photos). Nothing under private/ is served directly: views check who may see it first.
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", str(BASE_DIR / "media")))
MEDIA_URL = "/media-not-public/"
DATA_UPLOAD_MAX_MEMORY_SIZE = 8 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 4 * 1024 * 1024
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["accounts.authentication.DeviceJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "accounts.errors.api_exception_handler",
}

# --- Seedha Bazar auth settings ---
OTP_BACKEND = os.environ.get("OTP_BACKEND", "console")  # console | custom dotted path to a backend class
OTP_CHANNELS = [c for c in os.environ.get("OTP_CHANNELS", "sms,whatsapp,voice").split(",") if c]  # which "send code" choices the website offers
OTP_LENGTH = 6
# Pilot only, until an SMS/WhatsApp provider is connected: farmers, buyers, FPO agents (and numbers not yet registered) sign in
# with this fixed code. Agronomists and admins always get a real random code. Set OTP_STATIC_CODE= (empty) to turn off.
OTP_STATIC_CODE = "" if "test" in sys.argv else os.environ.get("OTP_STATIC_CODE", "123456")
OTP_TTL_SECONDS = 300
OTP_RESEND_COOLDOWN_SECONDS = 30
OTP_MAX_PER_PHONE_PER_HOUR = 5
OTP_MAX_PER_IP_PER_HOUR = 30
OTP_MAX_WRONG_ATTEMPTS = 5
PIN_MAX_WRONG_ATTEMPTS = 5
PIN_LOCK_MINUTES = 15
ACCESS_TOKEN_TTL_SECONDS = 15 * 60
REFRESH_TOKEN_TTL_DAYS = 90
CONSENT_VERSION = "2026-10-v1"

if not DEBUG and OTP_BACKEND == "console" and not OTP_STATIC_CODE:
    raise RuntimeError("OTP_BACKEND=console prints codes to the log. Configure a real provider for production.")
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "1") == "1"  # every http:// request goes to https://
    SECURE_REDIRECT_EXEMPT = [r"^health/$"]  # the load balancer's health check may use plain http
    # Browsers remember to use https only. Starts at one hour; raise to 31536000 (a year) once https is known to work everywhere.
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "3600"))
    # Off by default: both are hard to undo. Turn on only when every subdomain is https-only (preload also needs a year of HSTS).
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get("SECURE_HSTS_INCLUDE_SUBDOMAINS", "0") == "1"
    SECURE_HSTS_PRELOAD = os.environ.get("SECURE_HSTS_PRELOAD", "0") == "1"

# --- Website ---
LOGIN_URL = "/login/"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 60  # farmers stay signed in on their phone for 60 days
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000").rstrip("/")
SUPPORT_WHATSAPP = os.environ.get("SUPPORT_WHATSAPP", "")  # digits only with country code, e.g. 919876543210
GA4_ID = os.environ.get("GA4_ID", "")
META_PIXEL_ID = os.environ.get("META_PIXEL_ID", "")
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

# --- Market rates ---
DATA_GOV_IN_API_KEY = os.environ.get("DATA_GOV_IN_API_KEY", "")  # free: https://data.gov.in -> My Account
RATES_STATES = [s for s in os.environ.get("RATES_STATES", "").split(",") if s]  # empty = all states
RATES_REFRESH_HOURS = int(os.environ.get("RATES_REFRESH_HOURS", "24"))
RATES_SHOW_DEMO = os.environ.get("RATES_SHOW_DEMO", "1" if DEBUG else "0") == "1"  # sample rows are for local trials only
DEFAULT_STATE = os.environ.get("DEFAULT_STATE", "Madhya Pradesh")
FACEBOOK_APP_ID = os.environ.get("FACEBOOK_APP_ID", "")
FACEBOOK_APP_SECRET = os.environ.get("FACEBOOK_APP_SECRET", "")
FACEBOOK_GRAPH_VERSION = os.environ.get("FACEBOOK_GRAPH_VERSION", "v21.0")
# Notifications on phones (Web Push). Make keys with: python manage.py make_vapid_keys
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_EMAIL = os.environ.get("VAPID_EMAIL", "mailto:support@seedhabazar.in")
# WhatsApp Business Cloud API and Facebook Messenger (Meta)
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_TEMPLATE = os.environ.get("WHATSAPP_TEMPLATE", "seedha_update")  # an approved utility template with one body variable {{1}}
FACEBOOK_PAGE_ID = os.environ.get("FACEBOOK_PAGE_ID", "")
FACEBOOK_PAGE_TOKEN = os.environ.get("FACEBOOK_PAGE_TOKEN", "")
META_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "")
# Maps: "osm" (OpenStreetMap, free, default) or "google" (needs GOOGLE_MAPS_API_KEY)
MAP_PROVIDER = os.environ.get("MAP_PROVIDER", "osm")
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
MAP_TILE_URL = os.environ.get("MAP_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
# OSM's own tile servers are for light use only and need a Referer (map.js sends our origin). For real traffic use a provider
# with a key, e.g. MAP_TILE_URL=https://api.maptiler.com/maps/streets-v2/{z}/{x}/{y}.png?key=... and its attribution below.
MAP_TILE_ATTRIBUTION = os.environ.get("MAP_TILE_ATTRIBUTION", "")
# Optional server-side speech to text (Bhashini, Government of India)
BHASHINI_USER_ID = os.environ.get("BHASHINI_USER_ID", "")
BHASHINI_API_KEY = os.environ.get("BHASHINI_API_KEY", "")
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "")  # Open-Meteo is free for non-commercial use; commercial use needs their key
WEATHER_LOOKUP_VILLAGES = os.environ.get("WEATHER_LOOKUP_VILLAGES", "1") == "1"
NEWS_REFRESH_HOURS = int(os.environ.get("NEWS_REFRESH_HOURS", "6"))
NEWS_STATES = [s for s in os.environ.get("NEWS_STATES", "Madhya Pradesh,Maharashtra").split(",") if s]  # states that get their own local searches
GEOCODER_USER_AGENT = os.environ.get("GEOCODER_USER_AGENT", "SeedhaBazar/1.0 (+https://seedhabazar.in; contact: set GEOCODER_USER_AGENT)")

# --- SMS / WhatsApp connectors (see notify/backends.py) ---
NOTIFY_BACKENDS = {"sms": os.environ.get("NOTIFY_SMS_BACKEND", "notify.backends.LogBackend"),
                   "whatsapp": os.environ.get("NOTIFY_WHATSAPP_BACKEND", "notify.backends.WhatsAppCloudBackend" if os.environ.get("WHATSAPP_TOKEN") else "notify.backends.LogBackend"),
                   "messenger": os.environ.get("NOTIFY_MESSENGER_BACKEND", "notify.backends.MessengerBackend" if os.environ.get("FACEBOOK_PAGE_TOKEN") else "notify.backends.LogBackend")}
NOTIFY_WEBHOOK_URL = os.environ.get("NOTIFY_WEBHOOK_URL", "")
NOTIFY_WEBHOOK_SECRET = os.environ.get("NOTIFY_WEBHOOK_SECRET", "")
NOTIFY_MAX_PER_PHONE_PER_DAY = int(os.environ.get("NOTIFY_MAX_PER_PHONE_PER_DAY", "10"))

# --- Institution Connect: the KVK / research agency application, on its own address ---
# The same database, a different site: its own sign-in, its own sessions (cookies are per host), its own menus and pages.
INSTITUTION_HOSTS = [h for h in os.environ.get("INSTITUTION_HOSTS", "connect.localhost,connect.testserver").split(",") if h]
INSTITUTION_URL = os.environ.get("INSTITUTION_URL", "http://connect.localhost:8000").rstrip("/")
ALLOWED_HOSTS += [h for h in INSTITUTION_HOSTS if h not in ALLOWED_HOSTS]

# --- Feeds: district advisories and registered warehouses ---
MKISAN_ENABLED = os.environ.get("MKISAN_ENABLED", "1") == "1"
MKISAN_ADVISORY_URL = os.environ.get("MKISAN_ADVISORY_URL", "https://mkisan.gov.in/Home/Advisory")
ADVISORY_REFRESH_HOURS = float(os.environ.get("ADVISORY_REFRESH_HOURS", "6"))
IMD_API_ENABLED = os.environ.get("IMD_API_ENABLED", "0") == "1"  # only after IMD whitelists this server's IP
IMD_WARNINGS_URL = os.environ.get("IMD_WARNINGS_URL", "https://mausam.imd.gov.in/api/warnings_district_api.php")
WDRA_ENABLED = os.environ.get("WDRA_ENABLED", "1") == "1"
WDRA_LIST_URL = os.environ.get("WDRA_LIST_URL", "https://wdra.gov.in/registered-wh-public?p_p_id=in_gov_wdra_warehouse_publiclist_portlet_WarehousePubliclistPortlet_INSTANCE_faio"
                               "&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view&_in_gov_wdra_warehouse_publiclist_portlet_WarehousePubliclistPortlet_INSTANCE_faio_javax.portlet.action=processWarehouseListReport")
WDRA_REFRESH_DAYS = int(os.environ.get("WDRA_REFRESH_DAYS", "7"))
WDRA_STATES_PER_RUN = int(os.environ.get("WDRA_STATES_PER_RUN", "6"))  # spread the 37 states over the week, gently

# --- Email (sign-in codes for Institution Connect staff who choose email; console notices) ---
# Development prints mail to the server log. In production set EMAIL_HOST, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD
# (e.g. Amazon SES, Zoho, Google Workspace SMTP relay), EMAIL_PORT=587, EMAIL_USE_TLS=1 and DEFAULT_FROM_EMAIL.
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend" if not os.environ.get("EMAIL_HOST") else "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Seedha Bazar <no-reply@seedhabazar.in>")

# --- The company behind Seedha Bazar (footer, contact details for search engines) ---
COMPANY_NAME = os.environ.get("COMPANY_NAME", "Vindhyachal Farms LLP")
COMPANY_ADDRESS = os.environ.get("COMPANY_ADDRESS", "Plot number 39, Palak Vihar, Near Housing Board Colony, Maharajpur, Adhartal, Jabalpur, Madhya Pradesh")
COMPANY_EMAIL = os.environ.get("COMPANY_EMAIL", "pranav@erpion.in")
COMPANY_PHONE = os.environ.get("COMPANY_PHONE", "9770417301")
