"""公众号搜索结果识别的保守匹配回归测试。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from wechat_profile_ocr import WeChatProfileOCR, _account_name_match
from wechat_visual_rpa import (
    classify_collection_error,
    resolve_search_account_name,
    resolve_secondary_filter_name,
)


def _row(text: str, left: float, top: float, right: float, bottom: float) -> dict:
    return {
        "text": text,
        "normalized": text,
        "confidence": 0.99,
        "left": left,
        "right": right,
        "top": top,
        "bottom": bottom,
        "center_x": (left + right) / 2,
        "center_y": (top + bottom) / 2,
    }


class AccountMatchingTests(unittest.TestCase):
    def test_ascii_case_difference_is_accepted(self) -> None:
        matched, method = _account_name_match("ComfyUI中文", "ComfyUi中文")
        self.assertTrue(matched)
        self.assertEqual(method, "ascii-case-ignored")

    def test_i_and_l_ocr_confusion_is_accepted_only_when_other_chars_match(self) -> None:
        matched, method = _account_name_match("海螺AI-MiniMaxHub", "海螺Al-MiniMaxHub")
        self.assertTrue(matched)
        self.assertEqual(method, "ocr-i-l-confusion")

    def test_known_bili_ocr_confusion_is_accepted(self) -> None:
        matched, method = _account_name_match("哔哩哔哩技术", "哗哩哗哩技术")
        self.assertTrue(matched)
        self.assertEqual(method, "ocr-chinese-confusion")

    def test_known_qwen_ocr_confusion_is_accepted(self) -> None:
        matched, method = _account_name_match("千问大模型", "干问大模型")
        self.assertTrue(matched)
        self.assertEqual(method, "ocr-chinese-confusion")

    def test_ai_prefix_i_omission_is_accepted(self) -> None:
        matched, method = _account_name_match("AI新工匠", "A新工匠")
        self.assertTrue(matched)
        self.assertEqual(method, "ocr-ai-prefix-i-omitted")

    def test_unrelated_similar_name_stays_rejected(self) -> None:
        matched, method = _account_name_match("ComfyUI中文", "ComfyUl中文站")
        self.assertFalse(matched)
        self.assertEqual(method, "")

    def test_alias_only_changes_the_search_name(self) -> None:
        # 测试自带临时别名，避免依赖被 Git 忽略的本机配置文件。
        with TemporaryDirectory() as temp_dir:
            aliases_path = Path(temp_dir) / "account_aliases.json"
            aliases_path.write_text(
                '{"通义千问Qwen": "千问大模型", "通义大模型": "千问大模型"}',
                encoding="utf-8",
            )
            with patch("wechat_visual_rpa.ACCOUNT_ALIASES_PATH", aliases_path):
                self.assertEqual(
                    resolve_search_account_name("通义千问Qwen"), "千问大模型"
                )
                self.assertEqual(
                    resolve_search_account_name("通义大模型"), "千问大模型"
                )
                self.assertEqual(
                    resolve_search_account_name("不存在的账号"), "不存在的账号"
                )

    def test_verified_identity_suffix_is_accepted(self) -> None:
        matched, method = _account_name_match("书生Intern", "书生Intern事业单位")
        self.assertTrue(matched)
        self.assertEqual(method, "safe-suffix-alias")

    def test_identity_badge_with_ocr_comma_is_accepted(self) -> None:
        matched, method = _account_name_match("鼓楼微讯", "鼓楼微讯,政府")
        self.assertTrue(matched)
        self.assertEqual(method, "safe-suffix-alias")
        matched, method = _account_name_match("鼓楼微讯", "鼓楼微讯，政府")
        self.assertTrue(matched)
        self.assertEqual(method, "safe-suffix-alias")
        # 逗号后面如果不是认证标，仍然是另一个名称，不能点进去。
        self.assertFalse(_account_name_match("鼓楼微讯", "鼓楼微讯,鼓楼文讯")[0])

    def test_filter_and_account_not_found_errors_are_separated(self) -> None:
        self.assertEqual(
            classify_collection_error(
                RuntimeError("二级公众号筛选未确认选中：下划线未显示")
            ),
            "account_filter",
        )
        self.assertEqual(
            classify_collection_error(
                RuntimeError("公众号筛选已选中，但未找到可确认的同名公众号：AI新工匠")
            ),
            "account_not_found",
        )
        self.assertEqual(
            classify_collection_error(
                RuntimeError("二级服务号筛选未确认选中：未检测到选中状态")
            ),
            "account_filter",
        )
        self.assertEqual(
            classify_collection_error(
                RuntimeError("服务号筛选已选中，但未找到可确认的同名服务号：我的南京官方号")
            ),
            "account_not_found",
        )

    def test_secondary_filter_resolution_for_service_accounts(self) -> None:
        self.assertEqual(resolve_secondary_filter_name("我的南京官方号"), "服务号")
        self.assertEqual(resolve_secondary_filter_name("我的南京官方号 "), "服务号")
        self.assertEqual(resolve_secondary_filter_name(" 量子位 "), "公众号")
        self.assertEqual(resolve_secondary_filter_name("腾讯技术工程"), "公众号")
        self.assertEqual(
            resolve_secondary_filter_name("我的南京别名", search_name="我的南京官方号"),
            "服务号",
        )

    def test_service_account_card_with_service_tag_is_identified(self) -> None:
        ocr = WeChatProfileOCR.__new__(WeChatProfileOCR)
        ocr._rows = lambda _image: [
            {
                "text": "我的南京官方号",
                "normalized": "我的南京官方号",
                "left": 80.0,
                "right": 260.0,
                "bottom": 300.0,
                "center_x": 170.0,
                "center_y": 280.0,
                "confidence": 0.99,
            },
            {
                "text": "服务号",
                "normalized": "服务号",
                "left": 80.0,
                "right": 140.0,
                "bottom": 330.0,
                "center_x": 110.0,
                "center_y": 320.0,
                "confidence": 0.99,
            },
            {
                "text": "南京市城市数字化治理中心",
                "normalized": "南京市城市数字化治理中心",
                "left": 80.0,
                "right": 320.0,
                "bottom": 360.0,
                "center_x": 200.0,
                "center_y": 345.0,
                "confidence": 0.99,
            },
        ]
        result = ocr.locate_search_result(Image.new("RGB", (1000, 1000)), "我的南京官方号")
        self.assertTrue(result["found"])
        self.assertTrue(result["is_official_account"])
        self.assertIn("服务号", result["official_evidence"])
        self.assertEqual(result["company"], "南京市城市数字化治理中心")

    def test_service_card_without_type_tag_is_accepted_after_filter_confirmed(self) -> None:
        # 真实截图：服务号筛选已选中，卡片只显示认证主体和“上次使用”，
        # 没有“服务号”文字或“篇原创内容”，过去会被误判为无关账号。
        ocr = WeChatProfileOCR.__new__(WeChatProfileOCR)
        ocr._rows = lambda _image: [
            _row("账号", 265, 127, 303, 150),
            _row("不限", 140, 177, 173, 196),
            _row("小程序", 190, 177, 239, 196),
            _row("公众号", 257, 177, 303, 196),
            _row("服务号", 322, 176, 371, 198),
            _row("视频号", 389, 177, 436, 196),
            _row("我的南京官方号", 219, 250, 349, 273),
            _row("南京大数据集团有限公司", 220, 279, 392, 296),
            _row("上次使用", 218, 296, 272, 317),
            _row("“我的南京”是南京城市智能门户，整合政府相关部门和公共事业单位的服务资源", 222, 320, 770, 340),
            _row("南京宁惠保", 230, 378, 314, 401),
            _row("@国务院", 511, 379, 588, 399),
            _row("南京市12345政务热线事业单位", 220, 440, 453, 464),
        ]
        screenshot = Image.new("RGB", (1114, 1032))

        rejected = ocr.locate_search_result(screenshot, "我的南京官方号")
        self.assertFalse(rejected["found"])
        self.assertEqual(rejected["official_evidence"], [])

        accepted = ocr.locate_search_result(
            screenshot,
            "我的南京官方号",
            filter_name="服务号",
            filter_confirmed=True,
        )
        self.assertTrue(accepted["found"])
        self.assertTrue(accepted["is_official_account"])
        self.assertIn("二级服务号筛选已确认", accepted["official_evidence"])
        self.assertEqual(accepted["company"], "南京大数据集团有限公司")

    def test_unconfirmed_or_unrelated_filter_does_not_bypass_card_evidence(self) -> None:
        ocr = WeChatProfileOCR.__new__(WeChatProfileOCR)
        ocr._rows = lambda _image: [
            _row("我的南京官方号", 219, 250, 349, 273),
            _row("南京大数据集团有限公司", 220, 279, 392, 296),
        ]
        screenshot = Image.new("RGB", (1114, 1032))
        for filter_name, confirmed in (("服务号", False), ("不限", True), ("", True)):
            result = ocr.locate_search_result(
                screenshot,
                "我的南京官方号",
                filter_name=filter_name,
                filter_confirmed=confirmed,
            )
            self.assertFalse(result["found"], (filter_name, confirmed))

    def test_personal_subject_with_original_count_stays_valid_after_public_filter(self) -> None:
        # 微信公众号二级筛选后，卡片的“个人”是主体类型，不代表它不是公众号。
        ocr = WeChatProfileOCR.__new__(WeChatProfileOCR)
        ocr._rows = lambda _image: [
            {
                "text": "AI新工匠",
                "normalized": "AI新工匠",
                "left": 80.0,
                "right": 200.0,
                "bottom": 300.0,
                "center_x": 140.0,
                "center_y": 280.0,
                "confidence": 0.99,
            },
            {
                "text": "个人",
                "normalized": "个人",
                "left": 80.0,
                "right": 120.0,
                "bottom": 330.0,
                "center_x": 100.0,
                "center_y": 320.0,
                "confidence": 0.99,
            },
            {
                "text": "127篇原创内容",
                "normalized": "127篇原创内容",
                "left": 80.0,
                "right": 210.0,
                "bottom": 360.0,
                "center_x": 145.0,
                "center_y": 350.0,
                "confidence": 0.99,
            },
        ]
        result = ocr.locate_search_result(Image.new("RGB", (1000, 1000)), "AI新工匠")
        self.assertTrue(result["found"])
        self.assertIn("127篇原创内容", result["official_evidence"])

    def test_government_badge_joined_by_comma_locates_original_content_card(self) -> None:
        ocr = WeChatProfileOCR.__new__(WeChatProfileOCR)
        ocr._rows = lambda _image: [
            {
                "text": "鼓楼微讯,政府",
                "normalized": "鼓楼微讯,政府",
                "left": 80.0,
                "right": 280.0,
                "bottom": 300.0,
                "center_x": 180.0,
                "center_y": 280.0,
                "confidence": 0.99,
            },
            {
                "text": "319篇原创内容3小时前更新",
                "normalized": "319篇原创内容3小时前更新",
                "left": 80.0,
                "right": 320.0,
                "bottom": 360.0,
                "center_x": 200.0,
                "center_y": 345.0,
                "confidence": 0.99,
            },
        ]
        result = ocr.locate_search_result(Image.new("RGB", (1000, 1000)), "鼓楼微讯")
        self.assertTrue(result["found"])
        self.assertEqual(result["name_match_method"], "safe-suffix-alias")
        self.assertIn("319篇原创内容3小时前更新", result["official_evidence"])


if __name__ == "__main__":
    unittest.main()
