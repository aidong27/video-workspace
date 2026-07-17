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


if __name__ == "__main__":
    unittest.main()
