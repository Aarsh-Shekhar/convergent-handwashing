#!/usr/bin/env bash
# Clone the pinned YOLOv5 checkout used by the YOLO branch (AGPL-3.0; see THIRD_PARTY.md).
# The upstream notebook used YOLOv5 "v4.0-144-ge5b0200" (March 2021). Checkpoints trained with
# that era load with the v7.0 code path (DetectMultiBackend); v7.0 is the last stable YOLOv5 tag.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/third_party/yolov5"
TAG="${YOLOV5_TAG:-v7.0}"
if [ -d "$DEST/.git" ]; then
  echo "yolov5 already present at $DEST"; exit 0
fi
git clone --depth 1 --branch "$TAG" https://github.com/ultralytics/yolov5 "$DEST"
echo "cloned yolov5 $TAG into $DEST"
