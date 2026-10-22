"""账号分类选中校验：下划线占比应按文字宽度计算。"""

from __future__ import annotations

import unittest

from PIL import Image, ImageDraw

from wechat_profile_ocr import WeChatProfileOCR


def _account_rows() -> list[dict[str, float | str]]:
    return [
        {
            "text": "账号",
            "normalized": "账号",
            "left": 275.0,
            "right": 372.0,
            "top": 191.0,
            "bottom": 222.0,
            "center_x": 323.5,
            "center_y": 206.5,
            "confidence": 0.99,
        },
        *[
            {
                "text": name,
                "normalized": name,
                "left": 80.0 + index * 70,
                "right": 140.0 + index * 70,
                "top": 250.0,
                "bottom": 280.0,
                "center_x": 110.0 + index * 70,
                "center_y": 265.0,
                "confidence": 0.99,
            }
            for index, name in enumerate(("不限", "小程序", "公众号", "服务号", "视频号"))
        ],
        {
            "text": "公众号",
            "normalized": "公众号",
            "left": 80.0,
            "right": 150.0,
            "top": 360.0,
            "bottom": 390.0,
            "center_x": 115.0,
            "center_y": 375.0,
            "confidence": 0.99,
        },
    ]


def _screenshot_with_underline(dark_pixels: int) -> Image.Image:
    """复现宽窗口里、下划线只覆盖文字中段的截图。"""
    image = Image.new("RGB", (1485, 1528), "white")
    if dark_pixels <= 0:
        return image
    text_left, text_right = 275, 372
    text_width = text_right - text_left
    start = text_left + (text_width - dark_pixels) // 2
    # 下划线位于文字框底边下方，和线上失败截图的相对位置一致。
    ImageDraw.Draw(image).rectangle((start, 232, start + dark_pixels - 1, 233), fill=(25, 25, 25))
    return image


class AccountTabSelectionTests(unittest.TestCase):
    def test_short_underline_on_wide_window_counts_as_selected(self) -> None:
        ocr = WeChatProfileOCR.__new__(WeChatProfileOCR)
        ocr._rows = lambda _image: _account_rows()
        # 69/157 ≈ 0.439，旧算法按整窗扩边后会低于 0.45。
        result = ocr.validate_account_tab_selected(_screenshot_with_underline(69))
        self.assertTrue(result["selected"])
        self.assertGreaterEqual(result["underline_ratio"], 0.45)

    def test_missing_underline_stays_unselected(self) -> None:
        ocr = WeChatProfileOCR.__new__(WeChatProfileOCR)
        ocr._rows = lambda _image: _account_rows()
        result = ocr.validate_account_tab_selected(_screenshot_with_underline(0))
        self.assertFalse(result["selected"])
        self.assertEqual(result["reason"], "账号下划线或账号结果证据未确认")


if __name__ == "__main__":
    unittest.main()
