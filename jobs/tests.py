import csv
import json
import tempfile
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from . import fetchers, llm, scheduler, sync
from .dedupe import dedupe_hash, norm_title, similar_titles
from .fetchers import Listing, is_fresher_job, min_years_required
from .models import Job, SyncLog
from .places import parse_location
from .tagging import clean_role, rules_role

IST = ZoneInfo("Asia/Kolkata")


def make_job(title="Junior Dev", company="Acme", city="Pune", source="Lever", role="Software Engineering", **kw):
    kw.setdefault("location", f"{city}, India")
    return Job.objects.create(title=title, company=company, city=city, role=role, source=source,
                              apply_url="https://example.com/x", **kw)


def listing(title="Junior Dev", company="Acme", city="Pune", source="Lever", n=1, snippet=""):
    return Listing(title, company, f"{city}, India", source, f"https://a.com/{n}", city, snippet)


class PlacesTests(TestCase):
    def test_india_detection(self):
        self.assertEqual(parse_location("Bangalore, Karnataka"), ("Bengaluru", True))
        self.assertEqual(parse_location("Remote - India"), ("Remote", True))
        self.assertEqual(parse_location("Hybrid - Gurgaon"), ("Gurugram", True))
        self.assertEqual(parse_location("Pune / Mumbai"), ("Pune", True))  # first one written wins
        self.assertEqual(parse_location("Rajkot, Gujarat"), ("Rajkot", True))
        self.assertEqual(parse_location("India"), ("India (unspecified)", True))

    def test_non_india_rejected(self):
        for text in ["Berlin, Germany", "Remote", "Indianapolis, IN", "San Francisco", ""]:
            self.assertFalse(parse_location(text)[1], text)

    def test_india_only_sources_trust_bare_remote(self):
        self.assertEqual(parse_location("Remote", india_source=True), ("Remote", True))


class DedupeTests(TestCase):
    def test_same_job_different_spelling(self):
        a = dedupe_hash("Acme Pvt. Ltd.", "Software Intern (m/f/d)", "Pune")
        b = dedupe_hash("ACME", "software internship", "Pune")
        self.assertEqual(a, b)
        self.assertNotEqual(a, dedupe_hash("Acme", "Software Intern", "Mumbai"))

    def test_fuzzy_titles(self):
        self.assertTrue(similar_titles(norm_title("Junior Python Developer"), norm_title("Junior Python Developers")))
        self.assertFalse(similar_titles(norm_title("Data Analyst Intern"), norm_title("Marketing Intern")))


class TaggingTests(TestCase):
    def test_rules_role(self):
        self.assertEqual(rules_role("Junior React Native Developer"), "Mobile")
        self.assertEqual(rules_role("Data Analyst Intern"), "Data & Analytics")
        self.assertEqual(rules_role("Founders Associate Intern"), "Other")

    def test_clean_role_forces_taxonomy(self):
        self.assertEqual(clean_role("frontend"), "Frontend")
        self.assertEqual(clean_role("Wizard"), "Other")
        self.assertEqual(clean_role(" ai / ml "), "AI / ML")
        self.assertEqual(clean_role(None), "Other")


