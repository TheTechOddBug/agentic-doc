#!/bin/sh
# ade-cli installer for macOS / Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/landing-ai/ade-cli/main/scripts/install.sh | sh
#
# Environment knobs:
#   ADE_CLI_VERSION      release to install ("0.2.0" or "v0.2.0"; default: latest)
#   ADE_CLI_INSTALL_DIR  where the app lands: the binary plus its _internal/
#                        support dir (default: ~/.ade/bin — inside the CLI's
#                        own home, next to the store; honors ADE_HOME)
#   GITHUB_TOKEN/GH_TOKEN  required while the repo is private; downloads go
#                          through the GitHub API instead of the public URL.
#
# Uninstall: remove ~/.ade/bin (the binary and its _internal/ support dir)
# and the ~/.local/bin/ade symlink. Never `rm -rf ~/.ade` — the rest of
# that directory is your local store (billed parse/extract results).
set -eu

REPO="landing-ai/ade-cli"
INSTALL_DIR="${ADE_CLI_INSTALL_DIR:-${ADE_HOME:-$HOME/.ade}/bin}"
VERSION="${ADE_CLI_VERSION:-latest}"
TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"

say() { printf '%s\n' "$*" >&2; }
fail() { say "error: $*"; exit 1; }

command -v curl >/dev/null 2>&1 || fail "curl is required"

# --- pick the release asset for this platform ------------------------------
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64)               target="darwin-arm64" ;;
  Darwin-x86_64)              target="darwin-x86_64" ;;
  Linux-aarch64 | Linux-arm64) target="linux-arm64" ;;
  Linux-x86_64 | Linux-amd64)  target="linux-x86_64" ;;
  Windows* | MINGW* | MSYS* | CYGWIN*)
    fail "use install.ps1 on Windows: irm .../install.ps1 | iex" ;;
  *)
    fail "unsupported platform: $(uname -s) $(uname -m)" ;;
esac
asset="ade-cli-${target}.tar.gz"

case "$VERSION" in
  latest) tag="" ;;
  v*)     tag="$VERSION" ;;
  *)      tag="v$VERSION" ;;
esac

tmp="$(mktemp -d)"
staging=""
trap 'rm -rf "$tmp"; if [ -n "$staging" ]; then rm -rf "$staging"; fi' EXIT INT TERM

# --- download ---------------------------------------------------------------
# Anonymous installs use the public download URL; with a token we resolve
# asset ids through the API, which also works while the repo is private.
fetch_public() { # $1 asset name, $2 output path
  if [ -n "$tag" ]; then
    url="https://github.com/${REPO}/releases/download/${tag}/$1"
  else
    url="https://github.com/${REPO}/releases/latest/download/$1"
  fi
  curl -fsSL --retry 3 -o "$2" "$url"
}

