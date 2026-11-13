# 部署与启动

把采集器装到另一台 Windows 电脑时，拷源码和配置，不要拷本机环境。`.venv` 里写的是创建电脑的绝对路径，复制过去无法使用。

新电脑不需要预装 Python。`setup-env.bat` 会把 `uv` 装到项目的 `.tools`，再安装 64 位 Python 3.10、创建 `.venv`，并用清华镜像安装 `requirements.txt`。需要 3.11 或 3.12 时，安装前设置 `RPA_PYTHON_VERSION`。

## 1. 在当前电脑打包

在 PowerShell 中执行。压缩包生成在 `D:\mynj\wechat-article-rpa-deploy.zip`。

```powershell
$dest = "D:\mynj\wechat-article-rpa-deploy.zip"
$stageParent = Join-Path $env:TEMP "wechat-rpa-pack"
$stage = Join-Path $stageParent "wechat-article-rpa"
if (Test-Path $stageParent) { Remove-Item $stageParent -Recurse -Force }
if (Test-Path $dest) { Remove-Item $dest -Force }
New-Item -ItemType Directory -Path $stage -Force | Out-Null

robocopy "D:\mynj\wechat-article-rpa" $stage /E `
  /XD .venv .tools output __pycache__ .git `
  /XF .env .env.mongo ui_position_cache.json run_history.json *.pyc `
  /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { throw "robocopy failed: $LASTEXITCODE" }

Compress-Archive -Path $stage -DestinationPath $dest
Remove-Item $stageParent -Recurse -Force
Write-Host "Created $dest"
```

`robocopy` 的退出码 0 到 7 都表示复制完成。

新电脑能访问 Git 仓库时，也可以不打包，直接克隆后再从第 3 步安装：

```powershell
git clone git@github.com:Dhaizei/wechat-article-rpa.git
cd .\wechat-article-rpa
```

克隆不会带上本机的 `.env`。别名和定时计划如果存在，仍要单独拷贝，见下一节。

## 2. 配置文件

程序启动时读取项目根目录的 `.env`。系统环境变量优先于文件里的同名项。`.env` 不要放进对外流转的压缩包；安装脚本发现没有 `.env` 时，会用 `.env.example` 复制一份。

### 必须准备：`.env`

两台电脑连同一个库时，把当前电脑的 `.env` 单独拷到新电脑项目根目录，覆盖安装脚本生成的那份。没有现成文件时，编辑新生成的 `.env`，至少核对：

| 变量 | 作用 |
|---|---|
| `MYSQL_HOST` | MySQL 数据库主机，默认 `127.0.0.1` |
| `MYSQL_PORT` | MySQL 端口，默认 `3306` |
| `MYSQL_USER` | MySQL 用户名，默认 `root` |
| `MYSQL_PASSWORD` | MySQL 密码，默认 `123456` |
| `MYSQL_DATABASE` | MySQL 数据库名，默认 `weixin` |
| `CONTROL_PANEL_USERNAME` | 控制台用户名，模板是 `admin` |
| `CONTROL_PANEL_PASSWORD` | 控制台密码。模板是 `admin-123`，给局域网别人访问前要改掉 |
| `QWEN_VL_BASE_URL` | 视觉模型地址。模板是 `http://192.168.33.27/v1` |
| `QWEN_VL_API_KEY` | 视觉模型密钥。留空时仍可用本地 OCR，失败后不再调用视觉模型 |
| `QWEN_VL_MODEL` | 模板是 `dashscope/qwen3-vl-plus` |

公众号名单在 MySQL 的 `collection_target` 表，不在配置文件里。没有 `.env` 时，代码默认连本地 MySQL `127.0.0.1:3306` 的 `weixin` 数据库。兼容历史 MongoDB 的配置项为 `MONGO_URI`（历史 MongoDB 代码已完整备份在 `backup_mongodb/` 目录中）。

操作节奏可以不填，下表是默认值。写法是「最少-最多」秒，每次在区间内随机取值。调小会更快，但更容易触发微信风控。

| 变量 | 作用 |
|---|---|
| `RPA_CLICK_INTERVAL_SECONDS` | 两次鼠标点击之间的最短间隔，默认 `0.8-1.5` |
| `RPA_ARTICLE_PAUSE_SECONDS` | 打开下一篇文章前的停顿，默认 `3-6` |
| `RPA_ACCOUNT_PAUSE_SECONDS` | 切换到下一个公众号前的停顿，默认 `8-15` |

### 用到才拷

| 文件 | 什么时候要 |
|---|---|
| `config/account_aliases.json` | 数据库里的名字和微信搜一搜显示名不一致。格式见 `config/account_aliases.example.json` |
| `config/control_panel.json` | 控制台里保存过定时计划。没有就在新电脑上重新保存 |
| `config/accounts.txt` | 只有改用本地名单、不从 MySQL 读账号时才用。`start-rpa.bat` 不读这个文件 |
| `.env.mongo` | 只在新电脑用 `mongodb.bat` 另起一套 Docker MongoDB 时需要。采集器不读这个文件，把 `.\mongodb.bat connection` 打印的 `MONGO_URI` 写入 `.env` |

### 不要拷

