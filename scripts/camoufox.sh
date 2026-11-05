#!/bin/zsh
# Legacy filename only. New configurations use fingerprint-chromium.sh.
set -eu
exec /bin/zsh "${0:A:h}/fingerprint-chromium.sh" "$@"
