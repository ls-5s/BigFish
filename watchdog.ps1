# QQBot watchdog v2: process-aware, lock-protected.
$ErrorActionPreference = "Continue"
$log = "D:\QQBot\logs\watchdog.log"
$lock = "D:\QQBot\logs\watchdog.lock"

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $log -Value $line -Encoding UTF8
}

function Test-Port($port) {
    try { return [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction Stop) }
    catch { return $false }
}

function Get-Proc {
    param($name, $pathLike)
    Get-Process -Name $name -ErrorAction SilentlyContinue | Where-Object {
        -not $pathLike -or ($_.Path -like $pathLike)
    }
}

# single instance lock
if (Test-Path $lock) {
    $age = (Get-Date) - (Get-Item $lock).LastWriteTime
    if ($age.TotalMinutes -lt 3) { exit 0 }
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType File -Path $lock -Force | Out-Null

try {
    $ports = "3000=$(Test-Port 3000) 5099=$(Test-Port 5099) 6185=$(Test-Port 6185) 6199=$(Test-Port 6199) 11434=$(Test-Port 11434)"
    Write-Log "tick $ports"

    # SnowLuma
    if (-not (Test-Port 3000)) {
        $proc = Get-Proc node "*SnowLuma*"
        if ($proc) {
            Start-Sleep -Seconds 20
            if (-not (Test-Port 3000)) {
                Write-Log "SnowLuma process alive but port down, killing"
                $proc | Stop-Process -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 2
            }
        }
        if (-not (Test-Port 3000)) {
            Write-Log "SnowLuma down, restarting"
            $env:SNOWLUMA_ACCEPT_EULA = "1"
            $env:SNOWLUMA_ACCEPT_PRIVACY = "1"
            $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
            Start-Process -FilePath "D:\QQBot\SnowLuma\node.exe" -ArgumentList "index.mjs" `
                -WorkingDirectory "D:\QQBot\SnowLuma" -WindowStyle Hidden `
                -RedirectStandardOutput "D:\QQBot\logs\snowluma-$stamp.log" `
                -RedirectStandardError "D:\QQBot\logs\snowluma-$stamp.err.log"
            Start-Sleep -Seconds 10
            Write-Log "SnowLuma started: $(Test-Port 3000)"
        }
    }

    # Ollama
    $ollamaOk = $false
    try {
        $o = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
        $ollamaOk = ($null -ne $o.models)
    } catch { $ollamaOk = $false }
    if (-not $ollamaOk) {
        Write-Log "Ollama down, starting"
        if (Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe") {
            Start-Process -FilePath "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
            Start-Sleep -Seconds 8
        }
    }

    # AstrBot
    if (-not (Test-Port 6185)) {
        $proc = Get-Proc astrbot
        if ($proc) {
            Start-Sleep -Seconds 30
            if (-not (Test-Port 6185)) {
                Write-Log "AstrBot process alive but port down, killing"
                $proc | Stop-Process -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 2
            }
        }
        if (-not (Test-Port 6185)) {
            Write-Log "AstrBot down, restarting"
            $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
            Start-Process -FilePath "$env:USERPROFILE\.local\bin\astrbot.exe" -ArgumentList "run" `
                -WorkingDirectory "D:\QQBot\AstrBot" -WindowStyle Hidden `
                -RedirectStandardOutput "D:\QQBot\logs\astrbot-$stamp.log" `
                -RedirectStandardError "D:\QQBot\logs\astrbot-$stamp.err.log"
            Start-Sleep -Seconds 15
            Write-Log "AstrBot started: $(Test-Port 6185)"
        }
    }
} finally {
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
