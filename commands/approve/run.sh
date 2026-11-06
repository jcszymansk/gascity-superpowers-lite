#!/bin/sh
exec python3 "${GC_PACK_DIR:?gc did not set GC_PACK_DIR}/assets/lite.py" approve "$@"
