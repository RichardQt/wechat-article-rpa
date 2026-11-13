"""MySQL 数据库连接与辅助操作模块。

负责连接管理、ID 生成、表结构自动初始化以及通用查询转换。
"""

from __future__ import annotations

import os
import secrets
import time
from contextlib import contextmanager
from typing import Any, Generator
from urllib.parse import parse_qs, unquote, urlsplit

import pymysql
import pymysql.cursors


def generate_object_id() -> str:
    """生成 24 字符的十六进制唯一标识（前 4 字节为秒级时间戳，后 8 字节为安全随机数）。

    与 MongoDB ObjectId 长度和前缀时间序保持一致，确保历史数据与新数据格式兼容。
    """
    timestamp = int(time.time()).to_bytes(4, byteorder="big")
    random_bytes = secrets.token_bytes(8)
    return (timestamp + random_bytes).hex()


def get_mysql_config() -> dict[str, Any]:
    """读取 MySQL 连接配置，优先从环境变量读取。"""
    uri = os.getenv("MYSQL_URI") or os.getenv("DATABASE_URL")
    if uri and (uri.startswith("mysql://") or uri.startswith("mysql+pymysql://")):
        parts = urlsplit(uri)
        query = parse_qs(parts.query)
        charset = query.get("charset", ["utf8mb4"])[0]
        database = parts.path.lstrip("/") or "weixin"
        port = parts.port or 3306
        username = unquote(parts.username or "root")
        password = unquote(parts.password or "")
        hostname = parts.hostname or "127.0.0.1"
        return {
            "host": hostname,
            "port": port,
            "user": username,
            "password": password,
            "database": database,
            "charset": charset,
        }

    return {
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", "123456"),
        "database": os.getenv("MYSQL_DATABASE", "weixin"),
        "charset": os.getenv("MYSQL_CHARSET", "utf8mb4"),
    }


def get_mysql_connection(
    *,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
    charset: str | None = None,
    connect_timeout: int = 5,
    cursorclass: type[pymysql.cursors.Cursor] = pymysql.cursors.DictCursor,
    autocommit: bool = True,
) -> pymysql.connections.Connection:
    """创建并返回 MySQL 数据库连接。"""
    cfg = get_mysql_config()
    return pymysql.connect(
        host=host or cfg["host"],
        port=port or cfg["port"],
        user=user or cfg["user"],
        password=password if password is not None else cfg["password"],
        database=database or cfg["database"],
        charset=charset or cfg["charset"],
        connect_timeout=connect_timeout,
        cursorclass=cursorclass,
        autocommit=autocommit,
    )


@contextmanager
def mysql_cursor(conn: pymysql.connections.Connection | None = None) -> Generator[tuple[pymysql.connections.Connection, pymysql.cursors.DictCursor], None, None]:
    """便捷上下文管理器：自动管理游标与生命周期。"""
    owns_conn = False
    if conn is None:
        conn = get_mysql_connection()
        owns_conn = True
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        yield conn, cursor
    finally:
        cursor.close()
        if owns_conn:
            conn.close()


