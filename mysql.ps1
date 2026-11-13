param(
    [ValidateSet("setup", "start", "stop", "restart", "status", "logs", "connection", "backup", "restore")]
    [string]$Action = "status",
    [string]$BackupFile = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$composeFile = Join-Path $PSScriptRoot "compose.yaml"
$envFile = Join-Path $PSScriptRoot ".env"
$containerName = "wechat-article-mysql"

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker was not found. Install and start Docker Desktop first."
    }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Engine is unavailable. Start Docker Desktop and retry."
    }
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & docker compose -f $composeFile @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose failed: $($Arguments -join ' ')"
    }
}

function Wait-MysqlHealthy {
    for ($index = 1; $index -le 30; $index++) {
        $status = (& docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" $containerName 2>$null)
        if ($status -eq "healthy") {
            Write-Host "MySQL is healthy." -ForegroundColor Green
            return
        }
        if ($status -eq "unhealthy" -or $status -eq "exited") {
            throw "MySQL container became unhealthy ($status). Check logs: .\mysql.bat logs"
        }
        Start-Sleep -Seconds 2
    }
    throw "Timed out waiting for MySQL container health check."
}

function Show-Status {
    Assert-Docker
    & docker compose -f $composeFile ps mysql
}

function Backup-Mysql {
    Assert-Docker
    $backupDirectory = Join-Path $PSScriptRoot "output\mysql-backups"
    if (-not (Test-Path $backupDirectory)) {
        New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
    }
    $fileName = "weixin-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".sql"
    $localFile = Join-Path $backupDirectory $fileName
    $arguments = @(
        "exec", $containerName, "mysqldump",
        "-uroot", "-p123456",
        "--default-character-set=utf8mb4",
        "weixin"
    )
    & docker @arguments > $localFile
    if ($LASTEXITCODE -ne 0) { throw "mysqldump failed." }
    Write-Host "MySQL backup created: $localFile" -ForegroundColor Green
}

function Restore-Mysql {
    Assert-Docker
    if (-not $Force) {
        throw "Restore overwrites matching tables. Retry with -Force after verification."
    }
    if (-not $BackupFile) { throw "Restore requires -BackupFile." }
    $resolvedBackup = (Resolve-Path -LiteralPath $BackupFile).Path
    $containerFile = "/tmp/restore.sql"
    & docker cp $resolvedBackup ($containerName + ":" + $containerFile)
    if ($LASTEXITCODE -ne 0) { throw "Could not copy the backup into the container." }
    & docker exec -i $containerName mysql -uroot -p123456 weixin -e "source $containerFile;"
    if ($LASTEXITCODE -ne 0) { throw "mysql restore failed." }
    & docker exec $containerName rm -f $containerFile
    Write-Host "MySQL restored successfully from: $resolvedBackup" -ForegroundColor Green
}

switch ($Action) {
    "start" {
        Assert-Docker
        Invoke-Compose up -d mysql
        Wait-MysqlHealthy
    }
    "stop" {
        Assert-Docker
        Invoke-Compose stop mysql
        Write-Host "MySQL stopped. The data volume was preserved." -ForegroundColor Green
    }
    "restart" {
        Assert-Docker
        Invoke-Compose restart mysql
        Wait-MysqlHealthy
    }
    "status" {
        Show-Status
    }
    "logs" {
        Assert-Docker
        Invoke-Compose logs --tail 150 mysql
    }
    "connection" {
        Write-Host "MYSQL_HOST=127.0.0.1"
        Write-Host "MYSQL_PORT=3306"
        Write-Host "MYSQL_DATABASE=weixin"
        Write-Host "MYSQL_USER=root"
        Write-Host "MYSQL_PASSWORD=123456"
    }
    "backup" {
        Backup-Mysql
    }
    "restore" {
        Restore-Mysql
    }
}