class FresherFilterTests(TestCase):
    def test_accepts_entry_level_titles(self):
        for title in ["Software Engineer Intern", "Junior Python Developer", "Graduate Trainee", "Jr. Data Analyst", "Entry-Level QA"]:
            self.assertTrue(is_fresher_job(title), title)

    def test_rejects_senior_titles(self):
        for title in ["Senior Intern Coordinator", "Lead Developer", "Engineering Manager", "Staff Engineer"]:
            self.assertFalse(is_fresher_job(title), title)

    def test_word_boundaries(self):
        self.assertFalse(is_fresher_job("Internal Tools Engineer"))
        self.assertFalse(is_fresher_job("International Sales Rep"))

    def test_experience_years_in_description(self):
        self.assertEqual(min_years_required("Requires 3-5 years of experience"), 3)
        self.assertEqual(min_years_required("Our company is 10 years old. 0-1 year experience"), 0)
        self.assertFalse(is_fresher_job("Junior Developer", "We need 4+ years of experience"))
        self.assertTrue(is_fresher_job("Junior Developer", "0-1 year experience is fine"))

    def test_listing_filters(self):
        self.assertIsNone(fetchers._listing("Junior Dev", "Acme", "India", "Lever", "javascript:alert(1)"))
        self.assertIsNone(fetchers._listing("Junior Dev", "Acme", "Berlin, Germany", "Lever", "https://a.com/1"))
        ok = fetchers._listing("Junior Dev", "Acme", "Bangalore", "Lever", "https://a.com/1", "<p>hello</p>")
        self.assertEqual((ok.city, ok.snippet), ("Bengaluru", "hello"))
        self.assertIsNotNone(fetchers._listing("Junior Dev", "Acme", None, "Adzuna India", "https://a.com/2"))


def fake_llm(tokens=(1000, 200), cost=0.0003):
    """Stand-in for llm.tag_all: tags every post as a Data role in Pune."""
    def run(posts):
        return {p["id"]: ("Data & Analytics", "Pune") for p in posts}, 1, tokens[0], tokens[1], cost, []
    return run


@override_settings(OPENROUTER_API_KEY="test-key")
class SyncTests(TestCase):
    def run_with(self, listings, errors=(), tagger=None):
        with mock.patch.object(fetchers, "collect", return_value=(list(listings), list(errors))), \
             mock.patch.object(llm, "tag_all", tagger or fake_llm()):
            return sync.run_sync()

    def test_adds_dedupes_and_logs(self):
        a, b = listing(), listing("Intern", "Beta", "Mumbai", n=2)
        log = self.run_with([a, a, b])
        self.assertEqual((log.status, log.added, log.duplicates, log.total_active), ("success", 2, 1, 2))
        log2 = self.run_with([a, b])
        self.assertEqual((log2.added, Job.objects.count()), (0, 2))

    def test_same_job_on_two_boards_is_one_row(self):
        log = self.run_with([listing(source="Lever"), listing(source="Adzuna India", n=2)])
        self.assertEqual((log.added, log.duplicates), (1, 1))

    def test_fuzzy_duplicate_against_database(self):
        make_job("Junior Python Developer", "Acme", "Pune")
        log = self.run_with([listing("Junior Python Developer Role", "Acme Pvt Ltd", "Pune")])
        self.assertEqual((log.added, log.duplicates), (0, 1))

    def test_llm_tags_are_stored_and_tokens_logged(self):
        log = self.run_with([listing("Analyst Intern", "Acme", "Pune")])
        job = Job.objects.get()
        self.assertEqual((job.role, job.city, job.tag_method), ("Data & Analytics", "Pune", "llm"))
        self.assertEqual((log.tagged_llm, log.tagged_rules, log.llm_calls, log.tokens_in, log.tokens_out), (1, 0, 1, 1000, 200))
        self.assertAlmostEqual(log.llm_cost_usd, 0.0003)

    def test_llm_failure_keeps_rule_tags(self):
        failing = lambda posts: ({}, 0, 0, 0, 0.0, ["LLM batch 1: Timeout"])
        log = self.run_with([listing("Data Analyst Intern", "Acme", "Pune")], tagger=failing)
        job = Job.objects.get()
        self.assertEqual((job.role, job.tag_method), ("Data & Analytics", "rules"))
        self.assertEqual((log.status, log.tagged_rules), ("partial", 1))

    @override_settings(OPENROUTER_API_KEY="")
    def test_no_api_key_falls_back_to_rules(self):
        log = self.run_with([listing()])
        self.assertEqual((Job.objects.get().tag_method, log.status), ("rules", "partial"))
        self.assertIn("OPENROUTER_API_KEY", log.errors)

    def test_expires_jobs_no_longer_listed(self):
        old = make_job("Old Intern")
        Job.objects.filter(pk=old.pk).update(last_seen=timezone.now() - timedelta(days=10))
        log = self.run_with([listing("New Intern", "Beta", n=2)])
        old.refresh_from_db()
        self.assertFalse(old.is_active)
        self.assertEqual(log.expired, 1)

    def test_outage_does_not_expire_jobs(self):
        old = make_job()
        Job.objects.filter(pk=old.pk).update(last_seen=timezone.now() - timedelta(days=30))
        log = self.run_with([], ["all sources: no internet"])
        old.refresh_from_db()
        self.assertTrue(old.is_active)
        self.assertEqual(log.status, "failed")

    def test_skips_when_another_sync_is_running(self):
        SyncLog.objects.create()
        self.assertIsNone(self.run_with([]))

    def test_crash_is_logged_not_raised(self):
        with mock.patch.object(fetchers, "collect", side_effect=RuntimeError("boom")):
            log = sync.run_sync()
        self.assertEqual(log.status, "failed")
        self.assertIn("boom", log.errors)


