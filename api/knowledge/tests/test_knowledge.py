from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from knowledge import classify, engine, services, sources
from knowledge.models import Announcement, Article, Scheme, Source, Video
from web.tests.test_market_web import make_buyer, make_farmer

NOW = timezone.now()
RFC = (NOW - timedelta(hours=3)).strftime("%a, %d %b %Y %H:%M:%S GMT")
OLD = (NOW - timedelta(days=30)).strftime("%a, %d %b %Y %H:%M:%S GMT")

GOOGLE_FEED = f"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>x</title>
<item><title>मध्य प्रदेश में गेहूँ की सरकारी खरीद समर्थन मूल्य पर शुरू - Dainik Bhaskar</title><link>https://news.example/a1</link><pubDate>{RFC}</pubDate>
  <description>मध्य प्रदेश में गेहूँ की सरकारी खरीद समर्थन मूल्य पर शुरू</description><source url="https://bhaskar.com">Dainik Bhaskar</source></item>
<item><title>Cricket team wins the series - Sports Daily</title><link>https://news.example/a2</link><pubDate>{RFC}</pubDate><source url="https://x">Sports Daily</source></item>
<item><title>Crop insurance claims for soybean farmers in Maharashtra - The Hindu</title><link>https://news.example/a3</link><pubDate>{RFC}</pubDate><source url="https://x">The Hindu</source></item>
<item><title>Crop insurance claims for soybean farmers in Maharashtra - Another Paper</title><link>https://news.example/a3-copy</link><pubDate>{RFC}</pubDate><source url="https://y">Another Paper</source></item>
</channel></rss>"""

YT_FEED = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
<title>DD Kisan</title><entry><id>yt:video:abc123</id><yt:videoId>abc123</yt:videoId><title>गेहूँ की बुवाई का सही तरीका</title><link rel="alternate" href="https://www.youtube.com/watch?v=abc123"/>
<published>2026-10-20T10:00:00+00:00</published><media:group><media:description>किसान भाई गेहूँ की बुवाई</media:description></media:group></entry></feed>"""


class ClassifyTests(TestCase):
    def test_topics_crops_state_and_language(self):
        self.assertIn("insurance", classify.topics_of("PMFBY crop insurance claim"))
        self.assertIn("price", classify.topics_of("मंडी में भाव गिरे"))
        self.assertEqual(classify.crops_of("Soybean and wheat prices"), ["wheat", "soybean"])
        self.assertIn("onion", classify.crops_of("कांदा बाजारभाव"))
        self.assertEqual(classify.state_of("योगी सरकार का फैसला", "Madhya Pradesh"), "Uttar Pradesh")
        self.assertEqual(classify.state_of("No state named", "Maharashtra"), "Maharashtra")
        self.assertEqual(classify.language_of("Farmers in Pune", "hi"), "en")

    def test_words_match_whole_words_only(self):
        self.assertNotIn("price", classify.topics_of("Ratings agency upgrades"))  # "rate" must not match inside "ratings"

    def test_non_farming_headlines_score_zero(self):
        s, topics, crops = classify.score("Cricket team wins the series", "", 5, NOW)
        self.assertEqual((s, topics, crops), (0, [], []))


class EngineTests(TestCase):
    def setUp(self):
        self.src = Source.objects.create(name="MP search", kind="search", url="मध्य प्रदेश किसान", language="hi", state="Madhya Pradesh", trust=3)

    def test_keeps_farming_news_drops_the_rest_and_duplicates(self):
        with mock.patch.object(engine, "fetch", return_value=GOOGLE_FEED.encode()):
            added = engine.run_source(self.src)
        self.assertEqual(added, 2)
        a = Article.objects.get(url="https://news.example/a1")
        self.assertEqual((a.outlet, a.language, a.state), ("Dainik Bhaskar", "hi", "Madhya Pradesh"))
        self.assertNotIn("Dainik Bhaskar", a.title)
        self.assertIn("wheat", a.crops)
        self.assertIn("price", a.topics)
        self.assertEqual(a.summary, "")  # Google repeats the headline as the snippet
        b = Article.objects.get(url="https://news.example/a3")
        self.assertEqual((b.state, b.language), ("Maharashtra", "en"))
        self.assertFalse(Article.objects.filter(url="https://news.example/a3-copy").exists())
        self.src.refresh_from_db()
        self.assertEqual((self.src.last_error, self.src.last_count), ("", 4))
        with mock.patch.object(engine, "fetch", return_value=GOOGLE_FEED.encode()):
            self.assertEqual(engine.run_source(self.src), 0)  # running again adds nothing

    def test_a_broken_feed_is_recorded_and_does_not_stop_others(self):
        other = Source.objects.create(name="ok", kind="rss", url="https://ok.example/rss", language="hi")
        def fake(url):
            if "news.google" in url:
                raise OSError("timed out")
            return GOOGLE_FEED.encode()
        with mock.patch.object(engine, "fetch", side_effect=fake):
            out = engine.run_all()
        self.assertEqual((out["failed"], out["added"]), (1, 2))
        self.src.refresh_from_db()
        self.assertIn("timed out", self.src.last_error)

    def test_youtube_channel_becomes_videos(self):
        yt = Source.objects.create(name="DD Kisan", kind="youtube", url="UCnDfmcUyhgJp6xC1LmBLfUg", language="hi", trust=5)
        self.assertIn("channel_id=UCnDfmcUyhgJp6xC1LmBLfUg", sources.feed_url(yt))
        with mock.patch.object(engine, "fetch", return_value=YT_FEED.encode()):
            self.assertEqual(engine.run_source(yt), 1)
        v = Video.objects.get()
        self.assertEqual((v.video_id, v.channel), ("abc123", "DD Kisan"))
        self.assertIn("youtube-nocookie.com/embed/abc123", v.embed_url)
        self.assertIn("wheat", v.crops)

    def test_old_items_are_pruned_and_due_follows_the_schedule(self):
        Article.objects.create(source=self.src, title="old", url="https://o.example/1", title_key="k", published_at=NOW - timedelta(days=90))
        self.assertEqual(engine.prune(), 1)
        self.assertTrue(engine.due())
        Source.objects.update(last_run=NOW)
        self.assertFalse(engine.due())
        self.assertTrue(engine.due(NOW + timedelta(hours=7)))

    def test_search_sources_ask_google_news_in_their_language(self):
        url = sources.feed_url(self.src)
        self.assertTrue(url.startswith("https://news.google.com/rss/search?q="))
        self.assertIn("hl=hi", url)


