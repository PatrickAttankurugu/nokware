from nokware.scorers import precision_at_k, recall_at_k, mrr, p95


def test_precision_at_k():
    assert precision_at_k(["a", "b", "c"], {"a", "c"}, k=2) == 0.5
    assert precision_at_k([], {"a"}, k=5) == 0.0


def test_recall_at_k():
    assert recall_at_k(["a", "b"], {"a", "z"}, k=10) == 0.5
    assert recall_at_k(["a"], set(), k=5) == 0.0


def test_mrr():
    assert mrr(["x", "a"], {"a"}) == 0.5
    assert mrr(["z"], {"a"}) == 0.0


def test_p95():
    assert p95(list(range(1, 101))) == 95
    assert p95([]) == 0.0