class LLMClientTests(TestCase):
    def reply(self, text, usage=(500, 80), cost=0.00012, error=None):
        resp = mock.Mock()
        body = {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1], "cost": cost}}
        if error:
            body = {"error": {"message": error}}
        resp.status_code = 200
        resp.headers = {}
        resp.text = ""
        resp.json.return_value = body
        return resp

    def posts(self):
        return [{"id": 1, "title": "SDE Intern", "company": "A", "location": "Bangalore", "about": "", "fallback_city": "Bengaluru"},
                {"id": 2, "title": "Mystery", "company": "B", "location": "India", "about": "", "fallback_city": "India (unspecified)"}]

    @override_settings(OPENROUTER_API_KEY="k", LLM_MODEL="some/model")
    def test_request_shape_and_parsing(self):
        text = '```json\n[{"id": 1, "role": "Software Engineering", "city": "Bangalore"}, {"id": 2, "role": "Wizard", "city": ""}]\n```'
        session = mock.Mock()
        session.post.return_value = self.reply(text)
        out, tin, tout, cost = llm.tag_batch(session, self.posts())
        self.assertEqual(out[1], ("Software Engineering", "Bengaluru"))
        self.assertEqual(out[2], ("Other", "India (unspecified)"))  # unknown role -> Other, empty city -> fallback
        self.assertEqual((tin, tout, cost), (500, 80, 0.00012))
        call = session.post.call_args
        self.assertEqual(call.args[0], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer k")
        body = call.kwargs["json"]
        self.assertEqual((body["model"], body["temperature"]), ("some/model", 0))
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertIn("Never invent a role", body["messages"][0]["content"])
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["usage"], {"include": True})

    @override_settings(OPENROUTER_API_KEY="k")
    def test_error_inside_http_200_is_raised(self):
        session = mock.Mock()
        session.post.return_value = self.reply("", error="Provider returned error")
        with self.assertRaisesRegex(RuntimeError, "Provider returned error"):
            llm.tag_batch(session, self.posts())

    @override_settings(OPENROUTER_API_KEY="k", LLM_MIN_REQUEST_INTERVAL_SECONDS=0)
    def test_bad_batch_is_skipped_not_fatal(self):
        with mock.patch.object(llm, "_session") as sess:
            sess.return_value.post.side_effect = [self.reply("sorry, I cannot"), self.reply('[{"id": 21, "role": "QA & Testing", "city": "Pune"}]')]
            posts = [{"id": i, "title": "t", "company": "c", "location": "l", "about": "", "fallback_city": "Pune"} for i in range(1, 22)]
            results, calls, tin, tout, cost, errors = llm.tag_all(posts)
        self.assertEqual((len(results), calls, len(errors)), (1, 1, 1))

    @override_settings(OPENROUTER_API_KEY="k")
    def test_rate_limit_stops_remaining_batches(self):
        limited = mock.Mock()
        limited.status_code = 429
        limited.headers = {"Retry-After": "60"}
        limited.text = '{"error":{"message":"Provider returned error"}}'
        limited.json.return_value = {
            "error": {
                "code": 429,
                "message": "Provider returned error",
                "metadata": {
                    "limit_source": "upstream_provider_shared_pool",
                    "provider_name": "ExampleProvider",
                    "provider_code": 429,
                },
            }
        }
        with mock.patch.object(llm, "_session") as sess:
            sess.return_value.post.return_value = limited
            posts = [{"id": i, "title": "t", "company": "c", "location": "l", "about": "", "fallback_city": "Pune"} for i in range(1, 61)]
            results, calls, tin, tout, cost, errors = llm.tag_all(posts)
        self.assertEqual((results, calls), ({}, 0))
        self.assertEqual(sess.return_value.post.call_count, 1)
        self.assertIn("429", errors[0])
        self.assertIn("upstream_provider_shared_pool", errors[0])
        self.assertIn("ExampleProvider", errors[0])
        self.assertIn("Remaining batches were not sent", errors[0])

    @override_settings(OPENROUTER_API_KEY="k")
    def test_json_object_response_is_supported(self):
        session = mock.Mock()
        session.post.return_value = self.reply('{"posts":[{"id":1,"role":"Backend","city":"Pune"}]}')
        out, _, _, _ = llm.tag_batch(session, self.posts())
        self.assertEqual(out[1], ("Backend", "Pune"))


