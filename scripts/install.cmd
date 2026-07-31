@echo off
rem ade-cli installer for Windows CMD — a thin wrapper that runs the
rem PowerShell installer (install.ps1), the single Windows install body.
rem
rem   curl -fsSL https://raw.githubusercontent.com/landing-ai/ade-cli/main/scripts/install.cmd -o install.cmd && install.cmd && del install.cmd
rem
rem Same knobs as install.ps1: ADE_CLI_VERSION, ADE_CLI_INSTALL_DIR, and
rem GITHUB_TOKEN/GH_TOKEN (also used here to fetch install.ps1 itself while
rem the repo is private).
setlocal
set "PS1_URL=https://raw.githubusercontent.com/landing-ai/ade-cli/main/scripts/install.ps1"

where powershell >nul 2>nul
if errorlevel 1 (
  echo error: PowerShell is required but was not found on PATH. 1>&2
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$t = $env:GITHUB_TOKEN; if (-not $t) { $t = $env:GH_TOKEN };" ^
  "$p = @{ Uri = '%PS1_URL%' }; if ($t) { $p.Headers = @{ Authorization = 'Bearer ' + $t } };" ^
  "Invoke-RestMethod @p | Invoke-Expression"
exit /b %errorlevel%
