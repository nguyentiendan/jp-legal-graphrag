"""Đọc file zip XML一括ダウンロード của e-Gov.

Cấu trúc zip:
    R081006.csv                                   (metadata: 法令ID, 施行日, 未施行 ...)
    {law_id}_{施行日}_{改正法令ID}/{same}.xml
Chọn 1 revision / law_id: bỏ bản 未施行 (chưa có hiệu lực), lấy bản có 施行日 mới nhất ≤ hôm nay.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from jplegal.ingest.parsers.egov_xml import ids_from_filename


@dataclass
class BulkEntry:
    law_id: str
    revision_id: str
    member: str  # đường dẫn trong zip
    title: str = ""
    not_yet_enforced: bool = False


def _read_csv(z: zipfile.ZipFile) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for name in z.namelist():
        if not name.lower().endswith(".csv"):
            continue
        raw = z.read(name)
        for enc in ("utf-8-sig", "cp932"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            continue
        for row in csv.DictReader(io.StringIO(text)):
            law_id = (row.get("法令ID") or "").strip()
            url = row.get("本文URL") or ""
            rev = url.rstrip("/").split("/")[-1] if url else ""
            if law_id:
                rows[f"{law_id}_{rev}"] = row
    return rows


def list_entries(zip_path: Path, law_ids: set[str] | None = None, today: date | None = None) -> list[BulkEntry]:
    today = today or date.today()
    best: dict[str, BulkEntry] = {}
    with zipfile.ZipFile(zip_path) as z:
        meta = _read_csv(z)
        for name in z.namelist():
            if not name.lower().endswith(".xml"):
                continue
            law_id, revision_id = ids_from_filename(name)
            if not law_id or (law_ids and law_id not in law_ids):
                continue
            parts = revision_id.split("_")
            rev_date = parts[1] if len(parts) > 1 else ""
            row = meta.get(f"{law_id}_{'_'.join(parts[1:])}", {})
            not_yet = (row.get("未施行") or "").strip() in ("○", "1", "true") or (
                rev_date.isdigit() and rev_date > today.strftime("%Y%m%d")
            )
            entry = BulkEntry(law_id=law_id, revision_id=revision_id, member=name,
                              title=(row.get("法令名") or "").strip(), not_yet_enforced=not_yet)
            if not_yet:
                continue
            cur = best.get(law_id)
            if cur is None or entry.revision_id > cur.revision_id:
                best[law_id] = entry
    return sorted(best.values(), key=lambda e: e.law_id)


def iter_xml(zip_path: Path, entries: list[BulkEntry]) -> Iterator[tuple[BulkEntry, bytes]]:
    with zipfile.ZipFile(zip_path) as z:
        for e in entries:
            yield e, z.read(e.member)