class EvalTests(TestCase):
    def test_sample_blind_sheet_and_scoring(self):
        for i in range(6):
            make_job(f"Data Analyst Intern {i}", f"Co{i}", "Pune", role="Data & Analytics", tag_method="llm")
        with tempfile.TemporaryDirectory() as d:
            sheet, key = str(Path(d, "s.csv")), str(Path(d, "k.csv"))
            call_command("eval_sample", n=5, sheet=sheet, key=key, stdout=StringIO())
            rows = list(csv.DictReader(open(sheet, encoding="utf-8-sig")))
            self.assertEqual(len(rows), 5)
            self.assertNotIn("llm_role", rows[0])  # labels are hidden from the human
            for r in rows:
                r["human_role"], r["human_city"] = "Data & Analytics", "Pune"
            rows[0]["human_role"] = "Product"  # one deliberate disagreement
            with open(sheet, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=rows[0].keys())
                w.writeheader(); w.writerows(rows)
            out = StringIO()
            call_command("eval_score", sheet=sheet, key=key, stdout=out)
        self.assertIn("role  AI (LLM)", out.getvalue())
        self.assertIn("4/5 =  80.0%", out.getvalue())
        self.assertRegex(out.getvalue(), r"city  AI \(LLM\)\s+5/5")

    def test_cost_report_prefers_real_openrouter_cost(self):
        SyncLog.objects.create(status="success", tagged_llm=1000, llm_calls=50, tokens_in=80_000, tokens_out=22_000, llm_cost_usd=0.0123)
        out = StringIO()
        call_command("cost_report", stdout=out)
        self.assertIn("COST PER 1,000 POSTS: $0.0123", out.getvalue())
        self.assertIn("billed by OpenRouter", out.getvalue())

    @override_settings(LLM_PRICE_IN=0.15, LLM_PRICE_OUT=0.60, LLM_MODEL="example/paid-model")
    def test_cost_report_falls_back_to_token_prices(self):
        SyncLog.objects.create(status="success", tagged_llm=1000, llm_calls=50, tokens_in=80_000, tokens_out=22_000)
        out = StringIO()
        call_command("cost_report", stdout=out)
        self.assertIn("COST PER 1,000 POSTS: $0.0252", out.getvalue())  # 0.08M*$0.15 + 0.022M*$0.60

    @override_settings(LLM_MODEL="google/gemma-4-26b-a4b-it:free", LLM_PRICE_IN=0.20, LLM_PRICE_OUT=0.40)
    def test_cost_report_keeps_zero_cost_for_free_model(self):
        SyncLog.objects.create(status="success", tagged_llm=1000, llm_calls=50, tokens_in=80_000, tokens_out=22_000, llm_cost_usd=0.0)
        out = StringIO()
        call_command("cost_report", stdout=out)
        self.assertIn("COST PER 1,000 POSTS: $0.0000", out.getvalue())
        self.assertIn("zero-priced OpenRouter free model", out.getvalue())


