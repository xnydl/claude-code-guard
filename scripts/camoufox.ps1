$ErrorActionPreference = "Stop"
# Legacy filename only; never start Camoufox or the default browser.
& (Join-Path $PSScriptRoot "fingerprint-chromium.ps1") @args
exit $LASTEXITCODE
