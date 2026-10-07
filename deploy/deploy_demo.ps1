# Builds the public bundle and uploads it to Cloudflare, then checks the live site serves exactly what was built.
# Needs: the project's .venv, Node.js, and a Cloudflare login (`npx wrangler login` once, or CLOUDFLARE_API_TOKEN in the environment).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$py = ".\.venv\Scripts\python.exe"
& $py -m pipeline.package --indexable
if ($LASTEXITCODE) { throw "packaging failed" }
npx --yes wrangler@latest deploy --config deploy/wrangler.jsonc
if ($LASTEXITCODE) { throw "deploy failed" }
$cfg = Get-Content dashboard\config.json | ConvertFrom-Json
$local = (Get-Content dist\public\manifest.json | ConvertFrom-Json).fingerprint
$live = (Invoke-RestMethod ($cfg.site_url.TrimEnd('/') + "/manifest.json")).fingerprint
if ($local -ne $live) { throw "live site serves fingerprint $live, expected $local" }
Write-Host "live site matches the bundle ($local)"
