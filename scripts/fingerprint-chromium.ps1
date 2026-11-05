$ErrorActionPreference = "Stop"
$python = if ($env:CLAUDE_GUARD_PYTHON) { $env:CLAUDE_GUARD_PYTHON } else { "python" }
# No default-browser fallback: ccg_browser reports unsupported platforms until
# an equivalent guarded Chromium IPC adapter has been deployed and validated.
& $python (Join-Path $PSScriptRoot "ccg_browser.py") @args
exit $LASTEXITCODE
