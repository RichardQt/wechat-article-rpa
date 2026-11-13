# MySQL 数据库说明

本项目使用 MySQL 作为持久化存储。MySQL 用于可靠保存采集公众号名单、文章正文、多版本互动数据快照、采集运行记录和每日统计简报。

## 连接配置

默认连接参数如下：

```text
主机：127.0.0.1
端口：3306
数据库：weixin
字符集：utf8mb4 (utf8mb4_unicode_ci)
```

通过环境变量自定义：

```powershell
$env:MYSQL_HOST="127.0.0.1"
$env:MYSQL_PORT="3306"
$env:MYSQL_USER="root"
$env:MYSQL_PASSWORD="your_password"
$env:MYSQL_DB="weixin"
```

如果 MySQL 部署在外部服务器或 Docker 容器中，请确认 Windows 运行环境能正常访问其端口。生产环境请设置高强度密码，不要把无访问限制的 MySQL 暴露在公网。

## 数据表结构

数据库包含 5 张核心数据表：

### 1. 采集目标表 `collection_target`

记录受监控的目标公众号列表。

```sql
CREATE TABLE IF NOT EXISTS `collection_target` (
  `id` VARCHAR(32) NOT NULL PRIMARY KEY COMMENT '唯一标识',
  `account_id` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '账号自定义ID',
  `name` VARCHAR(128) NOT NULL COMMENT '公众号名称',
  `category` VARCHAR(64) NOT NULL DEFAULT '未分类' COMMENT '账号分类',
  `type` VARCHAR(64) NOT NULL DEFAULT '公众号' COMMENT '类型',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录入库时间',
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',
  UNIQUE KEY `uk_target_name` (`name`),
  KEY `idx_account_id` (`account_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='公众号监控目标表';
