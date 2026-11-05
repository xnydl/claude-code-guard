#!/bin/zsh

# Legacy filename only. Login now uses Fingerprint Chromium Guarded.

set -eu
exec /bin/zsh "${0:A:h}/fingerprint-chromium.sh" "$@"
