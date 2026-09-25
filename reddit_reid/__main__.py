import argparse
import json
from .common import load_config, BudgetStop


def main():
    parser = argparse.ArgumentParser(description="Bounded, resumable Reddit research")
    parser.add_argument("command", choices=["inspect", "import-keywords", "benchmark", "search", "reconstruct", "annotate", "export", "status", "run-pilot", "run-full", "finalize", "dry-run", "recover", "report", "demonstrate-joins"])
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--month")
    args = parser.parse_args()
    cfg = load_config(args.config)
    if args.command == "inspect":
        from .inspection import inspect
        result = inspect(cfg)
        result = {k: {a: b for a, b in v.items() if a != "months"} if isinstance(v, dict) else v for k, v in result.items()}
    elif args.command == "import-keywords":
        from .keywords import import_keywords
        result = import_keywords(cfg)
        result = {k: v for k, v in result.items() if k not in ("only_aggregate", "only_category", "close_variant_groups_for_review")}
    else:
        from .pipeline import dispatch
        result = dispatch(args.command, cfg, args)
    print(json.dumps(result, indent=2, ensure_ascii=True, default=str))


if __name__ == "__main__":
    try:
        main()
    except BudgetStop as exc:
        print(json.dumps({"stopped": str(exc), "resumable": True}))
        raise SystemExit(2)
