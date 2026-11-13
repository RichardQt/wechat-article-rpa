"""解析公众号文章链接，并导出本地文件或写入 MySQL 数据库。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from bs4 import BeautifulSoup

import db_mysql


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

_INDEX_READY: set[str] = set()


def shanghai_timezone():
    """返回东八区时区；Windows 未安装 IANA 时区库时使用固定 UTC+8 兜底。"""
    try:
        return ZoneInfo("Asia/Shanghai")
    except (KeyError, ZoneInfoNotFoundError):
        return timezone(timedelta(hours=8), name="Asia/Shanghai")


def normalize_article_url(url: str) -> str:
    """规范化公众号文章 URL，避免参数顺序或片段差异造成重复记录。"""
    value = str(url or "").strip()
    if not value:
        return ""
    parts = urlsplit(value)
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))


def ensure_article_indexes(collection: Any) -> bool:
    """兼容旧 MongoDB 接口或数据库索引检查。"""
    if hasattr(collection, "create_index"):
        namespace = f"{getattr(collection.database, 'name', 'db')}.{getattr(collection, 'name', 'article')}"
        if namespace in _INDEX_READY:
            return True
        try:
            collection.create_index(
                [("article.urlNormalized", 1)],
                name="article_url_normalized_unique",
                unique=True,
                sparse=True,
            )
            _INDEX_READY.add(namespace)
            return True
        except Exception:
            _INDEX_READY.add(namespace)
            return False
    return True


def load_cached_page(
    url: str,
    mongo_uri: str = "",
    database_name: str = "weixin",
    collection_name: str = "article",
    *,
    mysql_conn: Any | None = None,
    table_name: str = "article",
) -> dict[str, str] | None:
    """读取已有文章的完整字段；返回 None 表示仍需访问网页补齐。"""
    normalized_url = normalize_article_url(url)

    # 优先使用 MySQL 检查
    owns_conn = False
    conn = mysql_conn
    try:
        if conn is None and not mongo_uri.startswith("mongodb://"):
            try:
                conn = db_mysql.get_mysql_connection()
                owns_conn = True
            except Exception:
                conn = None

        if conn is not None and not hasattr(conn, "__getitem__"):
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT title, account_name, publish_date, content_text FROM `{table_name}` "
                    "WHERE url_normalized = %s OR url = %s LIMIT 1",
                    (normalized_url, url),
                )
                existing = cursor.fetchone()
                if not existing:
                    return None
                pub_time = existing.get("publish_date")
                if isinstance(pub_time, datetime):
                    pub_time = pub_time.strftime("%Y-%m-%d %H:%M")
                page = {
                    "title": str(existing.get("title") or "").strip(),
                    "account_name": str(existing.get("account_name") or "").strip(),
                    "publish_time": str(pub_time or ""),
                    "content": str(existing.get("content_text") or "").strip(),
                }
                return page if all(page.values()) else None
    except Exception:
        pass
    finally:
        if owns_conn and conn is not None:
            conn.close()

    # 备用/历史 MongoDB 读取分支
    if mongo_uri.startswith("mongodb://"):
        try:
            from pymongo import MongoClient

            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            try:
                collection = client[database_name][collection_name]
                ensure_article_indexes(collection)
                existing = collection.find_one(
                    {"$or": [{"article.urlNormalized": normalized_url}, {"article.url": url}]},
                    {"account": 1, "article": 1},
                )
                if not existing:
                    return None
                account = existing.get("account") or {}
                article = existing.get("article") or {}
                content = article.get("content") or {}
                page = {
                    "title": str(article.get("title") or "").strip(),
                    "account_name": str(account.get("name") or "").strip(),
                    "publish_time": article.get("publishDate") or "",
                    "content": str(content.get("text") or "").strip(),
                }
                return page if all(page.values()) else None
            finally:
                client.close()
        except Exception:
            return None

    return None


def clean_text(element: Any) -> str:
    if element is None:
        return ""
    for tag in element.select("script,style,svg,iframe,video,audio,img"):
        tag.decompose()
    text = element.get_text("\n", strip=True)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_publish_time(html: str, soup: BeautifulSoup) -> str:
    """从微信文章 HTML 中提取发布时间，优先读取明确的页面变量。"""
    publish_node = soup.select_one("#publish_time")
    publish_text = clean_text(publish_node)
    if publish_text:
        return publish_text

    # 微信会通过脚本把 createTime 写入空的 #publish_time 节点。
    text_patterns = (
        r"\bvar\s+createTime\s*=\s*['\"](\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})['\"]",
        r"\bcreate_time\s*:\s*['\"](\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})['\"]",
    )
    for pattern in text_patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)

    # 部分页面只保留秒级时间戳；按上海时区格式化为页面展示时间。
    timestamp_patterns = (
        r"\bvar\s+create_time\s*=\s*['\"]?(\d{10})['\"]?\s*\*?\s*1",
        r"\bori_create_time\s*:\s*['\"]?(\d{10})['\"]?",
        r"\bvar\s+oriCreateTime\s*=\s*['\"]?(\d{10})['\"]?",
    )
    for pattern in timestamp_patterns:
        match = re.search(pattern, html)
        if match:
            value = datetime.fromtimestamp(int(match.group(1)), shanghai_timezone())
            # publishDate 保存页面显示的北京时间
            return value.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M")
    return ""


def extract_picture_message(soup: BeautifulSoup) -> dict[str, str]:
    """图片消息正文由脚本渲染；只读已知字段，不执行网页 JavaScript。"""
    if not soup.select_one("#js_article.share_content_page"):
        return {}
    scripts = [node.get_text() for node in soup.find_all("script")
               if re.search(r"window\.cgiDataNew\s*=\s*\{", node.get_text())]
    if len(scripts) != 1 or not re.search(r"\bitem_show_type:\s*'8'", scripts[0]):
        return {}

    def field(name: str) -> str:
        matches = re.findall(r"\b" + re.escape(name) + r"\s*:\s*'((?:\\.|[^'\\])*)'", scripts[0])
        if len(matches) != 1:
            return ""
        value = re.sub(r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|[nrt'\"\\])",
                       lambda m: chr(int(m[1][1:], 16)) if m[1][0] in "xu"
                       else {"n": "\n", "r": "\r", "t": "\t"}.get(m[1], m[1]), matches[0])
        return html.unescape(value).strip()

    title = soup.select_one('meta[property="og:title"]')
    result = {
        "title": title.get("content", "").strip() if title else "",
        "content": field("content_noencode"),
        "account_name": field("nick_name"),
        "publish_time": field("create_time"),
    }
    return result if all(result.values()) else {}


def parse_page(url: str, *, include_network_identity: bool = False) -> dict[str, str]:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8"
    page = parse_page_html(response.text)
    if include_network_identity:
        from network_metrics import page_article_identity
        resolved = response.url if isinstance(getattr(response, "url", None), str) else url
        page["network_article_id"] = page_article_identity(resolved, response.text) or ""
    return page


def parse_page_html(document: str) -> dict[str, str]:
    """解析已取得的响应正文，供 HTTP 下载和本机抓包共用。"""
    soup = BeautifulSoup(document, "html.parser")
    title_node = soup.select_one("#activity-name")
    content_node = soup.select_one("#js_content")
    account_node = soup.select_one("#js_name") or soup.select_one(".profile_nickname")
    title = clean_text(title_node)
    content = clean_text(content_node)
    publish_time = extract_publish_time(document, soup)

    account_name = clean_text(account_node)
    if not account_name:
        match = re.search(r'var\s+nickname\s*=\s*htmlDecode\("(.*?)"\)', document)
        account_name = match.group(1) if match else ""

    if not title or not content:
        picture = extract_picture_message(soup)
        if picture:
            title, content = picture["title"], picture["content"]
            account_name, publish_time = picture["account_name"], picture["publish_time"]

    if not title:
        raise ValueError("文章页面没有标题")
    if not content:
        raise ValueError("文章正文为空，拒绝写入数据库")
    return {
        "title": title,
        "account_name": account_name,
        "publish_time": publish_time,
        "content": content,
    }


def parse_publish_time(value: str | None) -> datetime:
    if not value:
        raise ValueError("缺少文章发布时间")
    normalized = value.strip().replace("年", "-").replace("月", "-").replace("日", "")
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, pattern)
        except ValueError:
            continue
    raise ValueError(f"无法解析发布时间：{value}")


def stable_account_id(account_name: str) -> str:
    digest = hashlib.sha1(account_name.encode("utf-8")).hexdigest()[:16].upper()
    return f"RPA_{digest}"


def build_interaction(metrics: dict[str, Any], collected_at: datetime) -> dict[str, Any]:
    interaction = {
        "recognitionMethod": metrics.get("metric_source"),
        "collectedAt": collected_at,
        "source": "wechat-desktop-rpa",
    }
    field_map = {
        "read_count": "readCount",
        "like_count": "likeCount",
        "share_count": "shareCount",
        "favorite_count": "favoriteCount",
        "comment_count": "commentCount",
    }
    for source_name, target_name in field_map.items():
        value = metrics.get(source_name)
        if value is not None:
            interaction[target_name] = value
    return interaction


def _ingest_mongo_fallback(
    url: str,
    metrics: dict[str, Any],
    mongo_uri: str,
    database_name: str,
    collection_name: str,
    dry_run: bool,
    page: dict[str, str] | None,
    target_collection_name: str,
    expected_account_name: str | None,
    mongo_client: Any | None,
) -> dict[str, Any]:
    """兼容旧单元测试中传入 fake mongo client 的分支。"""
    from pymongo import MongoClient

    normalized_url = normalize_article_url(url)
    client = mongo_client
    owns_client = False
    if client is None:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        owns_client = True
    database = client[database_name]
    collection = database[collection_name]
    ensure_article_indexes(collection)
    existing = collection.find_one(
        {"$or": [{"article.urlNormalized": normalized_url}, {"article.url": url}]},
        {"_id": 1, "account": 1, "article": 1, "source": 1},
    )
    if page is None and existing:
        old_account = existing.get("account") or {}
        old_article = existing.get("article") or {}
        old_content = old_article.get("content") or {}
        cached_page = {
            "title": str(old_article.get("title") or "").strip(),
            "account_name": str(old_account.get("name") or expected_account_name or "").strip(),
            "publish_time": old_article.get("publishDate") or "",
            "content": str(old_content.get("text") or "").strip(),
        }
        if all(cached_page.values()):
            page = cached_page
    try:
        page = page or parse_page(url)
    except Exception:
        if owns_client and client is not None:
            client.close()
        raise
    account_name = page["account_name"].strip()
    publish_time = page["publish_time"] or metrics.get("publish_time")
    publish_date = publish_time if isinstance(publish_time, datetime) else parse_publish_time(publish_time)
    now = datetime.now(timezone.utc)
    interaction = build_interaction(metrics, now)
    result = {
        "url": url,
        "title": page["title"],
        "account_name": account_name,
        "publish_time": publish_time,
        "content_chars": len(page["content"]),
        "content": page["content"],
        "interaction": interaction,
        "status": "dry_run" if dry_run else "pending",
    }
    if dry_run:
        return result

    try:
        target = database[target_collection_name].find_one({"name": account_name}, {"id": 1})
        account_id = str((target or {}).get("id") or "").strip() or stable_account_id(account_name)
        if existing is None:
            existing = collection.find_one(
                {"$or": [{"article.urlNormalized": normalized_url}, {"article.url": url}]},
                {"account.id": 1, "account.name": 1, "article.title": 1, "article.publishDate": 1, "article.content.text": 1, "source.type": 1},
            )
        if existing is None:
            collection.update_one(
                {"article.urlNormalized": normalized_url},
                {
                    "$setOnInsert": {
                        "account.id": account_id,
                        "account.name": account_name,
                        "article.title": page["title"],
                        "article.url": url,
                        "article.publishDate": publish_date,
                        "article.content.text": page["content"],
                        "source.type": "wechat-desktop-rpa",
                        "firstCollectedAt": now,
                    },
                    "$set": {"article.urlNormalized": normalized_url, "source.syncedAt": now, "lastUpdatedAt": now},
                    "$push": {"interactionHistory": {"$each": [interaction], "$slice": -90}},
                },
                upsert=True,
            )
            result["status"] = "inserted"
            result["baseFieldsUpdated"] = ["all"]
            return result

        account = existing.get("account") or {}
        article = existing.get("article") or {}
        content = article.get("content") or {}
        source = existing.get("source") or {}
        missing_fields: dict[str, Any] = {}
        if not str(account.get("id") or "").strip():
            missing_fields["account.id"] = account_id
        if not str(account.get("name") or "").strip():
            missing_fields["account.name"] = account_name
        if page["title"] and str(article.get("title") or "").strip() != page["title"]:
            missing_fields["article.title"] = page["title"]
        if article.get("publishDate") is None:
            missing_fields["article.publishDate"] = publish_date
        if not str(content.get("text") or "").strip():
            missing_fields["article.content.text"] = page["content"]
        if not str(source.get("type") or "").strip():
            missing_fields["source.type"] = "wechat-desktop-rpa"

        collection.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {**missing_fields, "article.urlNormalized": normalized_url, "source.syncedAt": now, "lastUpdatedAt": now},
                "$push": {"interactionHistory": {"$each": [interaction], "$slice": -90}},
            },
        )
        result["status"] = "updated"
        result["baseFieldsUpdated"] = sorted(missing_fields)
        return result
    finally:
        if owns_client and client is not None:
            client.close()


def ingest(
    url: str,
    metrics: dict[str, Any],
    mongo_uri: str = "",
    database_name: str = "weixin",
    collection_name: str = "article",
    dry_run: bool = False,
    page: dict[str, str] | None = None,
    target_collection_name: str = "collection_target",
    expected_account_name: str | None = None,
    mongo_client: Any | None = None,
    *,
    mysql_conn: Any | None = None,
    table_name: str = "article",
    target_table_name: str = "collection_target",
    interaction_table_name: str = "article_interaction_history",
) -> dict[str, Any]:
    """将采集到的文章与互动指标写入 MySQL 数据库。"""
    # 兼容传入了测试 mock mongo_client 的回归测试
    if mongo_client is not None or (mongo_uri and not os.getenv("MYSQL_HOST") and not os.getenv("MYSQL_URI")):
        return _ingest_mongo_fallback(
            url=url,
            metrics=metrics,
            mongo_uri=mongo_uri,
            database_name=database_name,
            collection_name=collection_name,
            dry_run=dry_run,
            page=page,
            target_collection_name=target_collection_name,
            expected_account_name=expected_account_name,
            mongo_client=mongo_client,
        )

    normalized_url = normalize_article_url(url)
    owns_conn = False
    conn = mysql_conn
    existing: dict[str, Any] | None = None

    if not dry_run:
        if conn is None:
            conn = db_mysql.get_mysql_connection()
            owns_conn = True
        db_mysql.ensure_mysql_schema(conn)

        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT id, account_id, account_name, title, publish_date, content_text, source_type, "
                f"interaction_history_json, latest_share_count, latest_read_count, latest_like_count, "
                f"latest_comment_count, latest_collected_at FROM `{table_name}` "
                "WHERE url_normalized = %s OR url = %s LIMIT 1",
                (normalized_url, url),
            )
            existing = cursor.fetchone()

        if page is None and existing:
            pub_str = existing.get("publish_date")
            if isinstance(pub_str, datetime):
                pub_str = pub_str.strftime("%Y-%m-%d %H:%M")
            cached_page = {
                "title": str(existing.get("title") or "").strip(),
                "account_name": str(existing.get("account_name") or expected_account_name or "").strip(),
                "publish_time": str(pub_str or ""),
                "content": str(existing.get("content_text") or "").strip(),
            }
            if all(cached_page.values()):
                page = cached_page

    try:
        page = page or parse_page(url)
    except Exception:
        if owns_conn and conn is not None:
            conn.close()
        raise

    account_name = page["account_name"].strip()
    publish_time = page["publish_time"] or metrics.get("publish_time")
    publish_date = publish_time if isinstance(publish_time, datetime) else parse_publish_time(publish_time)
    now_beijing = datetime.now(shanghai_timezone()).replace(tzinfo=None)
    interaction = build_interaction(metrics, now_beijing)

    result: dict[str, Any] = {
        "url": url,
        "title": page["title"],
        "account_name": account_name,
        "publish_time": publish_time,
        "content_chars": len(page["content"]),
        "content": page["content"],
        "interaction": interaction,
        "status": "dry_run" if dry_run else "pending",
    }
    if dry_run:
        return result

    try:
        assert conn is not None
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT account_id FROM `{target_table_name}` WHERE name = %s LIMIT 1",
                (account_name,),
            )
            target = cursor.fetchone()
            account_id = str((target or {}).get("account_id") or "").strip() or stable_account_id(account_name)

            share_count = int(metrics.get("share_count") or 0)
            read_count = int(metrics.get("read_count") or 0)
            like_count = int(metrics.get("like_count") or 0)
            comment_count = int(metrics.get("comment_count") or 0)
            favorite_count = int(metrics.get("favorite_count") or 0)

            if existing is None:
                article_id = db_mysql.generate_object_id()
                interaction_history = [interaction]
                history_json = json.dumps(interaction_history, ensure_ascii=False, default=str)

                cursor.execute(
                    f"INSERT INTO `{table_name}` ("
                    "`id`, `account_id`, `account_name`, `title`, `url`, `url_normalized`, "
                    "`publish_date`, `content_text`, `source_type`, `source_synced_at`, "
                    "`first_collected_at`, `last_updated_at`, `latest_share_count`, `latest_read_count`, "
                    "`latest_like_count`, `latest_comment_count`, `latest_collected_at`, `interaction_history_json`"
                    ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        article_id,
                        account_id,
                        account_name,
                        page["title"],
                        url,
                        normalized_url,
                        publish_date,
                        page["content"],
                        "wechat-desktop-rpa",
                        now_beijing,
                        now_beijing,
                        now_beijing,
                        share_count,
                        read_count,
                        like_count,
                        comment_count,
                        now_beijing,
                        history_json,
                    ),
                )

                cursor.execute(
                    f"INSERT INTO `{interaction_table_name}` ("
                    "`article_id`, `collected_at`, `recognition_method`, `source`, "
                    "`share_count`, `read_count`, `like_count`, `favorite_count`, `comment_count`"
                    ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        article_id,
                        now_beijing,
                        str(metrics.get("metric_source") or ""),
                        "wechat-desktop-rpa",
                        share_count,
                        read_count,
                        like_count,
                        favorite_count,
                        comment_count,
                    ),
                )
                result["status"] = "inserted"
                result["baseFieldsUpdated"] = ["all"]
                return result

            # 已存在文章：更新缺失字段并追加互动历史
            article_id = str(existing["id"])
            missing_fields: dict[str, Any] = {}
            if not str(existing.get("account_id") or "").strip():
                missing_fields["account.id"] = account_id
            if not str(existing.get("account_name") or "").strip():
                missing_fields["account.name"] = account_name
            if page["title"] and str(existing.get("title") or "").strip() != page["title"]:
                missing_fields["article.title"] = page["title"]
            if existing.get("publish_date") is None:
                missing_fields["article.publishDate"] = publish_date
            if not str(existing.get("content_text") or "").strip():
                missing_fields["article.content.text"] = page["content"]
            if not str(existing.get("source_type") or "").strip():
                missing_fields["source.type"] = "wechat-desktop-rpa"

            raw_history = existing.get("interaction_history_json")
            history_list: list[dict[str, Any]] = []
            if isinstance(raw_history, str) and raw_history.strip():
                try:
                    history_list = json.loads(raw_history)
                except Exception:
                    history_list = []
            elif isinstance(raw_history, list):
                history_list = list(raw_history)

            history_list.append(interaction)
            history_list = history_list[-90:]
            history_json = json.dumps(history_list, ensure_ascii=False, default=str)

            cursor.execute(
                f"UPDATE `{table_name}` SET "
                "`account_id` = %s, "
                "`account_name` = %s, "
                "`title` = %s, "
                "`publish_date` = %s, "
                "`content_text` = %s, "
                "`url_normalized` = %s, "
                "`source_synced_at` = %s, "
                "`last_updated_at` = %s, "
                "`latest_share_count` = %s, "
                "`latest_read_count` = %s, "
                "`latest_like_count` = %s, "
                "`latest_comment_count` = %s, "
                "`latest_collected_at` = %s, "
                "`interaction_history_json` = %s "
                "WHERE `id` = %s",
                (
                    account_id if "account.id" in missing_fields else (existing.get("account_id") or account_id),
                    account_name if "account.name" in missing_fields else (existing.get("account_name") or account_name),
                    page["title"] if "article.title" in missing_fields else (existing.get("title") or page["title"]),
                    publish_date if "article.publishDate" in missing_fields else (existing.get("publish_date") or publish_date),
                    page["content"] if "article.content.text" in missing_fields else (existing.get("content_text") or page["content"]),
                    normalized_url,
                    now_beijing,
                    now_beijing,
                    share_count,
                    read_count,
                    like_count,
                    comment_count,
                    now_beijing,
                    history_json,
                    article_id,
                ),
            )

            cursor.execute(
                f"INSERT INTO `{interaction_table_name}` ("
                "`article_id`, `collected_at`, `recognition_method`, `source`, "
                "`share_count`, `read_count`, `like_count`, `favorite_count`, `comment_count`"
                ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    article_id,
                    now_beijing,
                    str(metrics.get("metric_source") or ""),
                    "wechat-desktop-rpa",
                    share_count,
                    read_count,
                    like_count,
                    favorite_count,
                    comment_count,
                ),
            )

            result["status"] = "updated"
            result["baseFieldsUpdated"] = sorted(missing_fields)
            return result
    finally:
        if owns_conn and conn is not None:
            conn.close()


def append_local_exports(
    record: dict[str, Any], jsonl_path: str | None, csv_path: str | None
) -> None:
    """逐篇落盘，避免长任务中途退出时丢失已经采集的数据。"""
    if jsonl_path:
        path = os.path.abspath(jsonl_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    if csv_path:
        path = os.path.abspath(csv_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fields = [
            "url", "title", "account_name", "publish_time", "content_chars", "content",
            "read_count", "like_count", "share_count", "favorite_count", "comment_count",
            "collected_at", "status",
        ]
        interaction = record.get("interaction", {})
        row = {
            "url": record.get("url"),
            "title": record.get("title"),
            "account_name": record.get("account_name"),
            "publish_time": record.get("publish_time"),
            "content_chars": record.get("content_chars"),
            "content": record.get("content"),
            "read_count": interaction.get("readCount"),
            "like_count": interaction.get("likeCount"),
            "share_count": interaction.get("shareCount"),
            "favorite_count": interaction.get("favoriteCount"),
            "comment_count": interaction.get("commentCount"),
            "collected_at": interaction.get("collectedAt"),
            "status": record.get("status"),
        }
        exists = os.path.exists(path) and os.path.getsize(path) > 0
        with open(path, "a", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            if not exists:
                writer.writeheader()
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--metrics-json", required=True)
    parser.add_argument("--mysql-host", default=os.getenv("MYSQL_HOST", "127.0.0.1"))
    parser.add_argument("--mysql-port", type=int, default=int(os.getenv("MYSQL_PORT", "3306")))
    parser.add_argument("--mysql-user", default=os.getenv("MYSQL_USER", "root"))
    parser.add_argument("--mysql-password", default=os.getenv("MYSQL_PASSWORD", "123456"))
    parser.add_argument("--database", default=os.getenv("MYSQL_DATABASE", "weixin"))
    parser.add_argument("--table", default=os.getenv("MYSQL_ARTICLE_TABLE", "article"))
    parser.add_argument("--dry-run", action="store_true")
    # 兼容历史选项
    parser.add_argument("--mongo-uri", default="")
    parser.add_argument("--collection", default="")
    args = parser.parse_args()

    result = ingest(
        url=args.url,
        metrics=json.loads(args.metrics_json),
        database_name=args.database,
        table_name=args.table or args.collection or "article",
        dry_run=args.dry_run,
        mongo_uri=args.mongo_uri,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
