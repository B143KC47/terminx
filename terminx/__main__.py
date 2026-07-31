import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="terminx")
    parser.add_argument("--once", action="store_true", help="render a single frame and exit")
    args = parser.parse_args()

    from .ui.dashboard import run

    if args.once:
        from .config import load_config
        from .agents import ADAPTERS
        from .ui.dashboard import Dashboard

        cfg = load_config()
        dash = Dashboard(ADAPTERS, cfg)
        dash.scan()
        console = dash.console
        console.print(dash.render())
        console.print()
        return

    run()


if __name__ == "__main__":
    main()
