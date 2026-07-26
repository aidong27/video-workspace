import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from app import douyin


class DouyinUrlTests(unittest.TestCase):
    def test_chromium_probe_tolerates_unreadable_runtime_directory(self) -> None:
        root = Mock()
        root.glob.side_effect = PermissionError("unreadable")
        with patch.dict(douyin.os.environ, {"DOUYIN_CHROMIUM_EXECUTABLE": ""}), patch.object(
            douyin, "_playwright_root", return_value=root
        ):
            self.assertIsNone(douyin._chromium_executable())

    def test_adapter_status_tolerates_unreadable_cookie_file(self) -> None:
        cookie_path = Mock()
        cookie_path.stat.side_effect = PermissionError("unreadable")
        with patch.object(douyin, "_cookie_state_path", return_value=cookie_path), patch.object(
            douyin, "_dependency_available", return_value=False
        ), patch.object(douyin, "_chromium_executable", return_value=None):
            status = douyin.adapter_status()
        self.assertFalse(status["cookie_cached"])

    def test_extracts_url_from_share_text(self) -> None:
        text = "复制此链接 https://www.douyin.com/video/6961737553342991651 继续打开"
        self.assertEqual(
            douyin.normalize_douyin_input(text),
            "https://www.douyin.com/video/6961737553342991651",
        )

    def test_modal_id_is_canonicalized(self) -> None:
        value = "https://www.douyin.com/discover?modal_id=6961737553342991651"
        self.assertEqual(
            douyin.normalize_douyin_input(value),
            "https://www.douyin.com/video/6961737553342991651",
        )

    def test_lookalike_host_is_rejected(self) -> None:
        self.assertFalse(douyin.is_douyin_url("https://douyin.com.example.com/video/6961737553342991651"))

    def test_caption_tracks_support_both_api_shapes(self) -> None:
        detail = {
            "interaction_stickers": [
                {
                    "auto_video_caption_info": {
                        "auto_captions": [
                            {
                                "language": "zh",
                                "url": {"url_list": ["https://example.invalid/caption.json"]},
                            }
                        ]
                    }
                }
            ],
            "video": {
                "cla_info": {
                    "caption_infos": [
                        {
                            "lang": "en",
                            "Format": "webvtt",
                            "url": "https://example.invalid/caption.vtt",
                        }
                    ]
                }
            },
        }
        tracks = douyin._caption_tracks(detail)
        self.assertEqual([(track.language, track.ext) for track in tracks], [("zh", "json"), ("en", "vtt")])

    def test_muxed_play_address_is_preferred_over_video_only_bitrates(self) -> None:
        detail = {
            "video": {
                "play_addr": {"url_list": ["https://cdn.invalid/muxed"]},
                "bit_rate": [
                    {"bit_rate": 900000, "play_addr": {"url_list": ["https://cdn.invalid/high"]}},
                    {"bit_rate": 300000, "play_addr": {"url_list": ["https://cdn.invalid/low"]}},
                ]
            }
        }
        self.assertEqual(douyin._media_urls(detail)[0], "https://cdn.invalid/muxed")

    def test_original_sound_audio_is_preferred(self) -> None:
        detail = {
            "music": {
                "is_original_sound": True,
                "play_url": {"url_list": ["https://cdn.invalid/original.mp3"]},
            },
            "video": {"play_addr": {"url_list": ["https://cdn.invalid/video.mp4"]}},
        }
        self.assertEqual(douyin._media_urls(detail)[0], "https://cdn.invalid/original.mp3")

    def test_redirect_target_is_revalidated_and_loop_is_bounded(self) -> None:
        class Response:
            status_code = 302

            def __init__(self, location: str) -> None:
                self.headers = {"location": location}

        class Client:
            def __init__(self, locations) -> None:
                self.locations = list(locations)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def get(self, _url):
                return Response(self.locations.pop(0))

        with patch.object(
            douyin.httpx,
            "Client",
            return_value=Client(["https://example.com/video/6961737553342991651"]),
        ), self.assertRaises(douyin.DouyinAdapterError) as untrusted:
            douyin._resolve_douyin_redirect("https://v.douyin.com/test")
        self.assertEqual(untrusted.exception.reason, "short_link_untrusted")

        with patch.object(
            douyin.httpx,
            "Client",
            return_value=Client(["https://v.douyin.com/loop"]),
        ), self.assertRaises(douyin.DouyinAdapterError) as loop:
            douyin._resolve_douyin_redirect("https://v.douyin.com/loop")
        self.assertEqual(loop.exception.reason, "short_link_loop")

    def test_corrupt_cookie_state_is_rebuilt(self) -> None:
        cookies = {f"cookie-{index}": f"value-{index}" for index in range(6)}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cookies.json"
            path.write_text("{broken", encoding="utf-8")

            def refresh(_url):
                douyin._write_cached_cookies(cookies)
                return cookies

            with patch.object(douyin, "_cookie_state_path", return_value=path), patch.object(
                douyin, "refresh_douyin_cookies", side_effect=refresh
            ) as rebuilt:
                result = douyin.douyin_cookies("https://www.douyin.com/video/6961737553342991651")

            self.assertEqual(result, cookies)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["cookies"], cookies)
            rebuilt.assert_called_once()

    def test_browser_lock_is_released_when_cookie_refresh_fails(self) -> None:
        class FakeLock:
            def __init__(self) -> None:
                self.releases = 0

            def acquire(self, **_kwargs) -> bool:
                return True

            def release(self) -> None:
                self.releases += 1

        lock = FakeLock()
        with patch.object(douyin, "DOUYIN_COOKIE_LOCK", lock), patch.object(
            douyin, "_read_cached_cookies", return_value=None
        ), patch.object(
            douyin,
            "refresh_douyin_cookies",
            side_effect=douyin.DouyinAdapterError(502, "failed", "douyin_cookie_refresh_failed"),
        ), self.assertRaises(douyin.DouyinAdapterError):
            douyin.douyin_cookies("https://www.douyin.com/video/6961737553342991651")

        self.assertEqual(lock.releases, 1)

    def test_playwright_error_closes_page_context_and_browser(self) -> None:
        class Resource:
            def __init__(self) -> None:
                self.closed = 0

            def close(self) -> None:
                self.closed += 1

        page = Resource()
        context = Resource()
        browser = Resource()

        def add_init_script(_script):
            return None

        def goto(*_args, **_kwargs):
            raise RuntimeError("navigation failed")

        page.add_init_script = add_init_script
        page.goto = goto
        page.wait_for_timeout = lambda _value: None
        context.new_page = lambda: page
        context.cookies = lambda: []
        browser.new_context = lambda **_kwargs: context
        chromium = type("Chromium", (), {"launch": lambda _self, **_kwargs: browser})()
        playwright = type("Playwright", (), {"chromium": chromium})()

        class PlaywrightContext:
            def __enter__(self):
                return playwright

            def __exit__(self, *_args):
                return None

        sync_module = ModuleType("playwright.sync_api")
        sync_module.sync_playwright = lambda: PlaywrightContext()
        parent_module = ModuleType("playwright")
        parent_module.__path__ = []
        parent_module.sync_api = sync_module
        with patch.dict(
            sys.modules,
            {"playwright": parent_module, "playwright.sync_api": sync_module},
        ), patch.object(douyin, "_chromium_executable", return_value=Path("/fake/chrome")), self.assertRaises(
            douyin.DouyinAdapterError
        ):
            douyin.refresh_douyin_cookies("https://www.douyin.com/video/6961737553342991651")

        self.assertEqual(page.closed, 1)
        self.assertEqual(context.closed, 1)
        self.assertEqual(browser.closed, 1)

    def test_expired_media_urls_refresh_detail_once(self) -> None:
        old = douyin.DouyinVideo(
            video_id="6961737553342991651",
            title="old",
            author=None,
            webpage_url="https://www.douyin.com/video/6961737553342991651",
            duration=3,
            media_urls=["https://cdn.invalid/expired"],
            tracks=[],
            cookies={},
        )
        fresh = douyin.DouyinVideo(
            video_id=old.video_id,
            title="fresh",
            author=None,
            webpage_url=old.webpage_url,
            duration=3,
            media_urls=["https://cdn.invalid/fresh"],
            tracks=[],
            cookies={},
        )

        class Response:
            headers = {"content-length": "1024", "content-type": "video/mp4"}

            def __init__(self, url: str) -> None:
                self.url = url

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def raise_for_status(self):
                if self.url.endswith("expired"):
                    raise RuntimeError("expired URL")

            def iter_bytes(self, _size):
                yield b"x" * 1024

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def stream(self, _method, url):
                return Response(url)

        probe = type(
            "Probe",
            (),
            {
                "returncode": 0,
                "stdout": '{"streams":[{"codec_type":"video"},{"codec_type":"audio"}],"format":{"duration":"3"}}',
                "stderr": "",
            },
        )()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            douyin.httpx, "Client", return_value=Client()
        ), patch.object(douyin, "get_douyin_video", return_value=fresh) as refresh, patch.object(
            douyin.shutil, "which", return_value="/usr/bin/ffprobe"
        ), patch.object(douyin, "run_managed_process", return_value=probe):
            path, metadata = douyin.download_douyin_media(old, Path(directory))

        self.assertTrue(path.name.endswith(".mp4"))
        self.assertTrue(metadata["media_urls_refreshed"])
        refresh.assert_called_once_with(old.webpage_url, force_refresh=True)

    def test_refreshed_media_detail_rechecks_duration_before_download(self) -> None:
        old = douyin.DouyinVideo(
            video_id="6961737553342991651",
            title="old",
            author=None,
            webpage_url="https://www.douyin.com/video/6961737553342991651",
            duration=3,
            media_urls=["https://cdn.invalid/expired"],
            tracks=[],
            cookies={},
        )
        fresh = douyin.DouyinVideo(
            video_id=old.video_id,
            title="fresh",
            author=None,
            webpage_url=old.webpage_url,
            duration=120,
            media_urls=["https://cdn.invalid/fresh"],
            tracks=[],
            cookies={},
        )

        class Response:
            headers = {"content-length": "1024", "content-type": "video/mp4"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def raise_for_status(self):
                raise RuntimeError("expired URL")

            def iter_bytes(self, _size):
                return iter(())

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def stream(self, _method, _url):
                return Response()

        with tempfile.TemporaryDirectory() as directory, patch.object(
            douyin.httpx, "Client", return_value=Client()
        ), patch.object(
            douyin,
            "get_douyin_video",
            return_value=fresh,
        ) as refresh, self.assertRaises(douyin.DouyinAdapterError) as raised:
            douyin.download_douyin_media(
                old,
                Path(directory),
                max_duration_seconds=30,
            )

        self.assertEqual(raised.exception.reason, "media_duration_too_long")
        refresh.assert_called_once_with(old.webpage_url, force_refresh=True)


if __name__ == "__main__":
    unittest.main()
