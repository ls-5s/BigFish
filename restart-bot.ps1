# Safe restart: AstrBot first, then SnowLuma (avoids stale reverse-WS hang).
$ErrorActionPreference = "Continue"
$ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

Write-Host "[1/3] stop AstrBot + SnowLuma"
Get-Process astrbot -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process node -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*SnowLuma*" } | Stop-Process -Force
Start-Sleep -Seconds 3

# make sure 3000 is free; kill leftovers
for ($i = 0; $i -lt 10; $i++) {
    $c = Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue
    if (-not $c) { break }
    $c | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
}
Write-Host "free port 3000: $(-not [bool](Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue))"

Write-Host "[2/3] start AstrBot"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$astrLog = "D:\QQBot\logs\astrbot-$stamp.log"
Start-Process -FilePath "$env:USERPROFILE\.local\bin\astrbot.exe" -ArgumentList "run" `
    -WorkingDirectory "D:\QQBot\AstrBot" -WindowStyle Hidden `
    -RedirectStandardOutput $astrLog -RedirectStandardError "$astrLog.err"
Start-Sleep -Seconds 18

Write-Host "[3/3] start SnowLuma"
$env:SNOWLUMA_ACCEPT_EULA = "1"
$env:SNOWLUMA_ACCEPT_PRIVACY = "1"
$snowLog = "D:\QQBot\logs\snowluma-$stamp.log"
Start-Process -FilePath "D:\QQBot\SnowLuma\node.exe" -ArgumentList "index.mjs" `
    -WorkingDirectory "D:\QQBot\SnowLuma" -WindowStyle Hidden `
    -RedirectStandardOutput $snowLog -RedirectStandardError "$snowLog.err"

Write-Host "done. AstrBot: $astrLog  SnowLuma: $snowLog"
