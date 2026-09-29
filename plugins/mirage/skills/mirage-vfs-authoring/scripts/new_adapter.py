import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=
        "Create a runnable Mirage adapter with a read-contract check.")
    parser.add_argument("--language",
                        choices=("python", "typescript"),
                        required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    suffix = "py" if args.language == "python" else "ts"
    template = Path(
        __file__).resolve().parent.parent / "assets" / f"adapter.{suffix}"
    if args.output.suffix != f".{suffix}":
        parser.error(f"--output must have the .{suffix} extension")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("x", encoding="utf-8") as target:
            target.write(template.read_text(encoding="utf-8"))
    except FileExistsError:
        parser.error(f"refusing to overwrite {args.output}")


if __name__ == "__main__":
    main()
