"""Entry point: `webtree` opens the CLI, `webtree web` serves the web GUI."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="webtree")
    sub = parser.add_subparsers(dest="command")
    web_parser = sub.add_parser("web", help="serve the web GUI on localhost")
    web_parser.add_argument("--port", type=int, default=8765)
    web_parser.add_argument("--host", default="127.0.0.1")
    sub.add_parser("cli", help="open the terminal UI (default)")
    args = parser.parse_args()
    if args.command == "web":
        from webtree import web

        web.serve(port=args.port, host=args.host)
    else:
        from webtree import tui

        tui.run()


if __name__ == "__main__":
    main()
