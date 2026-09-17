from __future__ import annotations

from collections.abc import Awaitable, Callable

from critiq.ai.providers.base import LLMProvider
from critiq.ai.reviewers import build_reviewers, read_synthesis_prompt
from critiq.ai.synthesizer import Synthesizer
from critiq.analysis.context import ContextBuilder, RepoContext
from critiq.analysis.custom_rules import CustomRuleEngine
from critiq.analysis.diff import FileDiff
from critiq.analysis.static import StaticAnalyzer
from critiq.core.config import settings
from critiq.core.findings import Finding, ReviewResult
from critiq.core.policy import ReviewPolicy

FileFetcher = Callable[[str], Awaitable[str | None]]


async def run_review(
    diffs: list[FileDiff],
    fetch: FileFetcher,
    provider: LLMProvider,
    policy: ReviewPolicy | None = None,
    policy_yaml: str = "",
    repo_index=None,
    calibrator: Callable[[float, str], float] | None = None,
    history: str = "",
) -> ReviewResult:
    """Run the full review pipeline for a set of changed files."""
    policy = policy or ReviewPolicy.defaults()
    context_builder = ContextBuilder()
    context: RepoContext = await context_builder.build(
        changed_files=diffs,
        fetch=fetch,
        policy_yaml=policy_yaml,
        repo_index=repo_index,
        history=history,
    )

    reviewers = build_reviewers(provider, policy)
    findings: list[Finding] = []
    static = StaticAnalyzer()
    custom = CustomRuleEngine(policy.rules)
    for diff in diffs:
        findings.extend(static.analyze(context, diff))
        findings.extend(custom.analyze(context, diff))
        for reviewer in reviewers:
            findings.extend(await reviewer.review(context, diff))

    synthesizer = Synthesizer(
        provider=provider,
        synthesis_prompt=read_synthesis_prompt(),
        policy=policy,
        model=settings.llm_model_strong,
        calibrator=calibrator,
        history=history,
    )
    return await synthesizer.synthesize(findings, diffs)
