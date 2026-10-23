from django.test import TestCase, override_settings

from advisory import imd, mkisan, services
from advisory.models import Advisory, FeedRun

PAGE = """
<div class="post"><div class="user-block"><span class="username"><a href="#">Mr. VIJAY JAIN</a>
<span class="small">(Senior scientist and Head)</span></span><span class="description">Shared on - 7/9/2026 10:44:26 AM</span></div>
<!-- /.user-block --><p>धान पर खरपतवार नियंत्रण हेतु बुवाई के 20-25 दिन के अंदर छिडकाव करें । कृषि विज्ञान केंद्र, पाहन्दा (अ), दुर्ग</p><p>Share</p><input class="x">
<div class="post"><div class="user-block"><span class="username"><a href="#">Mr. VIJAY JAIN</a>
<span class="small">(Senior scientist and Head)</span></span><span class="description">Shared on - 7/9/2026 10:36:47 AM</span></div>
<!-- /.user-block --><p>अधिक दूध उत्पादन के लिए पशुओं को हरा चारा 25 से 30 किलो प्रति दिन खिलायें।</p><p>Share</p><input class="x">
<div class="post"><div class="user-block"><span class="username"><a href="#">DR R.LATHA</a>
<span class="small">(Senior scientist and Head)</span></span><span class="description">Shared on - 7/9/2026 2:58:34 PM</span></div>
<!-- /.user-block --><p>
</p><p>Share</p><input class="x">
"""


@override_settings(NOTIFY_BACKENDS={"sms": "notify.backends.MemoryBackend", "whatsapp": "notify.backends.MemoryBackend", "messenger": "notify.backends.MemoryBackend"})
class FeedTests(TestCase):
    def test_mkisan_posts_are_read_placed_and_read_only_once(self):
        out = mkisan.sync(PAGE)
        self.assertEqual(out, {"ok": True, "fetched": 2, "saved": 2})  # the picture-only post is skipped
        rice = Advisory.objects.get(text__contains="खरपतवार")
        self.assertEqual((rice.state, rice.district, rice.kind, rice.source), ("Chhattisgarh", "Durg", "pest", "mkisan"))
        milk = Advisory.objects.get(text__contains="दूध")
        self.assertEqual((milk.district, milk.kind), ("Durg", "livestock"))  # placed by the same scientist's signed post
        self.assertEqual(mkisan.sync(PAGE)["saved"], 0)
        self.assertEqual(FeedRun.objects.filter(feed="mkisan", ok=True).count(), 2)

    def test_a_broken_feed_is_recorded_not_raised(self):
        from unittest import mock
        self.assertTrue(services.due("mkisan", 6))  # never read: due
        with mock.patch("advisory.mkisan.fetch", side_effect=OSError("timed out")):
            self.assertEqual(mkisan.sync(), {"ok": False, "fetched": 0, "saved": 0})
        self.assertIn("timed out", FeedRun.objects.get().error)
        self.assertFalse(services.due("mkisan", 6))  # retried after an hour, not at once

    def test_imd_warnings_become_district_advisories(self):
        rows = [{"District": "Rewa", "Date": "2026-10-23", "Day_1": "2,4", "Day1_Color": "2", "Day_2": "1", "Day2_Color": "4"},
                {"District": "Nowhere", "Day_1": "2", "Day1_Color": "1"}]
        out = imd.sync(rows)
        self.assertEqual(out["saved"], 1)
        a = Advisory.objects.get()
        self.assertEqual((a.source, a.district, a.severity, a.kind), ("imd", "Rewa", "warning", "weather"))
        self.assertIn("Heavy rain", a.text)

    def test_text_is_sorted_into_topic_crop_and_place(self):
        self.assertEqual(services.classify("Heavy rain expected, drain the field")[0:2], ("weather", "warning"))
        self.assertIn("wheat", services.crops_in("Sow wheat variety HI-1544 now"))
        self.assertEqual(services.locate("Apply zinc. KVK East Kameng")[:2], ("Arunachal Pradesh", "East Kameng"))
        self.assertEqual(services.locate("No signature here")[:2], ("", ""))
