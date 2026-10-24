#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "============================================================================"
echo "  ABC2027 TrackID3x3 - Portable Ground-Truth Box & Trajectory Editor (v4)"
echo "============================================================================"
PY_BIN=$(command -v python3 || command -v python)
if [ -z "$PY_BIN" ]; then
  echo "[ERROR] Python 3 is not installed."
  exit 1
fi
"$PY_BIN" -c "import cv2, numpy, pandas" 2>/dev/null || "$PY_BIN" -m pip install opencv-python numpy pandas -q
"$PY_BIN" gt_editor_standalone.py
