"""Short-lived, model-free terminal target for Windows navigation acceptance."""

import json
import os
import sys
import time
from pathlib import Path

Path(sys.argv[1]).write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
print(
    "terminX navigation acceptance target "
    + Path(sys.argv[1]).stem
    + " — closes automatically",
    flush=True,
)
deadline = time.monotonic() + (float(sys.argv[2]) if len(sys.argv) > 2 else 25)
while time.monotonic() < deadline and not Path(sys.argv[1] + ".stop").exists():
    time.sleep(0.1)
