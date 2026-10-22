"""公众号列表按卡片位置滚动，避免固定两格滚轮停在同一屏。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import wechat_visual_rpa as rpa


class ProfileScrollTests(unittest.TestCase):
    def test_bottom_card_requests_more_than_two_notches(self) -> None:
        self.assertGreaterEqual(rpa.profile_scroll_notches(940), 4)
        self.assertLessEqual(rpa.profile_scroll_notches(940), 10)

    def test_card_already_near_top_uses_a_short_scroll(self) -> None:
        self.assertEqual(rpa.profile_scroll_notches(250), 3)

    def test_collection_scrolls_using_the_bottom_card(self) -> None:
        page = {
            "time_labels": [{"text": "昨天", "center_y_1000": 120}],
            "articles": [
                {
                    "title": "仍在屏幕底部的文章",
                    "center_y_1000": 940,
                    "center_x_1000": 400,
                    "screen_point": (400, 900),
                    "time_group": "昨天",
                    "list_read_count": 10,
                    "list_like_count": 1,
                }
            ],
        }
        # 下一屏出现更早日期后应停止，因此只会滚动一次。
        older = {
            "time_labels": [{"text": "星期三", "center_y_1000": 200}],
            "articles": [],
        }
        window = rpa.WindowInfo(0, "公众号", "test", rpa.Rect(0, 0, 1000, 1400))
        with tempfile.TemporaryDirectory() as directory, patch.object(rpa, "search_and_open_profile", return_value=(window, "南京发布")), patch.object(
            rpa, "analyze_profile_window", side_effect=[page, older]
        ), patch.object(rpa, "collect_open_article", return_value={"url": "https://mp.weixin.qq.com/s/x", "title": "仍在屏幕底部的文章", "status": "inserted"}), patch.object(
            rpa, "activate_window"
        ), patch.object(rpa, "click"), patch.object(rpa, "close_article_after_attempt"), patch.object(rpa, "scroll_window_down") as scroll, patch.object(
            rpa, "scroll_window_up"
        ), patch.object(rpa, "log_event"), patch.object(rpa.time, "sleep"):
            summary = rpa.collect_profile_account(
                None, "南京发布", Path(directory), 20, None, None, scan_range="yesterday"
            )

        self.assertEqual(summary["stop_reason"], "已离开「昨天」")
        self.assertEqual(scroll.call_count, 1)
        self.assertGreaterEqual(scroll.call_args[0][1], 4)

    def test_large_vertical_gap_is_filled_from_the_other_feed(self) -> None:
        primary = {
            "recognition_method": "uia-profile-feed",
            "time_labels": [{"text": "昨天", "center_y_1000": 80}],
            "articles": [
                {"title": "慧眼将亮相南京", "center_y_1000": 84, "center_x_1000": 373, "screen_point": (554, 128)},
                {"title": "江苏省政府最新通知", "center_y_1000": 944, "center_x_1000": 382, "screen_point": (568, 1442)},
            ],
        }
        extra = {
            "time_labels": [{"text": "昨天", "center_y_1000": 370}],
            "articles": [
                {"title": "慧眼将亮相南京", "center_y_1000": 90, "center_x_1000": 370},
                {"title": "漏掉的第一篇", "center_y_1000": 372, "center_x_1000": 400},
                {"title": "漏掉的第二篇", "center_y_1000": 660, "center_x_1000": 400},
            ],
        }
        self.assertTrue(rpa.profile_feed_has_recognition_gap(primary))
        merged = rpa.merge_unrecognized_profile_cards(primary, extra, rpa.Rect(0, 0, 1485, 1528))
        titles = [article["title"] for article in merged["articles"]]
        self.assertEqual(titles, ["慧眼将亮相南京", "江苏省政府最新通知", "漏掉的第一篇", "漏掉的第二篇"])
        self.assertIn("ocr-gap", merged["recognition_method"])


if __name__ == "__main__":
    unittest.main()
