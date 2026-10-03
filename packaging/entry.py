"""Start a Windows package executable."""

import sys
from pathlib import Path


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--internal":
        from terminx.core.runtime import HELPERS

        if len(sys.argv) < 3 or sys.argv[2] not in HELPERS:
            raise SystemExit("Unknown internal helper")
        import runpy

        module = sys.argv.pop(2)
        sys.argv.pop(1)
        runpy.run_module(module, run_name="__main__")
    elif Path(sys.executable).stem == "terminx-sidebar":
        from terminx.ui.sidebar import main as sidebar_main

        sidebar_main()
    else:
        from terminx.__main__ import main as console_main

        console_main()


if __name__ == "__main__":
    main()
