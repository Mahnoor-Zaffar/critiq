def estimate_tokens(text: str) -> int:
    """The project's one token estimate: four characters per token.

    Shared by the history budgets and the evaluation report so the cost a
    prompt is charged cannot drift from the cost the budgets check.
    """
    return len(text) // 4
