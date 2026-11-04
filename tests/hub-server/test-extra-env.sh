#!/usr/bin/env bash
set -euo pipefail
chart="$(cd "$(dirname "$0")/../../charts/hub-server" && pwd)"
helm_bin="${HELM_BIN:-helm}"
# Synthetic canonical 32-byte key; never use a real application key in tests.
base=(template test "$chart" --show-only templates/secrets.yml --set-string APP_KEY=base64:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= --set-string DIVI_HUB_PRIVATE_KEY_64=test-key)
output="$($helm_bin "${base[@]}" --set-string HUB_SERVER_EXTRA_ENV.APP_DEBUG=false --set-string HUB_SERVER_EXTRA_ENV.APP_PREVIOUS_KEYS=)"
[[ "$output" == *"    APP_DEBUG='false'"* ]]
[[ "$output" == *"    APP_PREVIOUS_KEYS=''"* ]]
[[ "$(printf '%s\n' "$output" | grep -c '    APP_KEY=')" == 1 ]]
if "$helm_bin" "${base[@]}" --set-string HUB_SERVER_EXTRA_ENV.APP_KEY=other >/dev/null 2>&1; then
    echo 'chart accepted an override of APP_KEY' >&2; exit 1
fi
if "$helm_bin" "${base[@]}" --set HUB_SERVER_EXTRA_ENV.APP_DEBUG=false >/dev/null 2>&1; then
    echo 'chart accepted a non-string value' >&2; exit 1
fi
if "$helm_bin" "${base[@]}" --set-string "HUB_SERVER_EXTRA_ENV.APP_DEBUG=bad'value" >/dev/null 2>&1; then
    echo 'chart accepted an unsafe quote' >&2; exit 1
fi
echo 'hub-server extra environment rendering: passed'
