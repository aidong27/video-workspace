"""Offline tests for Bilibili link parsing, WBI caching and platform refusals.

Every HTTP call is replaced by a fake client; nothing here contacts Bilibili.
"""

import unittest
from unittest.mock import patch


from app import main
from app.bilibili import (
    PlatformAccessGuard,
    WbiKeyCache,
    extract_aid,
    mixin_key_from_nav,
    wbi_sign,
)
from app.errors import USER_ERROR_MESSAGES, stable_error_code


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []

    def __call__(self, **_kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def get(self, url):
        self.urls.append(url)
        return self.responses.pop(0)


VIEW_OK = {"code": 0, "data": {"bvid": "BV14jFvzbEvj", "aid": 42, "cid": 7, "title": "t", "pages": [{"cid": 7}]}}
NAV_OK = {
    "code": -101,
    "data": {
        "wbi_img": {
            "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
            "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
        }
    },
}


class GuardedTestCase(unittest.TestCase):
    def setUp(self) -> None:
        main.BILI_ACCESS_GUARD.reset()
        main.BILI_WBI_KEYS.invalidate()

    def tearDown(self) -> None:
        main.BILI_ACCESS_GUARD.reset()
        main.BILI_WBI_KEYS.invalidate()


class LinkParsingTests(unittest.TestCase):
    def test_extract_aid_reads_video_paths_only(self) -> None:
        self.assertEqual(extract_aid("https://www.bilibili.com/video/av170001?p=2"), 170001)
        self.assertEqual(extract_aid("https://www.bilibili.com/video/AV170001/"), 170001)
        self.assertIsNone(extract_aid("https://www.bilibili.com/video/BV14jFvzbEvj"))
        self.assertIsNone(extract_aid("https://www.bilibili.com/read/av170001"))
        self.assertIsNone(extract_aid("https://www.bilibili.com/video/av0"))

    def test_platform_refusal_has_a_stable_public_message(self) -> None:
        code = stable_error_code("platform_risk_control")
        self.assertEqual(code, "platform_blocked")
        self.assertIn("上传本地视频", USER_ERROR_MESSAGES[code])
        self.assertEqual(stable_error_code("api_request_failed"), "platform_unreachable")


class WbiTests(unittest.TestCase):
    def test_mixin_key_matches_published_algorithm(self) -> None:
        self.assertEqual(mixin_key_from_nav(NAV_OK), "ea1db124af3c7062474693fa704f4ff8")
        self.assertIsNone(mixin_key_from_nav({"data": {"wbi_img": {"img_url": "short"}}}))
        self.assertIsNone(mixin_key_from_nav(None))

    def test_signing_is_deterministic_and_strips_reserved_characters(self) -> None:
        signed = wbi_sign({"foo": "one'two", "bar": "514", "zab": 1, "empty": ""}, "ea1db124af3c7062474693fa704f4ff8", 1702204169)
        self.assertEqual(signed["foo"], "onetwo")
        self.assertNotIn("empty", signed)
        self.assertEqual(signed["wts"], "1702204169")
        self.assertEqual(list(signed), sorted(signed))
        again = wbi_sign({"foo": "one'two", "bar": "514", "zab": 1}, "ea1db124af3c7062474693fa704f4ff8", 1702204169)
        self.assertEqual(signed["w_rid"], again["w_rid"])

    def test_key_cache_reuses_value_until_ttl_or_invalidation(self) -> None:
        now = [100.0]
        cache = WbiKeyCache(ttl_seconds=60, clock=lambda: now[0])
        fetches = []

        def fetch():
            fetches.append(now[0])
            return f"key-{len(fetches)}"

        self.assertEqual(cache.get(fetch), "key-1")
        self.assertEqual(cache.get(fetch), "key-1")
        now[0] = 161.0
        self.assertEqual(cache.get(fetch), "key-2")
        cache.invalidate()
        self.assertEqual(cache.get(fetch), "key-3")
        self.assertEqual(len(fetches), 3)

    def test_failed_key_fetch_is_not_cached(self) -> None:
        cache = WbiKeyCache(ttl_seconds=60)
        self.assertIsNone(cache.get(lambda: None))
        self.assertEqual(cache.get(lambda: "fresh"), "fresh")


class AccessGuardTests(unittest.TestCase):
    def test_block_expires_and_success_clears_it(self) -> None:
        now = [1000.0]
        guard = PlatformAccessGuard(cooldown_seconds=300, clock=lambda: now[0])
        guard.check(False)
        guard.record_block(False)
        with self.assertRaises(main.ExtractionFailure) as raised:
            guard.check(False)
        self.assertEqual(raised.exception.reason, "platform_risk_control")
        self.assertTrue(raised.exception.terminal)
        guard.check(True)  # a signed-in session is tracked separately
        now[0] += 301
        guard.check(False)
        guard.record_block(False)
        guard.record_success(False)
        guard.check(False)

    def test_zero_cooldown_disables_the_guard(self) -> None:
        guard = PlatformAccessGuard(cooldown_seconds=0)
        guard.record_block(False)
        guard.check(False)
        self.assertIsNone(guard.blocked_until(False))


class ApiRefusalTests(GuardedTestCase):
    def test_http_412_fails_fast_and_starts_cooldown(self) -> None:
        client = FakeClient([FakeResponse(412, None)])
        with patch.object(main.httpx, "Client", client):
            with self.assertRaises(main.ExtractionFailure) as raised:
                main.api_get_json("https://api.bilibili.com/x/web-interface/view?bvid=BV14jFvzbEvj", "https://www.bilibili.com/")
        self.assertEqual(raised.exception.reason, "platform_risk_control")
        self.assertEqual(raised.exception.status_code, 503)

        follow_up = FakeClient([])
        with patch.object(main.httpx, "Client", follow_up), self.assertRaises(main.ExtractionFailure) as again:
            main.api_get_json("https://api.bilibili.com/x/web-interface/view?bvid=BV14jFvzbEvj", "https://www.bilibili.com/")
        self.assertEqual(again.exception.reason, "platform_risk_control")
        self.assertEqual(follow_up.urls, [], "cooldown must not send another request")

    def test_risk_control_api_code_is_a_refusal_for_unsigned_requests(self) -> None:
        client = FakeClient([FakeResponse(200, {"code": -352, "message": "risk"})])
        with patch.object(main.httpx, "Client", client), self.assertRaises(main.ExtractionFailure) as raised:
            main.api_get_json("https://api.bilibili.com/x/web-interface/view?bvid=BV14jFvzbEvj", "https://www.bilibili.com/")
        self.assertEqual(raised.exception.reason, "platform_risk_control")
        self.assertIsNotNone(main.BILI_ACCESS_GUARD.blocked_until(False))

    def test_signed_request_rejection_refreshes_key_and_retries_once(self) -> None:
        client = FakeClient(
            [
                FakeResponse(200, NAV_OK),
                FakeResponse(200, {"code": -352, "message": "bad signature"}),
                FakeResponse(200, NAV_OK),
                FakeResponse(200, {"code": 0, "data": {"subtitle": {"subtitles": []}}}),
            ]
        )
        with patch.object(main.httpx, "Client", client):
            data = main.wbi_get_json(
                "https://api.bilibili.com/x/player/wbi/v2",
                {"aid": 42, "bvid": "BV14jFvzbEvj", "cid": 7},
                "https://www.bilibili.com/video/BV14jFvzbEvj",
            )
        self.assertEqual(data["code"], 0)
        self.assertEqual(sum("/nav" in url for url in client.urls), 2)
        self.assertTrue(all("w_rid=" in url for url in client.urls if "/player/" in url))
        self.assertIsNone(main.BILI_ACCESS_GUARD.blocked_until(False))

    def test_wbi_key_is_fetched_once_for_consecutive_requests(self) -> None:
        client = FakeClient(
            [
                FakeResponse(200, NAV_OK),
                FakeResponse(200, {"code": 0, "data": {}}),
                FakeResponse(200, {"code": 0, "data": {}}),
            ]
        )
        with patch.object(main.httpx, "Client", client):
            for _ in range(2):
                main.wbi_get_json("https://api.bilibili.com/x/player/wbi/v2", {"cid": 7}, "https://www.bilibili.com/")
        self.assertEqual(sum("/nav" in url for url in client.urls), 1)

    def test_success_clears_an_expired_block(self) -> None:
        main.BILI_ACCESS_GUARD.record_block(False)
        main.BILI_ACCESS_GUARD.reset()
        client = FakeClient([FakeResponse(200, VIEW_OK)])
        with patch.object(main.httpx, "Client", client):
            data = main.api_get_json("https://api.bilibili.com/x/web-interface/view?bvid=BV14jFvzbEvj", "https://www.bilibili.com/")
        self.assertEqual(data["data"]["aid"], 42)


class ViewContextTests(GuardedTestCase):
    def test_av_link_is_resolved_through_the_view_api(self) -> None:
        payload = {
            "code": 0,
            "data": {
                "bvid": "BV14jFvzbEvj",
                "aid": 170001,
                "cid": 1,
                "title": "multi",
                "pages": [{"cid": 1, "part": "one"}, {"cid": 2, "part": "two"}],
            },
        }
        with patch.object(main, "api_get_json", return_value=payload) as api:
            bvid, canonical, _data, selected, cid = main.bili_view_context(
                "https://www.bilibili.com/video/av170001?p=2"
            )
        self.assertIn("aid=170001", api.call_args.args[0])
        self.assertEqual(bvid, "BV14jFvzbEvj")
        self.assertEqual(canonical, "https://www.bilibili.com/video/BV14jFvzbEvj?p=2")
        self.assertEqual(selected["part"], "two")
        self.assertEqual(cid, 2)

    def test_link_without_bv_or_av_is_rejected_before_any_request(self) -> None:
        with patch.object(main, "api_get_json") as api, self.assertRaises(main.ExtractionFailure) as raised:
            main.bili_view_context("https://www.bilibili.com/bangumi/play/ep1")
        self.assertEqual(raised.exception.reason, "invalid_bvid")
        api.assert_not_called()


class OfficialSubtitleOrderTests(GuardedTestCase):
    def request(self):
        return main.ExtractRequest(input="https://www.bilibili.com/video/BV14jFvzbEvj")

    def test_api_is_tried_first_and_ytdlp_is_skipped_on_success(self) -> None:
        source = main.ExtractionSource(
            title="t",
            video_id="BV14jFvzbEvj",
            webpage_url="https://www.bilibili.com/video/BV14jFvzbEvj",
            tracks=[main.SubtitleTrack("official", "zh-CN", "json", "https://aisubtitle.hdslb.com/x.json")],
        )
        body = '{"body": [{"from": 0, "to": 1.5, "content": "你好"}]}'
        with patch.object(main, "bili_api_source", return_value=source), patch.object(
            main, "extract_info"
        ) as ytdlp, patch.object(main, "fetch_subtitle", return_value=body):
            entries, meta = main.official_subtitle(self.request(), allow_cookie=False, source_label="official_no_cookie")
        ytdlp.assert_not_called()
        self.assertEqual(entries[0].text, "你好")
        self.assertEqual(meta["attempts"], ["bilibili_api"])

    def test_platform_refusal_is_final_and_skips_ytdlp(self) -> None:
        refusal = main.platform_block_failure()
        with patch.object(main, "bili_api_source", side_effect=refusal), patch.object(
            main, "extract_info"
        ) as ytdlp, self.assertRaises(main.ExtractionFailure) as raised:
            main.official_subtitle(self.request(), allow_cookie=False, source_label="official_no_cookie")
        ytdlp.assert_not_called()
        self.assertEqual(raised.exception.reason, "platform_risk_control")

    def test_transient_api_error_falls_back_to_ytdlp(self) -> None:
        transient = main.ExtractionFailure(502, "timeout", "api_request_failed")
        info = {"id": "BV14jFvzbEvj", "title": "t", "subtitles": {}, "automatic_captions": {}}
        with patch.object(main, "bili_api_source", side_effect=transient), patch.object(
            main, "extract_info", return_value=info
        ) as ytdlp, self.assertRaises(main.ExtractionFailure) as raised:
            main.official_subtitle(self.request(), allow_cookie=False, source_label="official_no_cookie")
        ytdlp.assert_called_once()
        self.assertEqual(raised.exception.reason, "no_official_subtitle")
        self.assertTrue(raised.exception.can_try_asr)

    def test_ytdlp_failure_reports_the_more_precise_api_error(self) -> None:
        transient = main.ExtractionFailure(502, "timeout", "api_request_failed")
        ytdlp_error = main.ExtractionFailure(502, "412", "ytdlp_failed")
        with patch.object(main, "bili_api_source", side_effect=transient), patch.object(
            main, "extract_info", side_effect=ytdlp_error
        ), self.assertRaises(main.ExtractionFailure) as raised:
            main.official_subtitle(self.request(), allow_cookie=False, source_label="official_no_cookie")
        self.assertEqual(raised.exception.reason, "api_request_failed")

    def test_saved_login_goes_first_and_skips_anonymous_requests(self) -> None:
        entries = [main.SubtitleEntry(0, 1, "ok")]
        calls = []

        def official(req, allow_cookie, source_label):
            calls.append(allow_cookie)
            return entries, {"source": source_label, "platform": "bilibili"}

        with patch.object(main, "cookie_allowed", return_value=True), patch.object(
            main, "official_subtitle", side_effect=official
        ):
            result, meta = main.extract_subtitle_uncached(
                main.ExtractRequest(input="https://www.bilibili.com/video/BV14jFvzbEvj")
            )
        self.assertEqual(calls, [True])
        self.assertEqual(result, entries)
        self.assertEqual(meta["source"], "official_with_cookie")

    def test_anonymous_refusal_without_login_state_stops_immediately(self) -> None:
        refusal = main.platform_block_failure()
        with patch.object(main, "cookie_allowed", return_value=False), patch.object(
            main, "official_subtitle", side_effect=refusal
        ), patch.object(main, "asr_subtitle") as asr, self.assertRaises(main.HTTPException) as raised:
            main.extract_subtitle_uncached(main.ExtractRequest(input="https://www.bilibili.com/video/BV14jFvzbEvj"))
        asr.assert_not_called()
        self.assertEqual(raised.exception.detail["code"], "platform_blocked")
        self.assertFalse(raised.exception.detail["retryable"])


class PlatformStatusTests(GuardedTestCase):
    def test_status_follows_the_mode_requests_actually_use(self) -> None:
        with patch.object(main, "cookie_allowed", return_value=False):
            self.assertEqual(main.bilibili_platform_status()["state"], "ok")
            main.BILI_ACCESS_GUARD.record_block(False)
            limited = main.bilibili_platform_status()
            self.assertEqual(limited["state"], "limited")
            self.assertFalse(limited["signed_in"])
            self.assertGreater(limited["retry_after_seconds"], 0)
        with patch.object(main, "cookie_allowed", return_value=True):
            # Anonymous refusals do not matter once the owner's login is used.
            self.assertEqual(main.bilibili_platform_status(), {"state": "ok", "signed_in": True})
            main.BILI_ACCESS_GUARD.record_block(True)
            self.assertEqual(main.bilibili_platform_status()["state"], "limited")


if __name__ == "__main__":
    unittest.main()
