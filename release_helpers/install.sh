#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec env PYTHONDONTWRITEBYTECODE=1 "${PYTHON:-python3}" "$SCRIPT_DIR/install.py" --bundle "$SCRIPT_DIR" "$@"
