#!/usr/bin/env bash
# Alias de compatibilidad: delega en ./run
set -euo pipefail
exec "$(dirname "$0")/run"
