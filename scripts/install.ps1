# ade-cli installer for Windows (x86_64 / arm64).
#
#   irm https://raw.githubusercontent.com/landing-ai/ade-cli/main/scripts/install.ps1 | iex
#
# Environment knobs:
#   ADE_CLI_VERSION      release to install ("0.2.0" or "v0.2.0"; default: latest)
#   ADE_CLI_INSTALL_DIR  where the app lands: ade.exe plus its _internal\
#                        support dir (default: %USERPROFILE%\.ade\bin — inside
#                        the CLI's own home, next to the store; honors ADE_HOME)
#   GITHUB_TOKEN/GH_TOKEN  required while the repo is private; downloads go
#                          through the GitHub API instead of the public URL.
#
# Uninstall: remove %USERPROFILE%\.ade\bin (ade.exe and its _internal\
# support dir). Never delete all of .ade — the rest of that directory is
# your local store (billed results).
$ErrorActionPreference = "Stop"

$Repo = "landing-ai/ade-cli"
$InstallDir = if ($env:ADE_CLI_INSTALL_DIR) { $env:ADE_CLI_INSTALL_DIR }
              elseif ($env:ADE_HOME) { Join-Path $env:ADE_HOME "bin" }
              else { Join-Path $env:USERPROFILE ".ade\bin" }
$Version = if ($env:ADE_CLI_VERSION) { $env:ADE_CLI_VERSION } else { "latest" }
$Token = if ($env:GITHUB_TOKEN) { $env:GITHUB_TOKEN } elseif ($env:GH_TOKEN) { $env:GH_TOKEN } else { $null }

# --- pick the release asset for this machine --------------------------------
$target = switch ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture) {
    "Arm64" { "windows-arm64" }
    "X64"   { "windows-x86_64" }
    default { throw "unsupported architecture: $_" }
}
$Asset = "ade-cli-$target.zip"
$Tag = if ($Version -eq "latest") { $null }
       elseif ($Version.StartsWith("v")) { $Version } else { "v$Version" }

$Tmp = Join-Path ([System.IO.Path]::GetTempPath()) "ade-cli-install-$PID"
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null

try {
    # --- download ------------------------------------------------------------
    # Anonymous installs use the public download URL; with a token we resolve
    # asset ids through the API, which also works while the repo is private.
    $ReleaseJson = $null
    function Fetch-Asset([string]$Name, [string]$OutFile) {
        if ($Token) {
            if (-not $script:ReleaseJson) {
                $RelUrl = if ($Tag) { "https://api.github.com/repos/$Repo/releases/tags/$Tag" }
                          else { "https://api.github.com/repos/$Repo/releases/latest" }
                $script:ReleaseJson = Invoke-RestMethod -Uri $RelUrl -Headers @{ Authorization = "Bearer $Token" }
            }
            $Found = $script:ReleaseJson.assets | Where-Object { $_.name -eq $Name }
            if (-not $Found) { throw "release has no asset $Name" }
            Invoke-WebRequest -Uri "https://api.github.com/repos/$Repo/releases/assets/$($Found.id)" `
                -Headers @{ Authorization = "Bearer $Token"; Accept = "application/octet-stream" } `
                -OutFile $OutFile
        } else {
            $Url = if ($Tag) { "https://github.com/$Repo/releases/download/$Tag/$Name" }
                   else { "https://github.com/$Repo/releases/latest/download/$Name" }
            Invoke-WebRequest -Uri $Url -OutFile $OutFile
        }
    }

    Write-Host "downloading $Asset ($Version) ..."
    $Zip = Join-Path $Tmp $Asset
    try {
        Fetch-Asset $Asset $Zip
    } catch {
        throw "download failed ($_) — while the repo is private, set GITHUB_TOKEN and retry"
    }

    # --- verify ----------------------------------------------------------------
    $Sums = Join-Path $Tmp "SHA256SUMS.txt"
    try { Fetch-Asset "SHA256SUMS.txt" $Sums } catch { $Sums = $null }
    if ($Sums) {
        $Line = Get-Content $Sums | Where-Object { $_ -match [regex]::Escape($Asset) + "$" }
        if (-not $Line) { throw "SHA256SUMS.txt has no entry for $Asset" }
        $Expected = ($Line -split "\s+")[0]
        $Actual = (Get-FileHash -Algorithm SHA256 $Zip).Hash
        if ($Expected -ne $Actual) { throw "checksum mismatch for $Asset" }
        Write-Host "checksum OK"
    } else {
        Write-Warning "SHA256SUMS.txt not found on the release; skipping verification"
    }

    # --- install ---------------------------------------------------------------
    # The zip holds a onedir app: ade\ade.exe plus ade\_internal\ with the
    # bundled libraries (a single-file exe would re-extract those on
    # every launch and get rescanned each time — issue #83). Both pieces land
    # in $InstallDir so the exe sits next to its _internal dir.
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Expand-Archive -Path $Zip -DestinationPath $Tmp -Force
    Remove-Item -Recurse -Force (Join-Path $InstallDir "_internal") -ErrorAction SilentlyContinue
    Remove-Item -Force (Join-Path $InstallDir "ade.exe") -ErrorAction SilentlyContinue
    Remove-Item -Force (Join-Path $InstallDir "ade-cli.exe") -ErrorAction SilentlyContinue
    Move-Item -Force (Join-Path $Tmp "ade\_internal") (Join-Path $InstallDir "_internal")
    Move-Item -Force (Join-Path $Tmp "ade\ade.exe") (Join-Path $InstallDir "ade.exe")
    Write-Host "installed $(& (Join-Path $InstallDir 'ade.exe') version) to $InstallDir\ade.exe"

    # --- PATH (user-level) -------------------------------------------------------
    $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (($UserPath -split ";") -notcontains $InstallDir) {
        $NewPath = if ($UserPath) { "$UserPath;$InstallDir" } else { $InstallDir }
        [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
        $env:Path = "$env:Path;$InstallDir"
        Write-Host "added $InstallDir to your user PATH (open a new terminal to pick it up)"
    }
    Write-Host "run: ade --help"
    # The user PATH above reaches processes started after it — a runner or
    # service already running keeps the environment it launched with, so
    # give machine callers the spelling that always resolves.
    Write-Host ""
    Write-Host "driving ade from CI or an agent? Processes already running keep their old PATH:"
    Write-Host "  $InstallDir\ade.exe help --json   # absolute path - always resolves"
    Write-Host "then pass --json to every command: the full result is on stdout."
} finally {
    Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
}