class RankingTests(TestCase):
    def setUp(self):
        src = Source.objects.create(name="s", kind="rss", url="https://s.example", language="en")
        mk = lambda n, **kw: Article.objects.create(source=src, title=n, url=f"https://s.example/{n}", title_key=n, published_at=kw.pop("at", NOW), score=12, **kw)
        self.mp = mk("mp-wheat", state="Madhya Pradesh", crops=["wheat"], language="hi")
        self.up = mk("up-sugar", state="Uttar Pradesh", crops=["sugarcane"], language="hi")
        self.old = mk("old", at=NOW - timedelta(days=20), language="hi")

    def test_a_farmer_sees_their_state_and_crops_first(self):
        farmer = make_farmer()
        rows, total = services.ranked_articles(farmer, "hi")
        self.assertEqual((rows[0], rows[-1], total), (self.mp, self.old, 3))

    def test_topic_and_language_filters(self):
        self.mp.topics = ["price"]
        self.mp.save()
        rows, _ = services.ranked_articles(None, "hi", topic="price")
        self.assertEqual(rows, [self.mp])
        self.assertEqual(services.ranked_articles(None, "hi", language="en")[0], [])

    def test_announcements_reach_the_right_people(self):
        Announcement.objects.create(title="For farmers in Rewa", audience="farmer", district="Rewa")
        Announcement.objects.create(title="For buyers", audience="buyer")
        Announcement.objects.create(title="Old", audience="all", ends_at=NOW - timedelta(days=1))
        Announcement.objects.create(title="Marathi only", audience="all", language="mr")
        farmer = make_farmer()
        titles = [a.title for a in services.announcements_for(farmer, "hi", 10)]
        self.assertEqual(titles, ["For farmers in Rewa"])
        self.assertEqual([a.title for a in services.announcements_for(make_buyer(), "mr", 10)], ["Marathi only", "For buyers"])


class PageTests(TestCase):
    def setUp(self):
        call_command("seed_knowledge", stdout=StringIO())
        src = Source.objects.first()
        Article.objects.create(source=src, title="Wheat procurement starts", url="https://s.example/1", title_key="1", published_at=NOW, score=14, topics=["price"], crops=["wheat"])
        Video.objects.create(title="Sowing wheat", video_id="abc123", channel="DD Kisan")

    def test_seed_is_safe_to_run_twice_and_keeps_staff_edits(self):
        Scheme.objects.filter(slug="pmfby").update(short="edited by staff")
        call_command("seed_knowledge", stdout=StringIO())
        self.assertEqual(Scheme.objects.count(), 12)
        self.assertEqual(Scheme.objects.get(slug="pmfby").short, "edited by staff")

    def test_pages_render_in_every_language_for_everyone(self):
        farmer, buyer = make_farmer(), make_buyer()
        for who in (None, farmer, buyer):
            c = Client()
            if who:
                c.force_login(who)
            for lang in ("hi", "mr", "en"):
                for path in ("/news/", "/news/?topic=price", "/news/?language=en", "/schemes/", "/schemes/?topic=bulk_purchase", "/schemes/pmfby/", "/videos/"):
                    self.assertEqual(c.get(f"{path}{'&' if '?' in path else '?'}lang={lang}").status_code, 200, (path, lang))
        page = Client().get("/schemes/pmfby/?lang=hi").content.decode()
        self.assertIn("पीएम फसल बीमा योजना", page)
        self.assertIn("pmfby.gov.in", page)
        self.assertIn("youtube-nocookie.com/embed/abc123", Client().get("/videos/").content.decode())

    def test_home_pages_show_news_for_you(self):
        c = Client()
        c.force_login(make_farmer())
        self.assertContains(c.get("/farmer/?lang=en"), "Wheat procurement starts")

    def test_staff_console_posts_announcements_and_switches_sources(self):
        from web.tests.test_web import staff
        c = Client()
        c.force_login(staff())
        self.assertEqual(c.get("/console/news/?lang=en").status_code, 200)
        c.post("/console/news/announce/", {"title": "Wheat procurement opens Monday", "audience": "farmer", "language": "", "body": "Register now"})
        a = Announcement.objects.get()
        farmer = Client()
        farmer.force_login(make_farmer())
        self.assertContains(farmer.get("/farmer/?lang=en"), "Wheat procurement opens Monday")
        c.post(f"/console/news/announce/{a.pk}/end/")
        self.assertNotContains(farmer.get("/farmer/?lang=en"), "Wheat procurement opens Monday")
        s = Source.objects.first()
        c.post(f"/console/news/source/{s.pk}/toggle/")
        s.refresh_from_db()
        self.assertFalse(s.active)
        self.assertEqual(Client().get("/console/news/").status_code, 302)
