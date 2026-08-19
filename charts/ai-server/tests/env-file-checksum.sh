#!/usr/bin/env bash

set -euo pipefail

chart_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

render_checksum() {
  local env_file="$1"

  helm template ai-server "${chart_dir}" \
    --namespace dai-app \
    --set-string "ENV_FILE=${env_file}" \
    | awk '
        /^kind: Deployment$/ {
          in_deployment = 1
        }
        in_deployment && /checksum\/env-file:/ {
          print $2
          exit
        }
      '
}

first_checksum="$(render_checksum "SETTING=first")"
second_checksum="$(render_checksum "SETTING=second")"

if [[ -z "${first_checksum}" || -z "${second_checksum}" ]]; then
  echo "Rendered Deployment is missing checksum/env-file." >&2
  exit 1
fi

if [[ "${first_checksum}" == "${second_checksum}" ]]; then
  echo "Changing ENV_FILE did not change the Deployment checksum." >&2
  exit 1
fi

echo "ENV_FILE changes update the Deployment checksum."