# Returns non-zero (never exits) when the release or asset is unavailable:
# callers decide what is fatal — the binary is, SHA256SUMS.txt is optional.
release_json="" # cached across fetch_api calls
fetch_api() { # $1 asset name, $2 output path
  if [ -z "$release_json" ]; then
    if [ -n "$tag" ]; then
      rel_url="https://api.github.com/repos/${REPO}/releases/tags/${tag}"
    else
      rel_url="https://api.github.com/repos/${REPO}/releases/latest"
    fi
    release_json="$(curl -fsSL --retry 3 -H "Authorization: Bearer ${TOKEN}" "$rel_url")" || {
      say "cannot read release ${VERSION} of ${REPO} (bad token or no release yet?)"
      release_json=""
      return 1
    }
  fi
  # Normalize the JSON to one whitespace-free token per line so the match
  # doesn't depend on GitHub's pretty-printing. Inside the "assets" array,
  # an asset's numeric id is the last "id" emitted before its "name" (the
  # guard keeps a release titled like an asset filename from matching).
  asset_id="$(printf '%s' "$release_json" | tr '{,' '\n\n' | tr -d ' \t' \
    | awk -v name="\"name\":\"$1\"" '
      /^"assets":\[/ { in_assets = 1 }
      in_assets && /^"id":[0-9]+$/ { id = substr($0, 6) }
      in_assets && index($0, name) == 1 { print id; exit }')"
  if [ -z "$asset_id" ]; then
    say "release has no asset $1"
    return 1
  fi
  curl -fsSL --retry 3 -o "$2" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Accept: application/octet-stream" \
    "https://api.github.com/repos/${REPO}/releases/assets/${asset_id}"
}

fetch() {
  if [ -n "$TOKEN" ]; then fetch_api "$1" "$2"; else fetch_public "$1" "$2"; fi
}

say "downloading ${asset} (${VERSION}) ..."
fetch "$asset" "$tmp/$asset" \
  || fail "download failed — while the repo is private, set GITHUB_TOKEN and retry"

# --- verify -----------------------------------------------------------------
if fetch "SHA256SUMS.txt" "$tmp/SHA256SUMS.txt" 2>/dev/null; then
  expected="$(grep " ${asset}\$" "$tmp/SHA256SUMS.txt" | awk '{print $1}')"
  [ -n "$expected" ] || fail "SHA256SUMS.txt has no entry for ${asset}"
  if command -v sha256sum >/dev/null 2>&1; then
    actual="$(sha256sum "$tmp/$asset" | awk '{print $1}')"
  else
    actual="$(shasum -a 256 "$tmp/$asset" | awk '{print $1}')"
  fi
  [ "$expected" = "$actual" ] || fail "checksum mismatch for ${asset}"
  say "checksum OK"
else
  say "warning: SHA256SUMS.txt not found on the release; skipping verification"
fi

# --- install ----------------------------------------------------------------
# The archive holds a onedir app: ade/ade plus ade/_internal/ with the
# bundled libraries. A single-file binary would re-extract those to
# fresh inodes on every launch, making macOS re-validate every code
# signature each run (~10s per command, issue #83); the app dir pays that
# once, right below at the warm-up run.
tar -xzf "$tmp/$asset" -C "$tmp"
mkdir -p "$INSTALL_DIR"
# Stage inside the destination dir so the final steps are same-filesystem
# renames: mv from the temp mount would degrade to copy+delete and could
# leave a half-copied tree under a running `ade`. A concurrently
# *launched* ade can still hit the brief window between the renames;
# an already-running one keeps its open inodes and is unaffected.
staging="$INSTALL_DIR/.ade.new.$$"
cp -R "$tmp/ade" "$staging"
chmod 755 "$staging/ade"
rm -rf "$INSTALL_DIR/_internal" "$INSTALL_DIR/ade" "$INSTALL_DIR/ade-cli"
mv -f "$staging/_internal" "$INSTALL_DIR/_internal"
mv -f "$staging/ade" "$INSTALL_DIR/ade"
rmdir "$staging"
staging=""

# The version call doubles as the warm-up: macOS validates each bundled
# library once per inode, so the one slow launch happens here, not on the
# user's first real command.
case "$target" in
  darwin-*) say "verifying the app (first launch validates its libraries; can take ~10s) ..." ;;
esac
say "installed $("$INSTALL_DIR/ade" version) to ${INSTALL_DIR}/ade"

# --- expose on PATH -----------------------------------------------------------
# Prefer a symlink in ~/.local/bin (the XDG user bin dir, already on PATH in
# most setups) over asking the user to edit rc files — and create the dir if
# it is missing rather than skipping the link. Never clobber a real file
# there: only create or refresh a symlink.
local_bin="$HOME/.local/bin"
link="$local_bin/ade"
linked=0
if [ "$INSTALL_DIR" != "$local_bin" ]; then
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    say "note: $link exists and is not a symlink; leaving it untouched"
  elif mkdir -p "$local_bin" 2>/dev/null && ln -sf "$INSTALL_DIR/ade" "$link" 2>/dev/null; then
    # A link that doesn't run is not an install: prove it resolves before
    # reporting it, and withdraw it if it doesn't.
    if "$link" version >/dev/null 2>&1; then
      linked=1
      say "linked $link -> $INSTALL_DIR/ade"
    else
      rm -f "$link"
      say "note: ade would not run through $link; skipped the symlink"
    fi
  fi
fi

on_path() { case ":$PATH:" in *":$1:"*) return 0 ;; *) return 1 ;; esac; }
say ""
if on_path "$INSTALL_DIR" || { [ "$linked" -eq 1 ] && on_path "$local_bin"; }; then
  say "run: ade --help"
else
  say "put it on PATH for this shell:"
  say "  export PATH=\"$INSTALL_DIR:\$PATH\""
  say "and to keep it, append that line to your shell's rc file:"
  say "  echo 'export PATH=\"$INSTALL_DIR:\$PATH\"' >> ~/.$(basename "${SHELL:-sh}")rc"
  say "then run: ade --help"
fi

# Printed even when the PATH check above passed: that check reads *this*
# shell's PATH, and the shells CI jobs, cron, and agent harnesses spawn are
# non-interactive — they source no rc file, so an rc-provided ~/.local/bin
# is not there for them. The absolute path is the one spelling that always
# resolves, and `help --json` is where a machine caller should start.
say ""
say "driving ade from CI, cron, or an agent? Those shells source no rc file:"
say "  $INSTALL_DIR/ade help --json      # absolute path — always resolves"
say "  export PATH=\"$INSTALL_DIR:\$PATH\"   # ...or put it on PATH first"
say "then pass --json to every command: the full result is on stdout."
