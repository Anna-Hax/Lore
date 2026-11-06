from verifier.score import bm25, cosine, find_duplicate, length_ok, suggest_parents


def test_length_ok_is_inclusive():
    assert length_ok("abc", 3, 5) and length_ok("abcde", 3, 5)
    assert not length_ok("ab", 3, 5) and not length_ok("abcdef", 3, 5)


def test_cosine_identical_orthogonal_zero():
    assert round(cosine([1, 2], [2, 4]), 6) == 1
    assert cosine([1, 0], [0, 1]) == 0
    assert cosine([0, 0], [1, 1]) == 0


def test_find_duplicate_picks_closest_above_threshold():
    cands = [("a", [1, 0]), ("b", [0.95, 0.05]), ("c", [0, 1])]
    assert find_duplicate([1, 0], cands, 0.9)[0] == "a"
    assert find_duplicate([0.7, 0.7], cands, 0.99) is None


def test_bm25_ranks_keyword_match_and_normalises():
    docs = {"x": "monsoon rainfall in kerala and farming output", "y": "election results in maharashtra assembly"}
    s = bm25("maharashtra election turnout", docs)
    assert s == {"x": 0.0, "y": 1.0}


def test_suggest_parents_threshold_cap_and_order():
    nodes = {
        "1": ("bjp coalition maharashtra election", [1, 0, 0]),
        "2": ("maharashtra election turnout by district", [0.9, 0.1, 0]),
        "3": ("cricket world cup final", [0, 0, 1]),
    }
    p = suggest_parents("maharashtra election turnout analysis", [0.95, 0.05, 0], nodes, 0.5, 1)
    assert [x["node_id"] for x in p] == ["2"]
    assert suggest_parents("deep sea volcanic vents", [0, 1, 0], nodes, 0.5, 5) == []
