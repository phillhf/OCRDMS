import sys


def main() -> int:
    args = sys.argv[1:]
    if args and args != ["--no-browser"]:
        from .cli import run_cli
        return run_cli(args)
    from .launcher import run_launcher
    return run_launcher(open_browser=not args)


if __name__ == "__main__":
    sys.exit(main())
