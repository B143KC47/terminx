import argparse

from .i18n import t


def main() -> None:
    from .config import load_config
    from .i18n import set_language

    parser = argparse.ArgumentParser(prog="terminx")
    parser.add_argument("--once", action="store_true", help=t("render a single frame and exit"))
    args = parser.parse_args()

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
