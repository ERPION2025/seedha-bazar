"""What each outside service needs, whether it is set up, and how to set it up. Shown to staff in Console > Settings.

Secrets (keys, tokens) are read from the server's environment, never stored in the database or shown on screen.
"""
from django.conf import settings


def _set(*names) -> bool:
    return all(bool(getattr(settings, n, "")) for n in names)


def status() -> list[dict]:
    return [
        {"name": "Mandi prices (Agmarknet via data.gov.in)", "ok": _set("DATA_GOV_IN_API_KEY"), "free": True, "env": ["DATA_GOV_IN_API_KEY"],
         "steps": ["Sign up at data.gov.in and open My Account > API key (free).", "Set DATA_GOV_IN_API_KEY on the server and restart. Prices refresh daily."]},
        {"name": "Weather forecasts (Open-Meteo)", "ok": True, "free": True, "env": ["WEATHER_API_KEY (only for commercial use)"],
         "steps": ["Works now with no key or sign-up: the free Open-Meteo service is used.",
                   "Open-Meteo's free service is for non-commercial use. When Seedha Bazar earns money, buy an Open-Meteo API plan and set WEATHER_API_KEY; nothing else changes.",
                   "Alternative: IMD (India Meteorological Department) offers data to registered organisations; ask IMD for API access and an IP whitelist."]},
        {"name": "Maps", "ok": True, "free": True, "env": ["MAP_PROVIDER=osm (default) or google", "GOOGLE_MAPS_API_KEY (only for google)"],
         "steps": ["Works now with OpenStreetMap: free, no key. For heavy traffic in production, use a tile host (e.g. a paid OSM tile provider) and set MAP_TILE_URL.",
                   "To use Google Maps instead: Google Cloud Console > new project > enable 'Maps JavaScript API' > Billing (a card is needed; usage under Google's monthly free limits costs nothing) > Credentials > API key.",
                   "Restrict the key: Application restriction 'Websites' with your domain, API restriction 'Maps JavaScript API'.",
                   "Set MAP_PROVIDER=google and GOOGLE_MAPS_API_KEY=<key>, restart. 'Directions' links open Google Maps with no key at all."]},
        {"name": "Facebook Login", "ok": _set("FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET"), "free": True, "env": ["FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET"],
         "steps": ["developers.facebook.com > Create app > use case 'Authenticate and request data from users with Facebook Login'.",
                   f"Valid OAuth redirect URI: {settings.SITE_URL}/auth/facebook/callback/ ; Data deletion callback: {settings.SITE_URL}/auth/facebook/data-deletion/ ; Privacy policy URL: {settings.SITE_URL}/privacy/",
                   "Set FACEBOOK_APP_ID and FACEBOOK_APP_SECRET, restart, then tick 'Facebook login' below. Switch the app to Live mode after Meta's review."]},
        {"name": "WhatsApp messages (WhatsApp Business Cloud API)", "ok": _set("WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"), "free": False,
         "env": ["WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "NOTIFY_WHATSAPP_BACKEND=notify.backends.WhatsAppCloudBackend"],
         "steps": ["Meta Business Suite > WhatsApp > add a phone number (verified business).", "Create message templates (utility category) for alerts in Hindi, Marathi and English and get them approved.",
                   "Make a permanent System User token with whatsapp_business_messaging permission.", "Meta charges per conversation; service replies within 24 hours are free."]},
        {"name": "Facebook Messenger messages", "ok": _set("FACEBOOK_PAGE_TOKEN", "META_VERIFY_TOKEN"), "free": True,
         "env": ["FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_TOKEN", "META_VERIFY_TOKEN", "FACEBOOK_APP_SECRET"],
         "steps": ["Connect the Seedha Bazar Facebook Page to the same Meta app; add the Messenger product.", f"Webhook URL: {settings.SITE_URL}/hooks/meta/ with your META_VERIFY_TOKEN; subscribe to 'messages' and 'messaging_referrals'.",
                   "People link Messenger by tapping 'Get alerts on Messenger' in their notification settings (they message the Page once).",
                   "Meta allows Pages to message a person freely only within 24 hours of their last message; outside that, only for specific purposes. Alerts after 24 hours go by app notification, SMS or WhatsApp instead."]},
        {"name": "Phone notifications (Web Push)", "ok": _set("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY"), "free": True, "env": ["VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_EMAIL"],
         "steps": ["Run: python manage.py make_vapid_keys  (prints a key pair) and set the three values.", "Works in Chrome/Edge/Firefox on Android and desktop, and on iPhone when the site is added to the Home Screen.",
                   "A browser notification uses the phone's notification sound. Our own tune plays inside the app; for a custom tune in the phone's notification shade, wrap the site as an Android app (Trusted Web Activity) and use the tune in web/static/web/sounds/notify.wav."]},
        {"name": "SMS", "ok": getattr(settings, "NOTIFY_BACKENDS", {}).get("sms", "").endswith("WebhookBackend"), "free": False, "env": ["NOTIFY_SMS_BACKEND", "NOTIFY_WEBHOOK_URL", "NOTIFY_WEBHOOK_SECRET"],
         "steps": ["Pick a DLT-registered SMS provider, register sender ID and templates on the DLT portal, then point the webhook to the provider (or n8n/Make)."]},
        {"name": "Speech to text", "ok": True, "free": True, "env": ["BHASHINI_USER_ID, BHASHINI_API_KEY (optional, server-side)"],
         "steps": ["Works now in Chrome on Android: speech is turned into text by the phone's browser for Hindi, Marathi, Bengali, Tamil, Telugu, Gujarati, Kannada, Malayalam, Punjabi, Urdu and English.",
                   "Optional: Bhashini (Government of India, free after registration at bhashini.gov.in) for turning recorded voice notes into text on the server in 22 Indian languages."]},
    ]
