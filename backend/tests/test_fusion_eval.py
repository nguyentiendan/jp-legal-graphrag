from jplegal.retrieval.evaluate import metrics
from jplegal.retrieval.fusion import weighted_rrf


def test_rrf_weights_and_merge():
    fused = dict(weighted_rrf({"dense": ["a", "b", "c"], "graph": ["c", "d"]}, {"dense": 1.0, "graph": 0.5}, k=60))
    assert abs(fused["a"] - 1 / 61) < 1e-9
    assert abs(fused["c"] - (1 / 63 + 0.5 / 61)) < 1e-9
    assert fused["c"] > fused["b"]  # xuất hiện ở 2 nhánh được cộng điểm
    assert "d" in fused


def test_metrics():
    m = metrics(["x", "a", "y", "b"], {"a", "b"})
    assert m["recall@1"] == 0.0 and m["recall@5"] == 1.0 and m["mrr@10"] == 0.5
    assert 0 < m["ndcg@10"] < 1


def test_slot_fusion():
    from jplegal.retrieval.fusion import slot_fusion

    out = [u for u, _ in slot_fusion(["a", "b", "c", "d", "e"], ["c", "x", "y", "z"], final_k=4, slots=2)]
    assert out[:4] == ["a", "b", "x", "y"]  # graph chỉ bổ sung điều mới, dense giữ đầu danh sách
    assert out[4:] == ["c", "d", "e"]
    assert [u for u, _ in slot_fusion(["a"], [], 3, 2)] == ["a"]
    # điều first stage xếp hạng thấp (ngoài top final_k) được graph kéo lên, không bị nhân đôi
    assert [u for u, _ in slot_fusion(["a", "b", "c", "d", "e"], ["e"], final_k=3, slots=1)] == ["a", "b", "e", "c", "d"]
