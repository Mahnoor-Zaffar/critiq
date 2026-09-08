from critiq.ai.providers.mock import MockProvider
from critiq.ai.reviewers import read_synthesis_prompt
from critiq.ai.synthesizer import Synthesizer
from critiq.analysis.diff import parse_patch
from critiq.core.findings import Finding, FindingSource
from critiq.core.policy import Category, ReviewPolicy, Severity

PATCH = """@@ -1,3 +1,8 @@
 import os
+
+SECRET = "sk-1234"
+
+def run():
+    os.system("echo hi")
"""


async def test_synthesize_applies_quality_gate_and_builds_comment():
    provider = MockProvider()
    policy = ReviewPolicy.defaults()
    diffs = [parse_patch("app/review.py", PATCH)]
    finding = Finding(
        category=Category.SECURITY,
        file_path="app/review.py",
        line_start=4,
        line_end=4,
        severity=Severity.HIGH,
        confidence=0.96,
        title="Hardcoded secret",
        explanation="Secret hardcoded.",
        evidence="Line 4.",
        recommendation="Move to env.",
        source=FindingSource.STATIC,
    )

    result = await Synthesizer(
        provider=provider,
        synthesis_prompt=read_synthesis_prompt(),
        policy=policy,
    ).synthesize([finding], diffs)

    assert result.decision in {"APPROVE", "COMMENT", "REQUEST_CHANGES"}
    assert result.comments
    assert result.comments[0].file_path == "app/review.py"