| 文件 | 原因 |
|---|---|
| `.venv`、`.tools` | 本机环境，换电脑要重新安装 |
| `output` | 日志、截图和当次采集结果 |
| `config/ui_position_cache.json` | 这台屏幕上的点击坐标，换电脑会点错 |
| `config/run_history.json` | 本机运行记录，不影响采集 |

## 3. 在新电脑安装

1. 解压到不含空格和特殊符号的路径，例如 `D:\wechat-article-rpa`。
2. 确认能访问 `https://pypi.tuna.tsinghua.edu.cn/simple` 和 `https://astral.sh`。前者安装依赖，后者下载 `uv`。
3. 双击 `setup-env.bat`，直到窗口提示安装完成。
4. 按上一节放好或改好 `.env`。
5. 确认能连上数据库。下面命令里 `TcpTestSucceeded : True` 表示端口通：

```powershell
Test-NetConnection 127.0.0.1 -Port 3306
```

地址和端口按 `.env` 里的 `MYSQL_HOST` 与 `MYSQL_PORT` 修改。

## 4. 启动前的桌面条件

这是微信窗口上的视觉采集，需要一台已登录、未锁屏的 Windows 桌面。

1. 安装并登录微信 Windows 客户端，打开「搜一搜」。
2. 推荐分辨率 `2560×1440` 或 `1920×1080`，缩放 `100%`。
3. 采集过程中不要动鼠标和键盘，不要锁屏、休眠、注销，也不要改变分辨率。
4. 同一微信账号不要在两台电脑上同时采集。先停掉旧电脑上的控制台和 `start-rpa.bat`，再在新电脑启动。

## 5. 启动

### 管理控制台

双击 `start-control-panel.bat`。浏览器打开：

```text
http://127.0.0.1:8010/
```

用 `.env` 里的用户名和密码登录。在页面上选择扫描范围、指标和每账号上限，再点「立即开始」。定时计划保存在 `config/control_panel.json`，控制台进程要一直开着才会到点执行。

默认监听 `0.0.0.0:8010`。只在可信局域网使用，并先改掉 `CONTROL_PANEL_PASSWORD`。不要把 8010 映射到公网。

### 直接采集

双击 `start-rpa.bat`。它会：

- 从 `weixin.collection_target` 读取全部公众号；
- 采集今天和昨天的文章，每个账号最多 20 篇；
- 只识别转发数；
- 写入 `weixin.article`；
- 把日志、截图、JSONL 和 CSV 放到 `output\mysql-时间戳\`。

停止时在运行窗口按 `Ctrl+C`。

### 推送服务（可选）

若新电脑也要承担文章推送（把 `weixin.article` 中 `sync_flag IS NULL` 的文章上报远端），需要单独部署：

1. 新电脑需要 Java 8（命令行 `java -version` 可用）；
2. 拷贝 `push\local-information-reporter.jar` 和 `push\start-push-reporter.ps1`（打包脚本默认会带上 `push` 目录）；
3. 注册开机自启计划任务（在项目根目录 PowerShell 执行）：

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PWD\push\start-push-reporter.ps1`""
$trigger = New-ScheduledTaskTrigger -AtStartup; $trigger.Delay = "PT60S"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "wechat-push-reporter" -Action $action -Trigger $trigger -Settings $settings -Force
```

4. 立即启动一次并验证：`Start-ScheduledTask -TaskName "wechat-push-reporter"`，然后看 `push\app.log` 出现「服务启动成功」。

注意两点：

- **启动脚本必须带 `-Dfile.encoding=UTF-8`**（脚本已内置）。jar 的加密代码依赖 JVM 默认编码，Windows 中文系统默认 GBK，缺了它推送的中文会乱码、远端 insert 全为 0；
- **同一时间只有一台电脑跑推送服务**。两台同时推会导致 `sync_flag` 状态互相覆盖、远端重复推送。迁移时先在旧电脑执行 `Stop-Process -Name java -Force` 和 `Unregister-ScheduledTask -TaskName "wechat-push-reporter" -Confirm:$false`。

推送服务详细说明（工作原理、日志轮转、重推方法）见 `README.md` 的「推送服务」章节。

## 6. 安装或采集失败时看哪里

| 现象 | 先看 |
|---|---|
| `setup-env.bat` 失败 | 能否打开清华 PyPI 和 `https://astral.sh`；路径里是否有特殊符号 |
| 控制台打不开或密码不对 | 项目根目录 `.env` 是否存在，`CONTROL_PANEL_PASSWORD` 是否已改 |
| 读不到公众号或文章没入库 | `MYSQL_*` 配置是否能连通（`Test-NetConnection 127.0.0.1 -Port 3306`）；`output\mysql-时间戳\run.log` |
| 推送服务没起来 | 计划任务 `wechat-push-reporter` 是否注册；`push\app.log` 和 `push\app-err.log`；`java -version` 是否可用 |
| 推送成功但远端中文乱码 | 启动是否漏了 `-Dfile.encoding=UTF-8`（用 `push\start-push-reporter.ps1` 启动则不会漏）；日志里服务端响应 insert 是否全为 0 |
| 找不到搜一搜 | 微信已登录，搜一搜窗口没有最小化 |
| 点错位置、识别飘 | 缩放是否为 100%；不要使用从旧电脑拷来的 `config/ui_position_cache.json` |
