"""BM25 sparse vector cho tiếng Nhật: Sudachi tách từ → sparse vector lưu trong Qdrant.

Qdrant tự tính IDF khi sparse vector được khai báo `modifier=idf`, nên ở đây chỉ cần:
  - tài liệu: trọng số tf của BM25   tf·(k1+1) / (tf + k1·(1 − b + b·|d|/avgdl))
  - câu hỏi:  mỗi từ (không trùng) trọng số 1.0
→ điểm Qdrant = Σ IDF(t) · w_doc(t) · w_query(t) = BM25.

Tách từ (Sudachi, từ điển core):
  - Chuẩn hoá trước: NFKC, số kanji trước 条/項/号/… và sau 第 → số Ả Rập ("第三十七条" → "第37条"),
    vì Sudachi tách "三十七条" thành "三" + "十七条".
  - Đa độ mịn: lấy token SplitMode.C (vd. 割増賃金, 年次有給休暇) và thêm các token SplitMode.A bên trong
    (割増, 賃金) → câu hỏi dùng từ ghép hay từ đơn đều khớp.
  - Dùng normalized_form (支払/支払い → 支払い, 36協定 → 三六協定), bỏ trợ từ / trợ động từ / ký hiệu.
  - Token → chỉ số uint32 bằng hash ổn định (blake2b), không cần lưu từ điển.
"""

from __future__ import annotations

import hashlib
import re
import threading
import unicodedata
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from jplegal.ingest.normalize import KANJI_NUM, kanji_to_int

_KEEP_POS = {"名詞", "動詞", "形容詞", "形状詞"}
_STOP = {
    "する", "ある", "いる", "なる", "れる", "られる", "よる", "こと", "もの", "その", "これ", "それ", "ため",
    "おる", "できる", "ない", "当該", "同じ", "次", "前", "号", "項", "条", "第",
    "為る", "成る", "有る", "居る", "出来る", "因る", "依る", "拠る", "無い", "於く", "於る",
}
_NUM_BEFORE = re.compile(rf"([{KANJI_NUM}]+)(?=条|項|号|編|章|節|款|目|箇月|か月|ヶ月|カ月|週間|時間|日|年|割|人|歳)")
_NUM_AFTER_DAI = re.compile(rf"(?<=第)([{KANJI_NUM}]+)")
_WS = re.compile(r"\s+")


def _kanji_num(m: re.Match) -> str:
    try:
        return str(kanji_to_int(m.group(1)))
    except ValueError:
        return m.group(1)


def normalize_for_tokenize(text: str) -> str:
    s = unicodedata.normalize("NFKC", text)
    s = _NUM_AFTER_DAI.sub(_kanji_num, s)
    s = _NUM_BEFORE.sub(_kanji_num, s)
    return _WS.sub(" ", s)


def token_id(token: str) -> int:
    return int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest(), "little")


@dataclass
class SparseVec:
    indices: list[int]
    values: list[float]

    def __bool__(self) -> bool:
        return bool(self.indices)


class JapaneseTokenizer:
    """Sudachi tokenizer – thread-safe bằng lock (đối tượng tokenizer của Sudachi không chia sẻ được giữa thread)."""

    # Sudachi giới hạn độ dài input (~49 KB); văn bản luật dài được chia theo câu
    MAX_CHARS = 8000

    def __init__(self, dict_name: str = "core", multi_granular: bool = True):
        from sudachipy import Dictionary, SplitMode

        self._dict = Dictionary(dict=dict_name)
        self._tok = self._dict.tokenizer()
        self._A, self._C = SplitMode.A, SplitMode.C
        self.multi = multi_granular
        self._lock = threading.Lock()

    def _pieces(self, text: str) -> list[str]:
        if len(text) <= self.MAX_CHARS:
            return [text]
        out, buf = [], ""
        for sent in re.split(r"(?<=。)", text):
            if len(buf) + len(sent) > self.MAX_CHARS and buf:
                out.append(buf)
                buf = ""
            buf += sent[: self.MAX_CHARS]
        if buf:
            out.append(buf)
        return out

    def tokenize(self, text: str) -> list[str]:
        text = normalize_for_tokenize(text)
        toks: list[str] = []
        with self._lock:
            for piece in self._pieces(text):
                for m in self._tok.tokenize(piece, self._C):
                    pos = m.part_of_speech()[0]
                    if pos not in _KEEP_POS:
                        continue
                    norm = m.normalized_form()
                    if norm not in _STOP and norm.strip():
                        toks.append(norm)
                    if self.multi:
                        subs = m.split(self._A)
                        if len(subs) > 1:
                            for sm in subs:
                                if sm.part_of_speech()[0] not in _KEEP_POS:
                                    continue
                                sn = sm.normalized_form()
                                if sn not in _STOP and sn.strip() and sn != norm:
                                    toks.append(sn)
        return toks


class BM25Encoder:
    def __init__(self, tokenizer: JapaneseTokenizer, k1: float = 1.2, b: float = 0.75, avg_len: float = 100.0):
        self.tok = tokenizer
        self.k1, self.b, self.avg_len = k1, b, max(1.0, avg_len)

    def _to_vec(self, weights: dict[int, float]) -> SparseVec:
        items = sorted(weights.items())
        return SparseVec(indices=[i for i, _ in items], values=[round(v, 5) for _, v in items])

    def encode_doc(self, text: str) -> SparseVec:
        toks = self.tok.tokenize(text)
        if not toks:
            return SparseVec([], [])
        dl = len(toks)
        norm = self.k1 * (1 - self.b + self.b * dl / self.avg_len)
        w: dict[int, float] = {}
        for t, tf in Counter(toks).items():
            tid = token_id(t)
            w[tid] = w.get(tid, 0.0) + tf * (self.k1 + 1) / (tf + norm)
        return self._to_vec(w)

    def encode_query(self, text: str) -> SparseVec:
        return self._to_vec({token_id(t): 1.0 for t in set(self.tok.tokenize(text))})


def doc_text_for_sparse(law_title: str, article_title: str, caption: str, text: str) -> str:
    """Văn bản dùng để tính BM25: tên luật + số điều + 見出し + nội dung."""
    return f"{law_title} {article_title} {caption or ''}\n{text}"


@lru_cache
def get_encoder(dict_name: str = "core", k1: float = 1.2, b: float = 0.75, avg_len: float = 100.0) -> BM25Encoder:
    return BM25Encoder(JapaneseTokenizer(dict_name), k1=k1, b=b, avg_len=avg_len)
