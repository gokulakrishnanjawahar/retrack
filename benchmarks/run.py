"""One command for the support-desk benchmark (docs/features.md, Block F).

set -a && . ./.env && set +a
uv run python -m benchmarks.run                      # fake mode, $0
uv run python -m benchmarks.run --mode real --approved-spend --budget-usd 0.10
"""

import argparse

from benchmarks.support_desk.harness import run_benchmark, save, to_markdown


def main() -> None:
    parser = argparse.ArgumentParser(prog="benchmarks.run")
    parser.add_argument("--mode", choices=["fake", "real"], default="fake")
    parser.add_argument("--learn", type=int, default=16)
    parser.add_argument("--evaluate", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--keep", action="store_true", help="keep the throwaway project")
    parser.add_argument("--approved-spend", action="store_true")
    parser.add_argument("--budget-usd", type=float, default=0.10)
    args = parser.parse_args()
    report = run_benchmark(
        mode=args.mode,
        learn=args.learn,
        evaluate=args.evaluate,
        seed=args.seed,
        keep=args.keep,
        approved_spend=args.approved_spend,
        budget_usd=args.budget_usd,
    )
    json_path, md_path = save(report)
    print(to_markdown(report))
    print(f"saved {json_path} and {md_path}")


if __name__ == "__main__":
    main()
