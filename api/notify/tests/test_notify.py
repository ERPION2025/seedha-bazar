import re
from unittest import mock

from django.test import TestCase, override_settings

from notify import service, texts
from notify.backends import MemoryBackend
from notify.models import Message, OptOut

MEM = {"sms": "notify.backends.MemoryBackend", "whatsapp": "notify.backends.MemoryBackend"}
PARAMS = {"crop": "Wheat", "qty": "10 quintal", "hand": "₹45,540", "cut": "₹1,260", "direct": "₹54,000", "gap": "₹8,460", "place": "Rewa",
          "date": "21 Oct", "price": "₹2,450", "msp": "", "link": "https://x/y"}


class TextTests(TestCase):
    def test_every_message_exists_in_all_languages_with_the_same_placeholders(self):
        for key, variants in texts.TEXTS.items():
            self.assertEqual(set(variants), {"en", "hi", "mr"}, key)
            ph = {lang: set(re.findall(r"\{(\w+)\}", t)) for lang, t in variants.items()}
            self.assertEqual(ph["en"], ph["hi"], key)
            self.assertEqual(ph["en"], ph["mr"], key)
            for lang in variants:
                texts.render(key, lang, PARAMS)  # no missing placeholder

    def test_messages_are_short_enough_for_sms(self):
        for key, variants in texts.TEXTS.items():
            self.assertLess(len(texts.render(key, "hi", PARAMS)), 300, key)


@override_settings(NOTIFY_BACKENDS=MEM)
class SendTests(TestCase):
    def setUp(self):
        MemoryBackend.outbox.clear()

    def test_sends_and_records(self):
        m = service.send("whatsapp", "9876543210", "calc_result", "hi", related="calculator", **PARAMS)
        self.assertEqual((m.status, m.provider, m.channel), ("sent", "memory", "whatsapp"))
        self.assertIn("सीधा बाज़ार", m.text)
        self.assertEqual(len(MemoryBackend.outbox), 1)
        self.assertTrue(m.sent_at)

    def test_default_backend_only_logs(self):
        with override_settings(NOTIFY_BACKENDS={"sms": "notify.backends.LogBackend", "whatsapp": "notify.backends.LogBackend"}):
            m = service.send("sms", "9876543210", "calc_result", "en", **PARAMS)
        self.assertEqual(m.status, "logged")  # never pretends it was delivered

    def test_opted_out_numbers_get_nothing(self):
        OptOut.objects.create(phone="9876543210")
        m = service.send("sms", "9876543210", "calc_result", "en", **PARAMS)
        self.assertEqual((m.status, m.error), ("blocked", "opted_out"))
        self.assertEqual(MemoryBackend.outbox, [])

    @override_settings(NOTIFY_MAX_PER_PHONE_PER_DAY=3)
    def test_daily_cap_per_number(self):
        statuses = [service.send("sms", "9876543210", "calc_result", "en", **PARAMS).status for _ in range(5)]
        self.assertEqual(statuses, ["sent", "sent", "sent", "blocked", "blocked"])
        self.assertEqual(service.send("sms", "9000000000", "calc_result", "en", **PARAMS).status, "sent")

    def test_a_provider_failure_is_recorded_not_raised(self):
        with mock.patch.object(MemoryBackend, "send", side_effect=RuntimeError("provider down")):
            m = service.send("sms", "9876543210", "calc_result", "en", **PARAMS)
        self.assertEqual(m.status, "failed")
        self.assertIn("provider down", m.error)

    def test_unknown_language_falls_back_to_english(self):
        self.assertTrue(service.send("sms", "9876543210", "calc_result", "xx", **PARAMS).text.startswith("Seedha Bazar"))


class WebhookTests(TestCase):
    @override_settings(NOTIFY_BACKENDS={"sms": "notify.backends.WebhookBackend", "whatsapp": "notify.backends.WebhookBackend"},
                       NOTIFY_WEBHOOK_URL="https://hooks.example/send", NOTIFY_WEBHOOK_SECRET="s3cret")
    def test_posts_signed_json(self):
        import hashlib, hmac, json
        sent = {}

        class Resp:
            headers = {"X-Message-Id": "abc123"}

            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout, context=None):
            sent["body"], sent["headers"], sent["url"] = req.data, dict(req.header_items()), req.full_url
            return Resp()

        with mock.patch("notify.backends.urllib.request.urlopen", fake_urlopen):
            m = service.send("whatsapp", "9876543210", "calc_result", "en", **PARAMS)
        self.assertEqual((m.status, m.provider_id), ("sent", "abc123"))
        self.assertEqual(sent["url"], "https://hooks.example/send")
        body = json.loads(sent["body"])
        self.assertEqual((body["to"], body["channel"], body["template"]), ("9876543210", "whatsapp", "calc_result"))
        self.assertEqual(sent["headers"]["X-seedha-signature"], hmac.new(b"s3cret", sent["body"], hashlib.sha256).hexdigest())


class LinkTests(TestCase):
    def test_whatsapp_and_sms_links(self):
        self.assertEqual(service.wa_link("hello world", "98765 43210"), "https://wa.me/919876543210?text=hello%20world")
        self.assertTrue(service.wa_link("hi").startswith("https://wa.me/?text="))
        self.assertEqual(service.sms_link("a b", "9876543210"), "sms:9876543210?body=a%20b")