@override_settings(TIME_ZONE="Asia/Kolkata", AUTO_SYNC_AT=(0, 5))
class SchedulerTests(TestCase):
    def test_next_run_is_just_after_midnight_ist(self):
        now = datetime(2026, 11, 19, 15, 0, tzinfo=IST)
        self.assertEqual(scheduler.next_run(now), datetime(2026, 11, 20, 0, 5, tzinfo=IST))

    def test_catch_up_when_a_night_was_missed(self):
        now = datetime(2026, 11, 19, 9, 0, tzinfo=IST)
        self.assertTrue(scheduler.is_due(now))
        SyncLog.objects.create(status="success", finished_at=datetime(2026, 11, 18, 0, 10, tzinfo=IST))
        self.assertTrue(scheduler.is_due(now))
        SyncLog.objects.create(status="success", finished_at=datetime(2026, 11, 19, 0, 7, tzinfo=IST))
        self.assertFalse(scheduler.is_due(now))

    def test_failed_sync_does_not_count(self):
        SyncLog.objects.create(status="failed", finished_at=datetime(2026, 11, 19, 0, 7, tzinfo=IST))
        self.assertTrue(scheduler.is_due(datetime(2026, 11, 19, 9, 0, tzinfo=IST)))


class ViewTests(TestCase):
    def setUp(self):
        make_job("Junior Python Dev", "Acme", "Bengaluru", "Lever", "Backend")
        make_job("Data Intern", "Beta", "Pune", "Greenhouse", "Data & Analytics", tag_method="llm")
        make_job("Hidden Intern", "Gamma", "Pune", "Lever", is_active=False)

    def test_index_renders_with_chips(self):
        res = self.client.get("/")
        self.assertContains(res, "Fresher Radar")
        self.assertContains(res, 'data-city="Pune"')
        self.assertContains(res, 'data-role="Backend"')
        self.assertEqual(res.context["total"], 2)

    def test_api_filters(self):
        get = lambda **p: self.client.get("/api/jobs/", p).json()
        self.assertEqual(get()["total_count"], 2)
        self.assertEqual(get(q="python")["total_count"], 1)
        self.assertEqual(get(role="Data & Analytics")["jobs"][0]["company"], "Beta")
        self.assertEqual(get(city="Bengaluru")["total_count"], 1)
        self.assertEqual(get(loc="pun")["total_count"], 1)
        self.assertEqual(get(source="lever")["total_count"], 1)
        self.assertEqual(get(new="1")["total_count"], 2)

    def test_api_returns_role_city_and_ai_flag(self):
        job = self.client.get("/api/jobs/", {"q": "data"}).json()["jobs"][0]
        self.assertEqual((job["role"], job["city"], job["ai"]), ("Data & Analytics", "Pune", True))

    def test_sync_overdue_flag(self):
        Job.objects.update(first_seen=timezone.now() - timedelta(days=3))
        self.assertTrue(self.client.get("/").context["sync_overdue"])
        SyncLog.objects.create(status="success", finished_at=timezone.now())
        self.assertFalse(self.client.get("/").context["sync_overdue"])

    def test_api_pagination_and_bad_input(self):
        data = self.client.get("/api/jobs/", {"limit": 1}).json()
        self.assertEqual((len(data["jobs"]), data["has_more"]), (1, True))
        data = self.client.get("/api/jobs/", {"limit": "abc", "offset": "-5"}).json()
        self.assertEqual(len(data["jobs"]), 2)
