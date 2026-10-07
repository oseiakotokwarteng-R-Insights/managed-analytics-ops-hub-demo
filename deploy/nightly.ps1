# The nightly job: advance the live clock to today's simulated date (catching up on any missed days), then publish.
# Scheduled once a day by Task Scheduler (see docs/PUBLISHING.md). Output goes to warehouse\nightly.log.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$log = "warehouse\nightly.log"
"=== $(Get-Date -Format s) ===" | Out-File -Append $log
& .\.venv\Scripts\python.exe -m pipeline.live tick --catch-up 2>&1 | Out-File -Append $log
if ($LASTEXITCODE) { "tick failed" | Out-File -Append $log; exit 1 }
& .\deploy\deploy_demo.ps1 2>&1 | Out-File -Append $log
if ($LASTEXITCODE) { "deploy failed" | Out-File -Append $log; exit 1 }
"ok" | Out-File -Append $log
