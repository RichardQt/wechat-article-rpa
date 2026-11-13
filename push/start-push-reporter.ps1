# local-information-reporter 启动脚本
# 由计划任务 wechat-push-reporter 在开机时调用（也可手动运行）。
# 关键点：必须带 -Dfile.encoding=UTF-8，否则 Windows 默认 GBK 导致推送中文乱码。

$ErrorActionPreference = "Stop"
$jarDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$jarPath = Join-Path $jarDir "local-information-reporter.jar"
$logPath = Join-Path $jarDir "app.log"
$errLogPath = Join-Path $jarDir "app-err.log"
$LOG_MAX_BYTES = 50MB

if (-not (Test-Path $jarPath)) {
    Write-Error "找不到 jar 文件: $jarPath"
    exit 1
}

# 防重复启动：检查 18080 端口是否已被本程序监听
$existing = Get-NetTCPConnection -LocalPort 18080 -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.OwningProcess -and (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName -eq "java" }
if ($existing) {
    Write-Output "推送程序已在运行 (PID: $($existing[0].OwningProcess))，跳过启动。"
    exit 0
}

# 日志轮转：超过 50MB 时，旧日志改名加时间戳归档，当前日志从头开始写。
# 归档保留最近 2 份，更早的自动删除，避免磁盘占满。
if (Test-Path $logPath) {
    $logItem = Get-Item $logPath
    if ($logItem.Length -gt $LOG_MAX_BYTES) {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $archived = Join-Path $jarDir "app-$stamp.log"
        Move-Item $logPath $archived -Force
        # 清理超过 2 份的历史归档（按文件名时间戳，最旧的先删）
        Get-ChildItem $jarDir -Filter "app-*.log" | Sort-Object Name -Descending |
            Select-Object -Skip 2 | ForEach-Object {
                try { Remove-Item $_.FullName -Force -ErrorAction Stop } catch { Write-Warning "删除旧归档失败: $($_.FullName)" }
            }
    }
}

# 等待本机 MySQL 就绪（最多 90 秒），jar 启动时需要连库
$mysqlReady = $false
for ($i = 0; $i -lt 30; $i++) {
    $conn = Test-NetConnection -ComputerName 127.0.0.1 -Port 3306 -WarningAction SilentlyContinue
    if ($conn.TcpTestSucceeded) { $mysqlReady = $true; break }
    Start-Sleep -Seconds 3
}
if (-not $mysqlReady) {
    Write-Warning "等待 MySQL 3306 超时，仍尝试启动 jar（Druid 连接池会自行重试）。"
}

# 启动 jar：UTF-8 编码，日志追加写入 app.log
$javaArgs = @(
    "-Dfile.encoding=UTF-8"
    "-jar"
    "-Xms256m"
    "-Xmx1024m"
    "-XX:MetaspaceSize=256m"
    "-XX:MaxMetaspaceSize=1024m"
    "-Dspring.profiles.active=test"
    $jarPath
)

Start-Process -FilePath "java" -ArgumentList $javaArgs `
    -WorkingDirectory $jarDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $logPath -RedirectStandardError $errLogPath

Write-Output "推送程序已启动，日志: $logPath"
