$ErrorActionPreference = "Stop"
$guardDir = Join-Path $HOME ".claude-guard"
$python = if ($env:CLAUDE_GUARD_PYTHON) { $env:CLAUDE_GUARD_PYTHON } else { "python" }
& $python (Join-Path $guardDir "ccg_guard.py") --fast
if ($LASTEXITCODE -ne 0) { throw "Claude 网络保护：启动前验证失败。" }
$state = Get-Content (Join-Path $guardDir "state.json") -Raw | ConvertFrom-Json
$gate = $state.gate_port
$env:HTTP_PROXY = "http://localhost:$gate"
$env:HTTPS_PROXY = $env:HTTP_PROXY
$env:ALL_PROXY = $env:HTTP_PROXY
$env:http_proxy = $env:HTTP_PROXY
$env:https_proxy = $env:HTTP_PROXY
$env:all_proxy = $env:HTTP_PROXY
$env:NO_PROXY = "127.0.0.1,localhost,::1"
$env:no_proxy = $env:NO_PROXY
$env:BROWSER = Join-Path $guardDir "fingerprint-chromium.ps1"
$real = if ($env:CLAUDE_REAL_BIN) { $env:CLAUDE_REAL_BIN } else { "claude" }
Write-Host "OK network-gate=localhost:$gate os=windows (no process sandbox)"
& $real @args
exit $LASTEXITCODE
