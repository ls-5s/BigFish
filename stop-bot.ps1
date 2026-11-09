# Stop AstrBot + SnowLuma
$ErrorActionPreference = "SilentlyContinue"
Get-Process -Name astrbot -ErrorAction SilentlyContinue | Stop-Process -Force
Get-NetTCPConnection -LocalPort 5099,3000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
Write-Host "Stopped. QQ is left running."
