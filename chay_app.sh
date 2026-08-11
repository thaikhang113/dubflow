#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ ! -x .venv/bin/python ]]; then
  echo "[LOI] Chua co .venv. Chay ./cai_dat_all.sh truoc."
  exit 1
fi

exec .venv/bin/python -m autodub_gui
