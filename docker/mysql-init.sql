-- ====================================================================
-- 微信公众号 RPA 采集系统 - MySQL 数据库初始化脚本
-- 字符集: utf8mb4
-- ====================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

CREATE DATABASE IF NOT EXISTS `weixin` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `weixin`;

-- 1. 监控目标账号表 (collection_target)
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

-- 2. 微信文章主表 (article)
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

-- 3. 文章互动指标历史快照表 (article_interaction_history)
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

-- 4. 采集任务批次运行记录表 (collection_runs)
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

-- 5. 编辑日报归档表 (daily_report)
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
