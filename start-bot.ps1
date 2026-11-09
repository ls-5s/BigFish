# Start AstrBot + SnowLuma (QQ must be logged in separately)
$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force -Path "D:\QQBot\logs" | Out-Null

Write-Host "[0/3] Ensuring Ollama (memory embeddings) ..."
$ollamaOk = $false
try { $ollamaOk = (Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3 -UseBasicParsing).StatusCode -eq 200 } catch { $ollamaOk = $false }
if (-not $ollamaOk -and (Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe")) {
    Start-Process -FilePath "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
    Start-Sleep -Seconds 5
}
Write-Host "[1/3] Starting AstrBot ..."
$astrExe = Join-Path $env:USERPROFILE ".local\bin\astrbot.exe"
$astrLog = "D:\QQBot\logs\astrbot-$stamp.log"
Start-Process -FilePath $astrExe -ArgumentList "run" -WorkingDirectory "D:\QQBot\AstrBot" -WindowStyle Hidden -RedirectStandardOutput $astrLog -RedirectStandardError "$astrLog.err"
Start-Sleep -Seconds 6

Write-Host "[2/3] Starting SnowLuma ..."
$env:SNOWLUMA_ACCEPT_EULA = "1"
$env:SNOWLUMA_ACCEPT_PRIVACY = "1"
$snowLog = "D:\QQBot\logs\snowluma-$stamp.log"
Start-Process -FilePath "D:\QQBot\SnowLuma\node.exe" -ArgumentList "index.mjs" -WorkingDirectory "D:\QQBot\SnowLuma" -WindowStyle Hidden -RedirectStandardOutput $snowLog -RedirectStandardError "$snowLog.err"

Write-Host ""
Write-Host "AstrBot  : http://127.0.0.1:6185"
Write-Host "SnowLuma : http://127.0.0.1:5099"
Write-Host "Logs     : $astrLog"
Write-Host "           $snowLog"
Write-Host "Make sure QQ is logged in as 1138563945."