def ensure_mysql_schema(conn: pymysql.connections.Connection) -> None:
    """初始化 MySQL 表结构（如未建表则自动创建）。"""
    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS `collection_target` (
          `id` VARCHAR(32) NOT NULL COMMENT '唯一标识',
          `account_id` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '账号自定义ID',
          `name` VARCHAR(128) NOT NULL COMMENT '公众号名称',
          `category` VARCHAR(64) NOT NULL DEFAULT '未分类' COMMENT '账号分类',
          `type` VARCHAR(64) NOT NULL DEFAULT '公众号' COMMENT '类型',
          `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录入库时间',
          `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录最后更新时间',
          PRIMARY KEY (`id`),
          UNIQUE KEY `uk_target_name` (`name`),
          KEY `idx_account_id` (`account_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='公众号监控目标表';
        """,
        """
        CREATE TABLE IF NOT EXISTS `article` (
          `id` VARCHAR(32) NOT NULL COMMENT '唯一标识',
          `account_id` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '公众号唯一ID',
          `account_name` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '公众号名称',
          `title` VARCHAR(500) NOT NULL DEFAULT '' COMMENT '文章标题',
          `url` VARCHAR(1024) NOT NULL DEFAULT '' COMMENT '微信文章原始链接',
          `url_normalized` VARCHAR(500) NOT NULL DEFAULT '' COMMENT '规范化文章链接(唯一幂等)',
          `publish_date` DATETIME DEFAULT NULL COMMENT '文章发布时间(北京时间)',
          `content_text` LONGTEXT DEFAULT NULL COMMENT '文章正文纯文本',
          `source_type` VARCHAR(64) NOT NULL DEFAULT 'wechat-desktop-rpa' COMMENT '采集来源类型',
          `source_synced_at` DATETIME DEFAULT NULL COMMENT '来源同步时间',
          `first_collected_at` DATETIME DEFAULT NULL COMMENT '首次采集时间',
          `last_updated_at` DATETIME DEFAULT NULL COMMENT '最后更新时间',
          `latest_share_count` INT NOT NULL DEFAULT 0 COMMENT '最新分享数快照',
          `latest_read_count` INT NOT NULL DEFAULT 0 COMMENT '最新阅读数快照',
          `latest_like_count` INT NOT NULL DEFAULT 0 COMMENT '最新点赞数快照',
          `latest_comment_count` INT NOT NULL DEFAULT 0 COMMENT '最新评论数快照',
          `latest_collected_at` DATETIME DEFAULT NULL COMMENT '最新互动数据采集时间',
          `interaction_history_json` JSON DEFAULT NULL COMMENT '完整互动指标历史快照JSON',
          `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'MySQL入库时间',
          `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'MySQL更新时间',
          PRIMARY KEY (`id`),
          UNIQUE KEY `uk_url_normalized` (`url_normalized`),
          KEY `idx_account_name_publish` (`account_name`, `publish_date`),
          KEY `idx_publish_date` (`publish_date`),
          KEY `idx_account_id` (`account_id`),
          KEY `idx_last_updated` (`last_updated_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='微信公众号文章主表';
        """,
        """
        CREATE TABLE IF NOT EXISTS `article_interaction_history` (
          `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
          `article_id` VARCHAR(32) NOT NULL COMMENT '关联文章ID',
          `collected_at` DATETIME NOT NULL COMMENT '互动数据采集时间',
          `recognition_method` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '识别方式',
          `source` VARCHAR(64) NOT NULL DEFAULT 'wechat-desktop-rpa' COMMENT '采集来源端',
          `share_count` INT NOT NULL DEFAULT 0 COMMENT '分享数',
          `read_count` INT DEFAULT NULL COMMENT '阅读数',
          `like_count` INT DEFAULT NULL COMMENT '点赞数',
          `favorite_count` INT DEFAULT NULL COMMENT '收藏数',
          `comment_count` INT DEFAULT NULL COMMENT '评论数',
          `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录入库时间',
          PRIMARY KEY (`id`),
          KEY `idx_article_id` (`article_id`),
          KEY `idx_collected_at` (`collected_at`),
          KEY `idx_article_collected` (`article_id`, `collected_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='文章互动指标历史快照表';
        """,
        """
        CREATE TABLE IF NOT EXISTS `collection_runs` (
          `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
          `run_id` VARCHAR(64) NOT NULL COMMENT '批次唯一标识',
          `status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '运行状态',
          `started_at` DATETIME DEFAULT NULL COMMENT '批次开始时间',
          `finished_at` DATETIME DEFAULT NULL COMMENT '批次结束时间',
          `account_count` INT NOT NULL DEFAULT 0 COMMENT '纳入账号数',
          `article_count` INT NOT NULL DEFAULT 0 COMMENT '采集文章数',
          `error_message` TEXT DEFAULT NULL COMMENT '错误信息',
          `details_json` JSON DEFAULT NULL COMMENT '运行详情JSON',
          `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
          PRIMARY KEY (`id`),
          UNIQUE KEY `uk_run_id` (`run_id`),
          KEY `idx_started_at` (`started_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='采集任务批次运行记录表';
        """,
        """
        CREATE TABLE IF NOT EXISTS `daily_report` (
          `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
          `report_date` DATE NOT NULL COMMENT '日报归属日期',
          `generated_at` DATETIME DEFAULT NULL COMMENT '生成时间',
          `time_range_start` DATETIME DEFAULT NULL COMMENT '统计区间开始',
          `time_range_end` DATETIME DEFAULT NULL COMMENT '统计区间结束',
          `article_count` INT NOT NULL DEFAULT 0 COMMENT '纳入文章数',
          `report_content` LONGTEXT DEFAULT NULL COMMENT '日报正文/Markdown',
          `send_status` VARCHAR(32) DEFAULT NULL COMMENT '发送状态',
          `articles_json` JSON DEFAULT NULL COMMENT '关联文章列表JSON快照',
          `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
          PRIMARY KEY (`id`),
          KEY `idx_report_date` (`report_date`),
          KEY `idx_generated_at` (`generated_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC COMMENT='编辑日报归档表';
        """,
    ]
    with conn.cursor() as cursor:
        for stmt in ddl_statements:
            cursor.execute(stmt)
