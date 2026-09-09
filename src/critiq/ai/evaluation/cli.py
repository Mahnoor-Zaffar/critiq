from __future__ import annotations

import argparse
import asyncio

from critiq.ai.evaluation.dataset import load_dataset
from critiq.ai.evaluation.runner import render_report, run_evaluation
from critiq.ai.providers.mock import MockProvider
from critiq.ai.providers.openrouter import OpenRouterProvider
from critiq.core.config import settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="critiq-evaluate")
    parser.add_argument("dataset", help="Path to a dataset dir or YAML file")
    parser.add_argument(
        "--provider", choices=["mock", "openrouter"], default="mock"
    )
    parser.add_argument("--model", default=None, help="Model for the provider")
    parser.add_argument("--output", default=None, help="Write report to a file")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cases = load_dataset(args.dataset)
    if not cases:
        print(f"No evaluation cases found in {args.dataset}")
        return

    provider = _make_provider(args.provider, args.model)
    report = asyncio.run(run_evaluation(cases, provider=provider))
    text = render_report(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Wrote report to {args.output}")
    else:
        print(text)


def _make_provider(name: str, model: str | None):
    if name == "openrouter":
        return OpenRouterProvider(model=model or settings.llm_model_cheap)
    return MockProvider()


if __name__ == "__main__":
    main()
