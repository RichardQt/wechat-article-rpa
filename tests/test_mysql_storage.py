"""MySQL 存储与查询操作的回归测试。"""

from __future__ import annotations

import unittest
from datetime import datetime

import article_ingest
import db_mysql
import rpa_control_panel as panel


class MySQLStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            conn = db_mysql.get_mysql_connection()
            db_mysql.ensure_mysql_schema(conn)
            conn.close()
            cls.mysql_available = True
        except Exception:
            cls.mysql_available = False

    def test_generate_object_id_format(self) -> None:
        """生成的 ID 必须为 24 位十六进制字符，与 MongoDB ObjectId 长度和字符集一致。"""
        id1 = db_mysql.generate_object_id()
        id2 = db_mysql.generate_object_id()
        self.assertEqual(len(id1), 24)
        self.assertEqual(len(id2), 24)
        self.assertNotEqual(id1, id2)
        int(id1, 16)
        int(id2, 16)

    def test_mysql_config_parsing(self) -> None:
        """验证默认与环境变量连接配置解析。"""
        cfg = db_mysql.get_mysql_config()
        self.assertIn("host", cfg)
        self.assertIn("port", cfg)
        self.assertIn("user", cfg)
        self.assertIn("database", cfg)

    def test_list_accounts_returns_valid_structure(self) -> None:
        if not self.mysql_available:
            self.skipTest("MySQL 服务未就绪")
        result = panel.list_accounts(limit=10)
        self.assertIn("items", result)
        self.assertIn("total", result)
        self.assertIn("summary", result)
        self.assertIn("categories", result)
        self.assertIsInstance(result["items"], list)
        if result["items"]:
            item = result["items"][0]
            self.assertIn("name", item)
            self.assertIn("coverage_status", item)
            self.assertIn("article_count", item)

    def test_list_articles_pagination_and_fields(self) -> None:
        if not self.mysql_available:
            self.skipTest("MySQL 服务未就绪")
        result = panel.list_articles(date_filter="all", limit=5, offset=0)
        self.assertIn("items", result)
        self.assertIn("total", result)
        self.assertIsInstance(result["items"], list)
        if result["items"]:
            article = result["items"][0]
            self.assertIn("id", article)
            self.assertIn("title", article)
            self.assertIn("account_name", article)
            self.assertIn("url", article)
            self.assertIn("publish_time", article)

    def test_get_article_detail_and_interaction(self) -> None:
        if not self.mysql_available:
            self.skipTest("MySQL 服务未就绪")
        articles = panel.list_articles(date_filter="all", limit=1)
        if not articles["items"]:
            self.skipTest("数据库中暂无文章测试数据")
        art_id = articles["items"][0]["id"]
        detail = panel.get_article_detail(art_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail["id"], art_id)
        self.assertIn("content", detail)
        self.assertIn("interaction", detail)

    def test_article_export_rows_format(self) -> None:
        if not self.mysql_available:
            self.skipTest("MySQL 服务未就绪")
        rows = panel.article_export_rows(date_filter="all")
        self.assertIsInstance(rows, list)
        if rows:
            row = rows[0]
            self.assertIn("account_name", row)
            self.assertIn("title", row)
            self.assertIn("content", row)
            self.assertIn("share_count", row)

    def test_account_export_rows_format(self) -> None:
        if not self.mysql_available:
            self.skipTest("MySQL 服务未就绪")
        rows = panel.account_export_rows()
        self.assertIsInstance(rows, list)
        if rows:
            row = rows[0]
            self.assertIn("name", row)
            self.assertIn("record_id", row)
            self.assertIn("category", row)

    def test_preview_account_import_validation(self) -> None:
        if not self.mysql_available:
            self.skipTest("MySQL 服务未就绪")
        preview = panel.preview_account_import([
            {"公众号名称": "新建测试账号A", "分类": "测试", "账号类型": "公众号"},
            {"公众号名称": "", "分类": "测试"},  # 空名称报错
        ])
        self.assertEqual(preview["summary"]["total"], 2)
        self.assertEqual(preview["items"][0]["status"], "valid")
        self.assertEqual(preview["items"][1]["status"], "error")

    def test_article_ingest_dry_run(self) -> None:
        res = article_ingest.ingest(
            url="https://mp.weixin.qq.com/s/sample_unit_test",
            metrics={"share_count": 50, "metric_source": "test-source"},
            page={
                "title": "测试单测文章标题",
                "account_name": "南京发布",
                "publish_time": "2026-11-09 10:00",
                "content": "测试单测正文内容",
            },
            dry_run=True,
        )
        self.assertEqual(res["status"], "dry_run")
        self.assertEqual(res["title"], "测试单测文章标题")
        self.assertEqual(res["account_name"], "南京发布")

    def test_load_cached_page_mysql(self) -> None:
        if not self.mysql_available:
            self.skipTest("MySQL 服务未就绪")
        articles = panel.list_articles(date_filter="all", limit=1)
        if not articles["items"]:
            self.skipTest("数据库中暂无文章")
        url = articles["items"][0]["url"]
        if url:
            cached = article_ingest.load_cached_page(url)
            self.assertIsNotNone(cached)
            assert cached is not None
            self.assertEqual(cached["title"], articles["items"][0]["title"])


if __name__ == "__main__":
    unittest.main()
