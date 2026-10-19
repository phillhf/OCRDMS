import sys


def main() -> int:
    if len(sys.argv) > 1:
        from .cli import run_cli
        return run_cli(sys.argv[1:])
    from .launcher import run_launcher
    return run_launcher()


if __name__ == "__main__":
    sys.exit(main())