```

- `name`：公众号在系统中的标准名称；若微信客户端展示名与此不同，在 `config/account_aliases.json` 配置映射别名。

### 2. 文章主表 `article`

记录抓取到的文章基础信息、正文内容以及最新一次的互动数据。

```sql
CREATE TABLE IF NOT EXISTS `article` (
  `id` VARCHAR(32) NOT NULL PRIMARY KEY COMMENT '唯一标识',
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
  UNIQUE KEY `uk_url_normalized` (`url_normalized`),
  KEY `idx_account_name_publish` (`account_name`, `publish_date`),
  KEY `idx_publish_date` (`publish_date`),
  KEY `idx_account_id` (`account_id`),
  KEY `idx_last_updated` (`last_updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='微信公众号文章主表';
```

字段与幂等规则：

- `id`：24 位十六进制唯一 ID（兼容历史 ObjectId 格式与时间戳检索）；
- `url_normalized`：去除动态跟踪参数与锚点后的规范链接，通过唯一索引 `uk_url_normalized` 实现幂等去重；
- `content_text`：文章纯文本正文；空正文文章不会入库；
- 已有非空标题、正文和发布时间不会被后续重复采集覆盖；
- 每次成功采集互动数时，更新文章主表的最新互动数据，并向互动历史表追加一条新快照。

### 3. 互动数据历史表 `article_interaction_history`

记录每次成功探测到的互动指标时序快照，用于分析阅读、点赞和转发增长趋势。

```sql
CREATE TABLE IF NOT EXISTS `article_interaction_history` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键',
  `article_id` VARCHAR(32) NOT NULL COMMENT '关联文章ID',
  `collected_at` DATETIME NOT NULL COMMENT '互动数据采集时间',
  `recognition_method` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '识别方式',
  `source` VARCHAR(64) NOT NULL DEFAULT 'wechat-desktop-rpa' COMMENT '采集来源端',
  `share_count` INT NOT NULL DEFAULT 0 COMMENT '分享数',
  `read_count` INT DEFAULT NULL COMMENT '阅读数',
  `like_count` INT DEFAULT NULL COMMENT '点赞数',
  `favorite_count` INT DEFAULT NULL COMMENT '收藏数',
  `comment_count` INT DEFAULT NULL COMMENT '评论数',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY `idx_article_id` (`article_id`),
  KEY `idx_collected_at` (`collected_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文章互动指标历史快照表';
```

### 4. 采集运行记录表 `collection_runs`

记录自动化采集任务的批次历史。

```sql
CREATE TABLE IF NOT EXISTS `collection_runs` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `run_id` VARCHAR(64) NOT NULL,
  `status` VARCHAR(32) NOT NULL DEFAULT 'running',
  `started_at` DATETIME NOT NULL,
  `finished_at` DATETIME DEFAULT NULL,
  `account_count` INT NOT NULL DEFAULT 0,
  `article_count` INT NOT NULL DEFAULT 0,
  `error_message` TEXT DEFAULT NULL,
  `details_json` JSON DEFAULT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY `uk_run_id` (`run_id`),
  KEY `idx_started_at` (`started_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='采集任务运行历史表';
```

### 5. 每日简报表 `daily_report`

按日期汇总文章产出与总互动数，供控制台“每日简报”快速查询。

```sql
CREATE TABLE IF NOT EXISTS `daily_report` (
  `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  `report_date` DATE NOT NULL UNIQUE,
  `generated_at` DATETIME NOT NULL,
  `time_range_start` DATETIME NOT NULL,
  `time_range_end` DATETIME NOT NULL,
  `article_count` INT NOT NULL DEFAULT 0,
  `report_content` LONGTEXT NOT NULL,
  `send_status` VARCHAR(32) NOT NULL DEFAULT 'draft',
  `articles_json` JSON DEFAULT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY `idx_report_date` (`report_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='每日资讯简报汇总表';
```

## 初始化与结构自动同步

系统连接 MySQL 时会自动执行 `ensure_mysql_schema()`，如数据表不存在会自动创建，无需人工手动执行 DDL。

若需要手工在 MySQL 命令行或客户端中一次性初始化，执行根目录下的初始化脚本：

```powershell
Get-Content docker\mysql-init.sql | mysql -u root -p weixin
```

## 初始化账号名单

直接在 MySQL 中执行插入语句：

```sql
USE weixin;
INSERT INTO collection_target (id, account_id, name, category, type)
VALUES
  ('6adac23ec32c88e8c5a432e4', '', '量子位', '技术综合类', '公众号'),
  ('6adac237c32c88e8c5a432de', '', '机器之心', '技术综合类', '公众号')
ON DUPLICATE KEY UPDATE name=VALUES(name);
```

也可以直接在管理控制台（默认 `http://127.0.0.1:8010/`）的“公众号管理”页面通过 CSV 或 JSON 文件批量导入导出。

## 常用查询语句

### 查询某公众号最新的 20 篇文章

```sql
SELECT title, publish_date, latest_share_count, url
FROM article
WHERE account_name = '量子位'
ORDER BY publish_date DESC
LIMIT 20;
```

### 查询某篇文章的全部互动历史

```sql
SELECT collected_at, share_count, read_count, like_count, recognition_method
FROM article_interaction_history
WHERE article_id = '6adac23ec32c88e8c5a432e4'
ORDER BY collected_at ASC;
```

### 统计近 7 天各公众号发文量与总转发数

```sql
SELECT
  account_name,
  COUNT(*) AS article_count,
  SUM(COALESCE(latest_share_count, 0)) AS total_shares
FROM article
WHERE publish_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)
GROUP BY account_name
ORDER BY article_count DESC;
```

## 备份与恢复

### 使用 mysqldump 备份

备份整个 `weixin` 数据库：

```powershell
mysqldump -u root -p --default-character-set=utf8mb4 weixin > output\mysql-backups\weixin_backup.sql
```

仅备份表结构：

```powershell
mysqldump -u root -p -d weixin > output\mysql-backups\weixin_schema.sql
```

### 恢复数据库

```powershell
mysql -u root -p weixin < output\mysql-backups\weixin_backup.sql
```

### 使用项目脚本管理 Docker 数据库备份

如果使用项目自带的 Docker MySQL 方案：

```powershell
# 执行备份
.\mysql.bat backup

# 恢复备份
.\mysql.ps1 restore -BackupFile .\output\mysql-backups\weixin-20261109-120000.sql -Force
```
