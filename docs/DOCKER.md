# Docker MySQL 部署

Docker 容器用于承载 MySQL 服务端存储。微信客户端、视觉采集器、OCR 和控制台仍然运行在 Windows 交互式桌面中，不能放入 Linux 容器。

## 一键启动与管理

确认 Docker Desktop 已启动：

```powershell
docker version
docker compose version
```

在项目根目录使用 `mysql.bat` 快捷脚本管理：

```powershell
# 启动 MySQL 容器并等待健康检查就绪
.\mysql.bat start

# 查看容器运行状态
.\mysql.bat status

# 查看 MySQL 容器日志
.\mysql.bat logs

# 显示连接配置信息
.\mysql.bat connection

# 停止容器（保留数据卷）
.\mysql.bat stop
```

也可以直接通过 PowerShell 传参执行：

```powershell
.\mysql.ps1 -Action start
.\mysql.ps1 -Action status
```

## 默认网络与端口

```text
127.0.0.1:3306 -> 容器 3306
```

如需修改绑定端口或主机地址，在项目根目录的 `.env` 文件中设置：

```ini
MYSQL_BIND_IP=127.0.0.1
MYSQL_PORT=3306
MYSQL_ROOT_PASSWORD=your_strong_password
MYSQL_DATABASE=weixin
MYSQL_USER=wechat_rpa
MYSQL_PASSWORD=your_strong_password
```

修改后重启容器生效：

```powershell
.\mysql.bat stop
.\mysql.bat start
```

> [!IMPORTANT]
> 切勿将无防火墙保护或使用默认弱密码的 MySQL 端口暴露到公网。若采集器与 MySQL 不在同一台机器，绑定 `0.0.0.0` 时必须在防火墙设置仅允许特定采集虚拟机 IP 访问。

## 数据持久化

MySQL 数据保存在 Docker 命名卷中：

```text
wechat-article-rpa_mysql_data
```

执行 `.\mysql.bat stop` 只会停止容器，不会删除数据卷。除非需要永久清空数据，否则切勿执行带 `--volumes` 的清空命令。

## 备份

运行以下命令自动在容器内执行 `mysqldump` 并将 SQL 文件导出至宿主机：

```powershell
.\mysql.bat backup
```

备份文件保存在：

```text
output\mysql-backups\weixin-YYYYMMDD-HHMMSS.sql
```

`output` 目录已被 Git 忽略，备份不会进入代码仓库。

## 恢复

恢复操作会覆盖目标数据库中的同名数据表，需要附加 `-Force` 开关二次确认：

```powershell
.\mysql.ps1 -Action restore -BackupFile .\output\mysql-backups\weixin-20261109-120000.sql -Force
```

恢复前建议先执行一次备份，并确保当前没有采集任务正在向数据库写入。

## 容器初始化机制

`docker/mysql-init.sql` 会在容器初次创建数据卷时由 MySQL 官方镜像自动加载执行，负责：

- 创建 `collection_target`、`article`、`article_interaction_history`、`collection_runs`、`daily_report` 5 张表；
- 设置字符集为 `utf8mb4`、排序规则为 `utf8mb4_unicode_ci`；
- 建立 `uniq_article_url_normalized`、`idx_article_publish_time` 等核心索引。

若需查看历史 MongoDB 容器以做数据迁移回溯，`compose.yaml` 中保留了 `mongodb` 服务定义，仍可通过 `.\mongodb.bat` 按需拉起。
