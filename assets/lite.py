"""Entry point for every superpowers-lite pack command."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from litetools.cli import run  # noqa: E402

run()
