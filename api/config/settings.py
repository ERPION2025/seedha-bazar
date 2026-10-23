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
    "market",
    "web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "web.middleware.LanguageMiddleware",
    "web.middleware.AttributionMiddleware",
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
# Pilot only, until an SMS/WhatsApp provider is connected: farmers and buyers (and numbers not yet registered) sign in
# with this fixed code. Agents, agronomists and admins always get a real random code. Set OTP_STATIC_CODE= (empty) to turn off.
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
GEOCODER_USER_AGENT = os.environ.get("GEOCODER_USER_AGENT", "SeedhaBazar/1.0 (+https://seedhabazar.in; contact: set GEOCODER_USER_AGENT)")

# --- SMS / WhatsApp connectors (see notify/backends.py) ---
NOTIFY_BACKENDS = {"sms": os.environ.get("NOTIFY_SMS_BACKEND", "notify.backends.LogBackend"),
                   "whatsapp": os.environ.get("NOTIFY_WHATSAPP_BACKEND", "notify.backends.LogBackend")}
NOTIFY_WEBHOOK_URL = os.environ.get("NOTIFY_WEBHOOK_URL", "")
NOTIFY_WEBHOOK_SECRET = os.environ.get("NOTIFY_WEBHOOK_SECRET", "")
NOTIFY_MAX_PER_PHONE_PER_DAY = int(os.environ.get("NOTIFY_MAX_PER_PHONE_PER_DAY", "10"))
