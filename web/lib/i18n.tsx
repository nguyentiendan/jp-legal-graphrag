"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Lang = "vi" | "ja";

const dict = {
  "nav.ask": { vi: "Hỏi đáp", ja: "質問" },
  "nav.ingest": { vi: "Nạp dữ liệu", ja: "データ取込" },
  "nav.jobs": { vi: "Tiến trình", ja: "ジョブ" },
  "nav.laws": { vi: "Văn bản luật", ja: "法令一覧" },
  "app.tagline": { vi: "GraphRAG cho pháp luật Nhật Bản", ja: "日本法令 GraphRAG" },
  "ask.placeholder": { vi: "Đặt câu hỏi bằng tiếng Nhật, ví dụ: 残業代の割増率は何パーセントですか？", ja: "例：残業代の割増率は何パーセントですか？" },
  "ask.submit": { vi: "Hỏi", ja: "質問する" },
  "ask.stop": { vi: "Dừng", ja: "停止" },
  "ask.searchOnly": { vi: "Chỉ truy xuất", ja: "検索のみ" },
  "ask.graph": { vi: "Mở rộng graph", ja: "グラフ展開" },
  "ask.rerank": { vi: "Rerank", ja: "リランク" },
  "ask.sparse": { vi: "Từ khoá (BM25)", ja: "キーワード（BM25）" },
  "ask.filterLaws": { vi: "Giới hạn trong luật", ja: "対象法令" },
  "ask.allLaws": { vi: "Tất cả", ja: "すべて" },
  "ask.answer": { vi: "Câu trả lời", ja: "回答" },
  "ask.guard.unsupported": { vi: "Có trích dẫn không nằm trong các điều đã truy xuất.", ja: "参照条文にない引用があります。" },
  "ask.guard.missing": { vi: "Câu trả lời không trích điều luật nào.", ja: "回答に条文の引用がありません。" },
  "ask.evidence": { vi: "Điều luật căn cứ", ja: "参照条文" },
  "ask.graphView": { vi: "Liên kết giữa các điều", ja: "条文間の関係" },
  "ask.empty": { vi: "Hỏi một câu về luật đã nạp. Kết quả hiển thị câu trả lời, các điều luật căn cứ và nguồn truy xuất (Dense / BM25 / Graph).", ja: "取り込んだ法令について質問してください。" },
  "ask.noLaws": { vi: "Chưa có luật nào. Hãy nạp dữ liệu trước.", ja: "法令が未登録です。先にデータを取り込んでください。" },
  "ask.timings": { vi: "Thời gian (ms)", ja: "処理時間 (ms)" },
  "ask.via": { vi: "qua", ja: "経由" },
  "ask.showText": { vi: "Xem toàn văn", ja: "全文" },
  "ask.hideText": { vi: "Thu gọn", ja: "閉じる" },
  "ask.jevRelevance": { vi: "Jev liên quan", ja: "Jev関連" },
  "src.dense": { vi: "Dense", ja: "ベクトル" },
  "src.sparse": { vi: "BM25", ja: "BM25" },
  "src.graph": { vi: "Graph", ja: "グラフ" },
  "rel.REFERS_TO": { vi: "dẫn chiếu", ja: "参照" },
  "rel.APPLIES_MUTATIS_MUTANDIS": { vi: "準用", ja: "準用" },
  "rel.DELEGATES_TO": { vi: "uỷ quyền", ja: "委任" },
  "ingest.upload": { vi: "Upload file", ja: "ファイル" },
  "ingest.egov": { vi: "e-Gov 法令API", ja: "e-Gov 法令API" },
  "ingest.bulk": { vi: "XML một lần (bulk)", ja: "XML一括" },
  "ingest.drop": { vi: "Kéo thả file vào đây hoặc bấm để chọn", ja: "ここにドロップ、またはクリックして選択" },
  "ingest.formats": { vi: "XML (e-Gov), PDF có lớp text, DOCX, TXT, MD · tối đa 50MB", ja: "XML（e-Gov）・PDF・DOCX・TXT・MD／最大50MB" },
  "ingest.title": { vi: "Tên văn bản (tuỳ chọn)", ja: "文書名（任意）" },
  "ingest.force": { vi: "Nạp lại kể cả khi trùng nội dung", ja: "重複でも再取込" },
  "ingest.start": { vi: "Bắt đầu nạp", ja: "取込開始" },
  "ingest.lawIds": { vi: "law_id (mỗi dòng 1 mã)", ja: "法令ID（1行に1件）" },
  "ingest.titles": { vi: "Hoặc tên luật chính xác (mỗi dòng 1 tên)", ja: "または正式な法令名（1行に1件）" },
  "ingest.egovNote": { vi: "Hệ thống tự giới hạn 1 request/giây tới e-Gov. Nạp số lượng lớn nên dùng bulk.", ja: "e-Govへのアクセスは1秒1件に制限しています。大量取込は一括XMLを利用してください。" },
  "ingest.bulkNote": { vi: "Môi trường không có internet: chép file zip vào ./data/import trên server (mount tại /data/import) rồi nhập đường dẫn.", ja: "オフライン環境ではZIPをサーバーの ./data/import に配置し（/data/import にマウント）、パスを指定してください。" },
  "ingest.zipPath": { vi: "Đường dẫn zip trên server", ja: "サーバー上のZIPパス" },
  "ingest.categoryCd": { vi: "Hoặc mã lĩnh vực (category_cd) để tải từ e-Gov", ja: "または分類コード（e-Govから取得）" },
  "ingest.filterIds": { vi: "Chỉ nạp các law_id sau (tuỳ chọn)", ja: "対象の法令ID（任意）" },
  "ingest.titleContains": { vi: "Tên luật chứa (tuỳ chọn)", ja: "法令名に含む文字列（任意）" },
  "ingest.maxLaws": { vi: "Số luật tối đa", ja: "最大件数" },
  "ingest.queued": { vi: "Đã tạo job", ja: "ジョブを作成しました" },
  "ingest.duplicate": { vi: "File đã được nạp trước đó", ja: "同じファイルは取込済みです" },
  "ingest.rebuild": { vi: "Dựng lại liên kết graph", ja: "リンク再構築" },
  "jobs.title": { vi: "Tiến trình nạp dữ liệu", ja: "取込ジョブ" },
  "jobs.empty": { vi: "Chưa có job nào.", ja: "ジョブはありません。" },
  "jobs.kind": { vi: "Loại", ja: "種別" },
  "jobs.target": { vi: "Đối tượng", ja: "対象" },
  "jobs.status": { vi: "Trạng thái", ja: "状態" },
  "jobs.progress": { vi: "Tiến độ", ja: "進捗" },
  "jobs.created": { vi: "Tạo lúc", ja: "作成" },
  "status.queued": { vi: "Đang chờ", ja: "待機" },
  "status.running": { vi: "Đang chạy", ja: "実行中" },
  "status.succeeded": { vi: "Xong", ja: "完了" },
  "status.failed": { vi: "Lỗi", ja: "失敗" },
  "laws.title": { vi: "Văn bản đã nạp", ja: "取込済み法令" },
  "laws.search": { vi: "Tìm theo tên", ja: "名称で検索" },
  "laws.articles": { vi: "điều", ja: "条" },
  "laws.chunks": { vi: "chunk", ja: "チャンク" },
  "laws.empty": { vi: "Chưa có văn bản nào.", ja: "法令はまだありません。" },
  "laws.unresolved": { vi: "Dẫn chiếu tới luật chưa nạp", ja: "未取込法令への参照" },
  "laws.aliases": { vi: "Tên gọi tắt", ja: "略称" },
  "laws.degree": { vi: "liên kết", ja: "リンク" },
  "article.neighbors": { vi: "Điều liên quan", ja: "関連条文" },
  "common.loading": { vi: "Đang tải…", ja: "読み込み中…" },
  "common.error": { vi: "Lỗi", ja: "エラー" },
  "common.retry": { vi: "Thử lại", ja: "再試行" },
  "common.back": { vi: "Quay lại", ja: "戻る" },
  "footer.source": { vi: "Nguồn dữ liệu: e-Gov法令検索 (デジタル庁, PDL1.0). Câu trả lời không phải tư vấn pháp lý.", ja: "出典：e-Gov法令検索（デジタル庁、PDL1.0）。回答は法的助言ではありません。" },
} as const;

export type Key = keyof typeof dict;

const Ctx = createContext<{ lang: Lang; setLang: (l: Lang) => void; t: (k: Key) => string }>({
  lang: "ja",
  setLang: () => {},
  t: (k) => dict[k].ja,
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("ja");
  useEffect(() => {
    const saved = localStorage.getItem("lang");
    if (saved === "vi" || saved === "ja") setLangState(saved);
    else document.documentElement.lang = "ja";
  }, []);
  const setLang = (l: Lang) => {
    setLangState(l);
    localStorage.setItem("lang", l);
    document.documentElement.lang = l;
  };
  const t = (k: Key) => dict[k][lang];
  return <Ctx.Provider value={{ lang, setLang, t }}>{children}</Ctx.Provider>;
}

export const useT = () => useContext(Ctx);
