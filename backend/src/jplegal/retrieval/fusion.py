"""Weighted Reciprocal Rank Fusion: score(d) = Σ_i w_i / (k + rank_i(d)), rank bắt đầu từ 1."""

from __future__ import annotations


def weighted_rrf(rankings: dict[str, list[str]], weights: dict[str, float], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for name, ids in rankings.items():
        w = weights.get(name, 1.0)
        seen: set[str] = set()
        for rank, doc_id in enumerate(ids, start=1):
            if doc_id in seen:
                continue
            seen.add(doc_id)
            scores[doc_id] = scores.get(doc_id, 0.0) + w / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def slot_fusion(dense: list[str], graph: list[str], final_k: int, slots: int) -> list[tuple[str, float]]:
    """Dense là danh sách chính; graph chỉ bổ sung tối đa `slots` điều *mới* (không có trong dense).

    Thứ tự: dense[: final_k - slots] → graph (mới) → phần dense còn lại.
    Score trả về là 1/rank để hiển thị (không có ý nghĩa tuyệt đối).
    Lý do: với Ruri v3, dense đã rất mạnh; RRF cộng điểm khiến các điều "vừa dense hạng thấp vừa là hàng xóm"
    vượt lên trên điều đúng (đo bằng eval/queries.jsonl). Graph đóng vai trò cung cấp ngữ cảnh liên quan.
    """
    dense_set = set(dense)
    new_graph = [g for g in dict.fromkeys(graph) if g not in dense_set][: max(0, slots)]
    head = dense[: max(0, final_k - len(new_graph))]
    order = head + new_graph + [d for d in dense if d not in head]
    return [(u, 1.0 / (i + 1)) for i, u in enumerate(order)]
