import argparse
import sys

from .i18n import t


def main() -> None:
    from .config import load_config
    from .i18n import set_language

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser(prog="terminx")
    parser.add_argument(
        "--once", action="store_true", help=t("render a single frame and exit")
    )
    parser.add_argument(
        "--sidebar", action="store_true", help="open the native desktop sidebar"
    )
    from . import __version__

    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--startup",
        choices=["status", "enable", "disable"],
        help="Change the Windows sign-in setting",
    )
    parser.add_argument(
        "--cleanup", action="store_true", help="Remove termiX hooks before uninstall"
    )
    args = parser.parse_args()

    if args.startup:
        from .core.startup import set_startup, startup_enabled

        if args.startup != "status":
            set_startup(args.startup == "enable")
        print("enabled" if startup_enabled() else "disabled")
        return
    if args.cleanup:
        from .core.cleanup import cleanup

        cleanup()
        return
    if args.sidebar:
        sys.argv = [sys.argv[0]]
        from .ui.sidebar import main as sidebar_main

        sidebar_main()
        return

    cfg = load_config()
    set_language(cfg.get("lang", "auto"))

    from .ui.dashboard import run

    if args.once:
        from .agents import ADAPTERS
        from .ui.dashboard import Dashboard

        dash = Dashboard(ADAPTERS, cfg)
        dash.scan()
        console = dash.console
        console.print(dash.render())
        console.print()
        return

    run()


if __name__ == "__main__":
    main()
