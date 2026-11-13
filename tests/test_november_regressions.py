"""十一月初批量日志暴露的失败：标题占位名、菜单左移、残留标签和操作节奏。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

import wechat_visual_rpa as rpa
from browser_navigation import Checkpoint, Navigator, Page, title_finished_loading


SEARCH = Page(1, "[1]:搜一搜", "search", "搜一搜")
PROFILE = Page(1, "[2]:甲", "profile", "甲", "甲")
LOADING = Page(1, "[3]:微信公众平台", "article", "微信公众平台", "甲")
ARTICLE = Page(1, "[3]:文章", "article", "文章", "甲")
CUSTOM_TABS = (((1,), "<custom-tab>"), ((2,), "<custom-tab>"), ((3,), "<custom-tab>"))


class ArticleTitleLoadingTests(unittest.TestCase):
    def test_placeholder_title_waits_for_real_title(self):
        """占位名连续出现多次也不算标题不匹配，换成真实标题后正常返回。"""
        loaded = Page(1, "[3]:真实标题", "article", "真实标题", "甲")
        with patch.object(rpa, "observe_browser_page", side_effect=[LOADING] * 5 + [loaded]), \
                patch.object(rpa.time, "sleep"), patch.object(rpa, "log_event") as log:
            self.assertEqual(rpa.wait_for_article_page(SimpleNamespace(hwnd=1), "甲", "真实标题"), loaded)
        events = [call.args[0] for call in log.call_args_list]
        self.assertEqual(events.count("article_page_title_loading"), 1)

    def test_placeholder_until_timeout_is_not_card_mismatch(self):
        clock = iter(range(100))
        with patch.object(rpa, "observe_browser_page", return_value=LOADING), \
                patch.object(rpa.time, "sleep"), patch.object(rpa, "log_event"), \
                patch.object(rpa.time, "monotonic", side_effect=lambda: next(clock)):
            with self.assertRaisesRegex(RuntimeError, "未确认目标标题"):
                rpa.wait_for_article_page(SimpleNamespace(hwnd=1), "甲", "真实标题", timeout=8)


class PlaceholderNavigationTests(unittest.TestCase):
    def setUp(self):
        self.before = Checkpoint(PROFILE, (PROFILE, SEARCH), "", CUSTOM_TABS[:2], (2,))
        self.tabs, self.active, self.current = CUSTOM_TABS, (), ARTICLE
        self.tab_pages = {(2,): PROFILE, (3,): ARTICLE}
        self.reads, self.pauses, self.forgotten = 0, 0, []

    def navigator(self, loading_reads=0):
        def observe():
            self.reads += 1
            return LOADING if self.reads <= loading_reads else self.current

        def close():
            self.tabs, self.active, self.current = CUSTOM_TABS[:2], (), SEARCH

        def select(identity):
            self.active, self.current = identity, self.tab_pages[identity]
            return True

        def pause():
            self.pauses += 1

        return Navigator(observe, lambda: self.fail("不得遍历"), close, lambda: self.fail("不得后退"),
                         on_closed=self.forgotten.append, signature=lambda: self.tabs,
                         selected=lambda: self.active, select_tab=select,
                         custom_tabs=lambda: True, pause=pause)

    def test_finished_loading_requires_same_document_and_account(self):
        self.assertTrue(title_finished_loading(LOADING, ARTICLE))
        self.assertFalse(title_finished_loading(ARTICLE, LOADING))
        self.assertFalse(title_finished_loading(LOADING, Page(1, "[9]:文章", "article", "文章", "甲")))
        self.assertFalse(title_finished_loading(LOADING, Page(1, "[3]:文章", "article", "文章", "乙")))

    def test_restore_waits_for_real_title_before_closing(self):
        """清理时先看到占位名、选中后才变成真实标题，曾被当成身份不一致而中止公众号。"""
        nav = self.navigator(loading_reads=2)
        self.assertEqual(nav.restore(self.before), "new_tab")
        self.assertEqual(self.pauses, 2)
        self.assertEqual(self.forgotten, [ARTICLE])
        self.assertEqual(self.current, PROFILE)

    def test_selection_may_finish_loading_title(self):
        self.assertTrue(self.navigator().confirm_added(self.before, LOADING))

    def test_selection_switching_document_still_aborts(self):
        self.tab_pages[(3,)] = Page(1, "[9]:别的文章", "article", "别的文章", "甲")
        with self.assertRaisesRegex(RuntimeError, "页面身份不一致"):
            self.navigator().confirm_added(self.before, LOADING)


def ocr_row(text: str, left: float, center_y: float, width: float = 90) -> dict:
    return {"text": text, "normalized": text, "confidence": 0.99,
            "left": left, "right": left + width, "top": center_y - 9, "bottom": center_y + 9,
            "center_x": left + width / 2, "center_y": center_y}


class CopyLinkMenuTests(unittest.TestCase):
    def setUp(self):
        self.screenshot = Image.new("RGB", (1114, 1032), "white")

    def locate(self, rows):
        with patch.object(rpa.PROFILE_OCR, "_rows", return_value=rows):
            return rpa.PROFILE_OCR.locate_copy_link_action(self.screenshot)

    def test_menu_moved_to_left_by_many_tabs_is_found(self):
        """十月三十日标签过多时整块菜单移到左侧，曾因横向位置限制全部判为未找到。"""
        result = self.locate([ocr_row("刷新", 218, 66), ocr_row("复制链接", 219, 91),
                              ocr_row("调整文字大小", 218, 116, 120)])
        self.assertTrue(result["found"], result)
        self.assertEqual(result["center_x_1000"], round((219 + 45) * 1000 / 1114))

    def test_normal_menu_is_found(self):
        result = self.locate([ocr_row("刷新", 520, 66), ocr_row("复制链接", 521, 91)])
        self.assertTrue(result["found"], result)

    def test_body_text_without_menu_column_is_rejected(self):
        result = self.locate([ocr_row("复制链接", 300, 200, 200), ocr_row("刷新", 600, 66)])
        self.assertFalse(result["found"])
        self.assertIn("同列", result["reason"])


class LiveMenuButtonRetryTests(unittest.TestCase):
    def test_stale_menu_cache_retries_live_ellipsis_in_same_attempt(self):
        """缓存三点在标签变化后打不开菜单时，本次改点实时识别到的三点，并记住新位置。"""
        rect = rpa.Rect(left=100, top=200, right=1100, bottom=1400)
        screenshot = Image.new("RGB", (1000, 1200), "white")
        live = {"found": True, "center_x_1000": 250, "center_y_1000": 20, "confidence": 0.8,
                "method": "opencv-browser-ellipsis"}
        validated = {"found": True, "center_x_1000": 600, "center_y_1000": 20, "confidence": 0.9,
                     "method": "cached-menu-button-verified-position", "live_detection": live}
        copy_link = {"found": True, "center_x_1000": 224, "center_y_1000": 88,
                     "method": "rapidocr-browser-copy-link"}
        with patch.object(rpa, "set_clipboard_text"), patch.object(rpa, "press_escape"), \
                patch.object(rpa, "capture_window", return_value=screenshot), \
                patch.object(rpa, "read_clipboard_text", return_value="https://mp.weixin.qq.com/s/x"), \
                patch.object(rpa, "click") as click, patch.object(rpa.time, "sleep"), \
                patch.object(rpa, "log_event"), \
                patch.object(rpa, "load_menu_button_position_cache", return_value={"center_x_1000": 600}), \
                patch.object(rpa, "validate_cached_menu_button_action", return_value=validated), \
                patch.object(rpa, "save_menu_button_position_cache") as save_menu, \
                patch.object(rpa, "clear_menu_button_position_cache"), \
                patch.object(rpa, "load_copy_link_position_cache", return_value=None), \
                patch.object(rpa, "save_copy_link_position_cache"), \
                patch.object(rpa.PROFILE_OCR, "locate_copy_link_action",
                             side_effect=[{"found": False, "reason": "未识别"}, copy_link]):
            url = rpa.copy_article_url(1, rect, client=None, allow_vl=False)
        self.assertEqual(url, "https://mp.weixin.qq.com/s/x")
        self.assertEqual(click.call_count, 3)
        self.assertEqual(save_menu.call_args.args[0]["center_x_1000"], 250)


class FakeBrowser:
    """按标签 id 保存页面；关闭生效时当前标签从列表消失。"""

    def __init__(self, pages: dict, close_works: bool = True):
        self.pages, self.order = dict(pages), list(pages)
        self.active, self.close_works = self.order[0], close_works
        self.selected, self.closed = [], []

    def add(self, identity, page):
        self.pages[identity] = page
        self.order.append(identity)

    def observe(self):
        return self.pages[self.active]

    def signature(self):
        return tuple((identity, "<custom-tab>") for identity in self.order)

    def select_tab(self, identity, allow_icon_tab=False):
        self.selected.append((identity, allow_icon_tab))
        self.active = identity
        return True

    def close_tab(self):
        self.closed.append(self.active)
        if self.close_works:
            self.order.remove(self.active)
            self.active = self.order[0]

    def pause(self):
        pass


class LeftoverTabCleanupTests(unittest.TestCase):
    def setUp(self):
        self.window = rpa.WindowInfo(1, "微信", "Chrome_WidgetWin_0", rpa.Rect(0, 0, 1000, 800))
        self.user_article = Page(1, "[2]:用户自己的文章", "article", "用户自己的文章", "乙")

    def run_cleanup(self, browser, add_leftovers):
        with patch.dict(rpa._BATCH_BASELINE_TABS, clear=True), \
                patch.object(rpa, "browser_session", return_value="session"), \
                patch.object(rpa, "browser_navigator", return_value=browser), \
                patch.object(rpa.TAB_OWNERSHIP, "forget") as forget, \
                patch.object(rpa, "log_event") as log:
            self.assertEqual(rpa.close_batch_leftover_tabs(self.window, "甲"), 0)
            add_leftovers()
            closed = rpa.close_batch_leftover_tabs(self.window, "乙")
        return closed, forget, log

    def test_leftovers_close_back_to_batch_baseline(self):
        """批次开始前已有的标签保留，之后残留的主页和文章从最右侧开始关闭。"""
        browser = FakeBrowser({(1,): SEARCH, (2,): self.user_article})

        def add_leftovers():
            browser.add((3,), PROFILE)
            browser.add((4,), ARTICLE)

        closed, forget, _log = self.run_cleanup(browser, add_leftovers)
        self.assertEqual(closed, 2)
        self.assertEqual(browser.closed, [(4,), (3,)])
        self.assertEqual(browser.order, [(1,), (2,)])
        self.assertEqual(forget.call_count, 2)
        self.assertTrue(all(allow_icon for _identity, allow_icon in browser.selected))

    def test_unrecognized_leftover_is_kept(self):
        browser = FakeBrowser({(1,): SEARCH})
        closed, forget, log = self.run_cleanup(
            browser, lambda: browser.add((2,), Page(1, "[5]:视频号", "unknown", "视频号")))
        self.assertEqual(closed, 0)
        self.assertEqual(browser.closed, [])
        forget.assert_not_called()
        self.assertIn("不是公众号", log.call_args.kwargs["stopped_reason"])

    def test_close_without_effect_stops_without_closing_again(self):
        browser = FakeBrowser({(1,): SEARCH}, close_works=False)

        def add_leftovers():
            browser.add((2,), PROFILE)
            browser.add((3,), ARTICLE)

        closed, forget, log = self.run_cleanup(browser, add_leftovers)
        self.assertEqual(closed, 0)
        self.assertEqual(browser.closed, [(3,)])
        forget.assert_not_called()
        self.assertIn("不一致", log.call_args.kwargs["stopped_reason"])

    def test_icon_tab_is_clicked_only_when_allowed(self):
        """标签被压成图标时，只有残留清理允许点击图标中心。"""
        evidence = {
            "ok": True, "hwnd": 1, "tab_probe_mode": "custom-unverified", "tabs": [],
            "custom_tabs": [{"id": [1], "name": "", "rect": [0, 0, 200, 36]},
                            {"id": [2], "name": "", "rect": [200, 0, 240, 36]}],
            "documents": [{"id": [7], "name": "文章", "rows": []}],
        }
        with patch.object(rpa, "browser_session", return_value=""), \
                patch.object(rpa, "probe_page", return_value=evidence), \
                patch.object(rpa, "activate_window"), patch.object(rpa, "click") as click, \
                patch.object(rpa.time, "sleep"), patch.object(rpa, "log_event"):
            navigator = rpa.browser_navigator(self.window, "")
            self.assertFalse(navigator.select_tab((2,)))
            click.assert_not_called()
            self.assertTrue(navigator.select_tab((2,), allow_icon_tab=True))
        click.assert_called_once_with(220, 18)


class PacingTests(unittest.TestCase):
    def test_seconds_range_parsing(self):
        cases = {"2-4": (2.0, 4.0), "3": (3.0, 3.0), " 0.5-1 ": (0.5, 1.0),
                 "": (9.0, 9.5), "abc": (9.0, 9.5), "5-2": (9.0, 9.5), "-1": (9.0, 9.5)}
        for raw, expected in cases.items():
            with patch.dict(os.environ, {"RPA_TEST_RANGE": raw}):
                self.assertEqual(rpa._env_seconds_range("RPA_TEST_RANGE", (9.0, 9.5)), expected, raw)

    def test_click_keeps_minimum_gap_and_holds_button(self):
        with patch.object(rpa, "user32") as user32, patch.object(rpa.time, "sleep") as sleep, \
                patch.object(rpa.time, "monotonic", return_value=10.0), \
                patch.object(rpa, "_LAST_CLICK_AT", 9.7), \
                patch.object(rpa, "CLICK_INTERVAL_SECONDS", (1.0, 1.0)), \
                patch.object(rpa.random, "uniform", side_effect=lambda low, high: low):
            rpa.click(10, 20)
            self.assertEqual(rpa._LAST_CLICK_AT, 10.0)
        self.assertEqual([round(call.args[0], 2) for call in sleep.call_args_list], [0.7, 0.06, 0.04])
        user32.SetCursorPos.assert_called_once_with(10, 20)
        self.assertEqual([call.args[0] for call in user32.mouse_event.call_args_list], [0x0002, 0x0004])

    def test_pause_between_articles_but_not_before_first(self):
        window = rpa.WindowInfo(0, "微信", "Chrome_WidgetWin_0", rpa.Rect(0, 0, 100, 100))
        card = {"center_x_1000": 500, "screen_point": (10, 10), "list_read_count": 1, "list_like_count": 1}
        first_page = {"time_labels": [{"text": "今天", "center_y_1000": 100}],
                      "articles": [dict(card, title="第一篇文章", center_y_1000=200),
                                   dict(card, title="第二篇文章", center_y_1000=400)]}
        older_page = {"time_labels": [{"text": "昨天", "center_y_1000": 100}], "articles": []}

        def collect(*args, **kwargs):
            return {"url": "https://mp.weixin.qq.com/s/" + kwargs["expected_title"],
                    "title": kwargs["expected_title"], "account_name": "甲", "status": "inserted"}

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(rpa, "search_and_open_profile", return_value=(window, "甲")), \
                patch.object(rpa, "analyze_profile_window", side_effect=[first_page, *([older_page] * 12)]), \
                patch.object(rpa, "collect_open_article", side_effect=collect), \
                patch.object(rpa, "activate_window"), patch.object(rpa, "click"), \
                patch.object(rpa, "close_article_after_attempt"), patch.object(rpa, "log_event"), \
                patch.object(rpa.time, "sleep"), patch.object(rpa, "human_pause") as pause:
            summary = rpa.collect_profile_account(None, "甲", Path(directory), max_articles=20,
                                                  export_jsonl=None, export_csv=None,
                                                  write_mongo=False, scan_range="today")
        self.assertEqual(len(summary["collected"]), 2)
        pause.assert_called_once_with(rpa.ARTICLE_PAUSE_SECONDS)


class CachedArticleTitleRenameTests(unittest.TestCase):
    def _run_collect_with_cache(self, cached_title: str, live_title: str, expected_title: str):
        cached = {
            "title": cached_title,
            "account_name": "南京江北新区",
            "publish_time": "2026-11-02 11:05:00",
            "content": "正文内容",
        }
        live = dict(cached, title=live_title)
        url = "https://mp.weixin.qq.com/s/MohnBJhrvvViFA1JuQo8Ag"
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"WECHAT_CAPTURE_CACHE_DIR": ""}, clear=False), \
                patch.object(rpa, "activate_window"), \
                patch.object(rpa, "append_local_exports"), \
                patch.object(rpa, "user32"), \
                patch.object(rpa, "find_article_window", return_value=(1, rpa.Rect(0, 0, 100, 100))), \
                patch.object(rpa, "copy_article_url", side_effect=[url, url]), \
                patch.object(rpa, "load_cached_page", return_value=cached), \
                patch.object(rpa, "parse_article_with_retry", return_value=live) as parse_live, \
                patch.object(rpa, "capture_window", return_value=Image.new("RGB", (100, 100))), \
                patch.object(rpa.ARTICLE_EVIDENCE_OCR, "inspect", return_value={}), \
                patch.object(rpa, "probe_page", return_value={}), \
                patch.object(rpa, "picture_share_count", return_value=None), \
                patch.object(rpa, "extract_local_interaction_metrics",
                             return_value=({"share_count": 120}, "template-ocr-share-only", None)), \
                patch.object(rpa, "ingest", return_value={"status": "updated"}) as ingest_mock, \
                patch.object(rpa, "log_event") as log_mock:
            result = rpa.collect_open_article(
                None,
                Path(directory),
                write_mongo=True,
                export_jsonl=None,
                export_csv=None,
                expected_title=expected_title,
                expected_account="南京江北新区",
                allow_vl=False,
                metric_mode="share",
            )
            return result, parse_live, ingest_mock, log_mock

    def test_cached_title_mismatch_refetches_live_article_when_renamed(self):
        """公众号发文后改标题时，丢弃旧缓存重抓线上标题并正常入库。"""
        result, parse_live, ingest_mock, log_mock = self._run_collect_with_cache(
            cached_title="注意看，这是医院不是养老院",
            live_title="注意看，这是医院，也可以来养老",
            expected_title="注意看，这是医院，也可以来养老",
        )
        parse_live.assert_called_once_with("https://mp.weixin.qq.com/s/MohnBJhrvvViFA1JuQo8Ag")
        self.assertEqual(ingest_mock.call_args.kwargs["page"]["title"], "注意看，这是医院，也可以来养老")
        self.assertEqual(result["verification"]["parsed_title"], "注意看，这是医院，也可以来养老")
        events = [call.args[0] for call in log_mock.call_args_list]
        self.assertIn("article_cached_title_mismatch_refetch", events)
        self.assertNotIn("article_page_reused_from_mongo", events)

    def test_cached_title_mismatch_still_raises_when_live_title_also_mismatches(self):
        """重抓线上页面后标题仍与卡片不一致时，依然抛出 ArticleMismatchError。"""
        with self.assertRaisesRegex(rpa.ArticleMismatchError, "文章标题不匹配"):
            self._run_collect_with_cache(
                cached_title="注意看，这是医院不是养老院",
                live_title="完全无关的另一篇文章标题",
                expected_title="注意看，这是医院，也可以来养老",
            )

    def test_ingest_updates_title_when_article_renamed(self):
        """更新已有链接记录时，若网页标题已改名则同步更新 article.title。"""
        import article_ingest

        existing_doc = {
            "_id": "doc-1",
            "account": {"id": "acc-1", "name": "南京江北新区"},
            "article": {
                "title": "注意看，这是医院不是养老院",
                "publishDate": article_ingest.parse_publish_time("2026-11-02 11:05"),
                "content": {"text": "正文内容"},
            },
            "source": {"type": "wechat-desktop-rpa"},
        }
        updated_calls = []

        class FakeCollection:
            database = SimpleNamespace(name="weixin")
            name = "article"

            def create_index(self, *args, **kwargs):
                return "idx"

            def find_one(self, query, projection=None):
                if "name" in query:
                    return {"id": "acc-1"}
                return existing_doc

            def update_one(self, flt, update, upsert=False):
                updated_calls.append((flt, update, upsert))

        class FakeClient:
            def __getitem__(self, name):
                return {"article": FakeCollection(), "collection_target": FakeCollection()}

            def close(self):
                pass

        res = article_ingest.ingest(
            url="https://mp.weixin.qq.com/s/MohnBJhrvvViFA1JuQo8Ag",
            metrics={"share_count": 120, "metric_source": "template-ocr-share-only"},
            mongo_uri="mongodb://localhost:27017/",
            database_name="weixin",
            collection_name="article",
            page={
                "title": "注意看，这是医院，也可以来养老",
                "account_name": "南京江北新区",
                "publish_time": "2026-11-02 11:05",
                "content": "正文内容",
            },
            mongo_client=FakeClient(),
        )
        self.assertEqual(res["status"], "updated")
        self.assertEqual(res["baseFieldsUpdated"], ["article.title"])
        self.assertEqual(updated_calls[0][1]["$set"]["article.title"], "注意看，这是医院，也可以来养老")


if __name__ == "__main__":
    unittest.main()
