# 微信公众号文章采集与推送系统

> 在 Windows 微信客户端中按公众号采集文章，提取正文、发布时间与互动数据，写入本机 MySQL；由常驻推送服务将新文章加密上报至远端平台。

> **项目边界：**本仓库负责公众号文章的采集、管理、存储与推送，不包含文章摘要生成、每日新闻、编辑日报或消息发送功能。

## 目录

- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [RPA 采集程序](#rpa-采集程序)
  - [启动方式](#启动方式)
  - [采集逻辑](#采集逻辑)
- [推送服务](#推送服务)
  - [运行 jar 的实际命令](#运行-jar-的实际命令)
  - [开机自启（计划任务）](#开机自启计划任务)
  - [日志保存与轮转](#日志保存与轮转)
  - [推送工作原理](#推送工作原理)
- [MySQL 数据库](#mysql-数据库)
- [管理控制台](#管理控制台)
- [配置项与数据目录](#配置项与数据目录)
- [运维命令速查](#运维命令速查)
- [常见问题](#常见问题)

## 系统架构

```text
Windows 微信客户端
       │  截图 / OCR / 鼠标键盘操作
       ▼
RPA 采集程序 (wechat_visual_rpa.py)
       │
       ▼
MySQL 数据库 (127.0.0.1:3306)
  └─ weixin.article          ← sync_flag 标记推送状态
       │
       ▼
推送服务 (push/local-information-reporter.jar)
       │  每 10 分钟扫描 sync_flag IS NULL 的文章
       │  SM4 加密 → HTTP POST
       ▼
远端平台 (m.mynj.cn:11005)
```

三个组成部分：

| 组件 | 角色 | 运行方式 |
|---|---|---|
| **RPA 采集程序** | 操作微信客户端采集文章入库 | 手动 / 控制台触发 / 定时任务 |
| **推送服务** | 扫描新文章、加密上报远端 | 开机自启，常驻后台 |
| **管理控制台** | 采集调度、账号与文章管理 | 手动或登录时启动 |

## 快速开始

### 1. 环境准备

```powershell
git clone git@github.com:Dhaizei/wechat-article-rpa.git
cd .\wechat-article-rpa
```

双击 `setup-env.bat`，安装脚本会自动安装 64 位 Python 3.10、创建 `.venv`、用清华镜像装依赖。也可手动：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

推送服务需要 Java 8 运行环境（`java -version` 可用即可）。

### 2. 配置

复制 `.env.example` 为 `.env`，按需修改。核心配置：

```text
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=******
MYSQL_DATABASE=weixin
CONTROL_PANEL_USERNAME=admin
CONTROL_PANEL_PASSWORD=强密码
```

### 3. 启动

| 要做什么 | 命令 |
|---|---|
| 启动管理控制台 | 双击 `start-control-panel.bat`，访问 `http://127.0.0.1:8010/` |
| 手动跑一次采集 | 控制台点"立即开始"，或双击 `start-rpa.bat` |
| 启动推送服务 | 已配开机自启；手动启动见[下文](#开机自启计划任务) |

## RPA 采集程序

### 启动方式

**方式一：管理控制台（推荐）**

```powershell
.\start-control-panel.bat
```

启动后访问 `http://127.0.0.1:8010/`，在页面上选择扫描范围（今天 / 昨天 / 今天和昨天）、采集指标（仅转发数 / 全部互动指标）、每账号上限，点击"立即开始"。

**方式二：一键采集脚本**

双击 `start-rpa.bat`（内部调用 `start-rpa.ps1`），实际执行的命令是：

```powershell
.\.venv\Scripts\python.exe .\wechat_visual_rpa.py `
  --run-search-accounts `
  --live `
  --accounts-from-mysql `
  --write-mysql `
  --metrics share `
  --window-layout auto `
  --max-articles 20 `
  --output-dir output\mysql-<时间戳> `
  --export-jsonl output\mysql-<时间戳>\articles.jsonl `
  --export-csv output\mysql-<时间戳>\articles.csv
```

参数含义：

| 参数 | 含义 |
|---|---|
| `--run-search-accounts --live` | 搜索模式 + 真实操作（非只读） |
| `--accounts-from-mysql` | 从 `weixin.collection_target` 表读取待采集公众号名单 |
| `--write-mysql` | 采集结果写入 MySQL |
| `--metrics share` | 仅识别转发数（更快）；`all` 为全部互动指标 |
| `--window-layout auto` | 自动适配标准/自定义标签栏 |
| `--max-articles 20` | 每账号最多读取 20 篇文章卡片 |

**方式三：命令行直接调用**

```powershell
# 从 MySQL 读账号名单并入库采集
.\.venv\Scripts\python.exe .\wechat_visual_rpa.py `
  --run-search-accounts --live --accounts-from-mysql --write-mysql --max-articles 20

# 只采集指定公众号
.\.venv\Scripts\python.exe .\wechat_visual_rpa.py `
  --run-search-accounts --live --account-name "南京发布" --max-articles 5

# 只截图识别、不操作鼠标、不写库（调试用）
.\.venv\Scripts\python.exe .\wechat_visual_rpa.py
```

### 采集逻辑

完整流程：

1. **读取名单**：从 `weixin.collection_target` 读取待采集公众号（也可用 `--account-name` 指定单个）。
2. **定位账号**：在微信"搜一搜"输入账号名 → 选一级分类"账号"、二级分类"公众号" → 本地 OCR 找到同名账号卡片（要求"公众号 / 服务号 / 篇原创内容"等证据防误点）→ 打开独立资料窗口。账号名与微信实际名不同时用 `config/account_aliases.json` 配置别名。
3. **读取文章列表**：按时间分组读取文章卡片，向下滚动至扫描范围边界（今天 / 昨天 / 今天和昨天），自动跳过置顶、历史内容和招聘等推广卡片。
4. **打开文章**：逐篇打开文章，复制链接解析出真实的标题、公众号、发布时间与纯文本正文（图片不写入正文）。
5. **读取互动数**：校验浏览器标签标题、正文标题、URL 与互动栏属于同一篇文章后，读取转发数（或全部互动指标）。互动栏优先 OpenCV 模板匹配 + RapidOCR 本地识别，不确定时由 Qwen-VL 视觉模型兜底。
6. **去重写入**：两层保守去重（卡片层：时间+标题+阅读数+点赞数全同才跳过；链接层：URL 与本次已成功文章相同立即关闭）。写入时以 `url_normalized` 为唯一键幂等入库：首次插入全文，再次采集只补空字段并追加互动历史到 `article_interaction_history`。正文为空不入库。
7. **收尾**：文章完成关闭文章标签，账号完成关闭资料窗口，保留搜一搜主窗口。操作间隔按 `.env` 中 `RPA_CLICK_INTERVAL_SECONDS` 等配置随机化，防止触发风控。

**桌面前置条件**（这是桌面视觉采集，不是 HTTP 爬虫）：

- 微信已登录，"搜一搜"窗口已打开；
- 采集期间不锁屏、不休眠、不动鼠标键盘、不改分辨率；
- 推荐分辨率 `2560×1440` / 缩放 `100%`（`1920×1080` / `100%` 也可用）；
- 远程维护用 Hyper-V/VMware 控制台或 Parsec/AnyDesk，避免 RDP 断连导致分辨率变化。

## 推送服务

第三方推送程序 `push/local-information-reporter.jar`（Spring Boot），负责把新采集的文章上报到远端平台。

### 运行 jar 的实际命令

启动脚本 `push\start-push-reporter.ps1` 中执行的命令：

```powershell
java -Dfile.encoding=UTF-8 -jar `
  -Xms256m -Xmx1024m `
  -XX:MetaspaceSize=256m -XX:MaxMetaspaceSize=1024m `
  -Dspring.profiles.active=test `
  local-information-reporter.jar
```

| 参数 | 含义 |
|---|---|
| `-Dfile.encoding=UTF-8` | **关键参数**。jar 的加密代码用了依赖 JVM 默认编码的 `String.getBytes()`，Windows 中文系统默认 GBK，不加此参数推送的中文会变成乱码（实测远端 insert 全为 0）。原程序为 Linux 编写（默认 UTF-8），在 Windows 上必须显式指定 |
| `-Xms256m -Xmx1024m` | 堆内存 256MB 起步、上限 1GB |
| `-XX:MetaspaceSize=256m -XX:MaxMetaspaceSize=1024m` | 元空间 256MB 起步、上限 1GB |
| `-Dspring.profiles.active=test` | 使用 test 配置（连本机 MySQL `127.0.0.1:3306/weixin`） |

手动启动 / 停止：

```powershell
# 手动启动（推荐，自带防重复、等 MySQL、日志轮转逻辑）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\mynj\wechat-article-rpa\push\start-push-reporter.ps1"

# 停止推送程序
Stop-Process -Name java -Force
```

### 开机自启（计划任务）

已注册 Windows 计划任务 `wechat-push-reporter`：

- **触发**：开机启动，延迟 60 秒（等 MySQL 服务就绪）；
- **动作**：`powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "D:\mynj\wechat-article-rpa\push\start-push-reporter.ps1"`；
- **失败重试**：每 5 分钟重试，最多 3 次；
- 启动脚本自带**防重复启动**（检测 18080 端口是否已被 java 监听）和 **MySQL 就绪等待**（最多 90 秒）。

管理命令：

```powershell
# 查看任务状态
Get-ScheduledTask -TaskName "wechat-push-reporter"

# 手动启动一次
Start-ScheduledTask -TaskName "wechat-push-reporter"

# 取消开机自启
Unregister-ScheduledTask -TaskName "wechat-push-reporter" -Confirm:$false

# 重新注册（在项目根目录执行）
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "D:\mynj\wechat-article-rpa\push\start-push-reporter.ps1"'
$trigger = New-ScheduledTaskTrigger -AtStartup; $trigger.Delay = "PT60S"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "wechat-push-reporter" -Action $action -Trigger $trigger -Settings $settings -Force
```

### 日志保存与轮转

**日志位置**：`push\app.log`（与 jar 同目录）

| 文件 | 内容 |
|---|---|
| `push\app.log` | 主日志：推送记录、SQL、服务端响应 |
| `push\app-err.log` | 错误输出（正常为空） |
| `push\logs\` | jar 自带的运行日志目录 |

**轮转规则**（由启动脚本在每次启动前检查执行）：

1. `app.log` 超过 **50MB** → 改名归档为 `app-<时间戳>.log`（如 `app-20261112-163349.log`），主日志从头开始写；
2. 归档**只保留最近 2 份**，更旧的自动删除（按文件名时间戳排序，最旧的先删）；
3. 磁盘占用上限约 **150MB**，不会无限增长。

查看实时日志：

```powershell
Get-Content "D:\mynj\wechat-article-rpa\push\app.log" -Tail 50 -Wait
```

### 推送工作原理

- **触发**：jar 内置定时任务，cron `0 0/10 * * * ?`，**每 10 分钟**执行一次；
- **筛选**：`SELECT ... FROM article WHERE sync_flag IS NULL ORDER BY publish_date DESC LIMIT 100`，每批 100 条；
- **上报**：JSON 序列化 → SM4 加密（密钥在 jar 内 `application.yml`，IV `0123456789123456`）→ HTTP POST 到 `https://m.mynj.cn:11005/renren/local_information_monitor/information/report`；
- **回写**：推送成功后 `UPDATE article SET sync_flag = 1 WHERE id IN (...)`；
- **状态字段**：`sync_flag` 由推送服务独占维护——`NULL` 未推送，`1` 已推送。RPA 采集程序的 INSERT/UPDATE 均为显式列名，不触碰此字段，两边互不干扰；
- **重推方法**：`UPDATE article SET sync_flag = NULL;` 然后等下一轮定时任务（远端按 `articleUrl` 幂等去重）。

## MySQL 数据库

本机原生安装的 MySQL 8.0（服务名 `MySQL80`），数据目录 `D:\MySQL\MySQL Server 8.0\Data\`。

| 配置项 | 值 |
|---|---|
| 主机 / 端口 | `127.0.0.1:3306` |
| 数据库 | `weixin` |
| 核心表 | `article`、`collection_target`、`article_interaction_history`、`collection_runs`、`daily_report` |

表结构、字段含义、索引与备份恢复方法见 `docs/DATABASE.md`。

`article` 表中与推送相关的字段：

| 字段 | 说明 |
|---|---|
| `url_normalized` | 规范化文章链接，唯一键，幂等去重用 |
| `sync_flag` | 推送状态标识：`NULL`=待推送，`1`=已推送（由推送服务维护） |

## 管理控制台

| 页面 | 用途 |
|---|---|
| `/` | 手动采集、定时计划、启动前检查、运行进度、日志 |
| `/accounts.html` | 公众号查询、筛选、搜索别名编辑、导入导出 |
| `/articles.html` | 文章查询、正文查看、CSV/JSON 导出 |

- 登录：HTTP Basic Auth，账号密码在 `.env` 的 `CONTROL_PANEL_USERNAME` / `CONTROL_PANEL_PASSWORD`；
- 定时采集：控制台保存后立即生效，配置在 `config\control_panel.json`；定时器依赖控制台进程常驻；
- 局域网访问：`.\.venv\Scripts\python.exe .\rpa_control_panel.py --host 0.0.0.0 --port 8010`，配合防火墙限制内网网段；**不要暴露到公网**。

## 配置项与数据目录

| 路径 / 变量 | 用途 |
|---|---|
| `.env` | 本机配置（不入 Git）：MySQL、控制台账号、Qwen-VL、RPA 节奏 |
| `config/control_panel.json` | 定时任务、扫描范围、指标、每账号上限 |
| `config/account_aliases.json` | MySQL 账号名与微信搜索名的映射 |
| `output/<run-id>/` | 单次采集的日志、截图、JSONL、CSV |
| `push/app.log` | 推送服务主日志（50MB 自动轮转，保留 2 份归档） |
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | MySQL 连接配置 |
| `CONTROL_PANEL_USERNAME` / `CONTROL_PANEL_PASSWORD` | 控制台登录账号 |
| `QWEN_VL_BASE_URL` / `QWEN_VL_API_KEY` / `QWEN_VL_MODEL` | OCR 兜底视觉模型 |
| `RPA_CLICK_INTERVAL_SECONDS` 等 | 采集操作节奏（区间随机，防风控） |

## 运维命令速查

```powershell
# ── 推送服务 ──────────────────────────────
Get-ScheduledTask -TaskName "wechat-push-reporter"   # 查看自启任务
Start-ScheduledTask -TaskName "wechat-push-reporter"  # 手动拉起
Stop-Process -Name java -Force                        # 停止推送程序
Get-Content .\push\app.log -Tail 50 -Wait             # 实时看推送日志

# ── MySQL ────────────────────────────────
& "D:\MySQL\MySQL Server 8.0\bin\mysql.exe" -h 127.0.0.1 -P 3306 -u root -p -D weixin

# 查看推送进度
SELECT sync_flag, COUNT(*) FROM article GROUP BY sync_flag;

# 重推全部文章
UPDATE article SET sync_flag = NULL;

# ── 采集 ─────────────────────────────────
.\start-control-panel.bat          # 启动控制台
.\start-rpa.bat                    # 一键采集（MySQL 名单 → 入库）
```

## 常见问题

### 推送的中文在远端是乱码

启动 jar 必须带 `-Dfile.encoding=UTF-8`（启动脚本已内置）。该 jar 的加密代码用了依赖 JVM 默认编码的写法，Windows 中文系统默认 GBK，不带此参数推送的密文就是 GBK 字节，远端按 UTF-8 解出乱码且 insert 计数为 0。判断方法：看日志中服务端响应的 insert 计数，全为 0 即中招。

### 推送日志显示成功但远端没数据

先确认不是上一条的乱码问题（乱码时接口返回"成功"但 insert 为 0）。确认方法：`SELECT sync_flag, COUNT(*) FROM article GROUP BY sync_flag;` 看 NULL 是否清零，再看日志里每批响应的 insert/update 计数是否大于 0。

### 采集时提示"未找到搜一搜顶部搜索框"

确认微信已登录且"搜一搜"窗口存在、未最小化。控制台的"重新检测 / 自动恢复"会尝试拉起；仍失败则手工在微信顶部搜索框输入"搜一搜"点击候选项后重试。

### 文章没有写入 MySQL

检查命令是否含 `--write-mysql`、MySQL 服务是否运行、正文是否为空（空正文不入库）、`output/<run-id>/run.log` 是否有校验失败记录。

### 为什么同一篇文章会被打开多次

安全校验的一部分：互动数识别前后各复制一次 URL，两次相同才确认互动数与正文属于同一文章。失败文章有限次重试；成功 URL 在当前任务内去重。

## 运行安全提示

- 不要把控制台端口暴露到公网；局域网开放前必须改强密码。
- 不要在采集过程中人工操作微信、鼠标或键盘。
- 不要在两台机器上同时运行同一微信账号的批量采集。
- `.env` 含数据库密码，不入 Git；更新代码前先提交代码、再单独备份配置与输出目录。
