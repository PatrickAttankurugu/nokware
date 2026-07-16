def is_drift(value: float, baseline: float | None, threshold: float = 0.10,
             higher_is_worse: bool = False) -> bool:
    """Check if a value has drifted from its baseline.

    Args:
        value: The current metric value
        baseline: The baseline (7-day average) or None
        threshold: Relative drift threshold (default 0.10 = 10%)
        higher_is_worse: For latency metrics where higher means worse performance

    Returns:
        True if drift is detected, False otherwise
    """
    if baseline is None or baseline == 0:
        return False
    if higher_is_worse:
        return value > baseline * (1 + threshold)
    return value < baseline * (1 - threshold)
