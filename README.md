# JP Legal GraphRAG（P1）

日本の法令文書を対象とした **GraphRAG（グラフ拡張検索）** システムです。

**Dense検索（意味検索）＋ BM25（キーワード検索）＋ Graph展開（引用・委任関係の辿り）** を組み合わせ、根拠となる条文を提示しながら質問に回答します。埋め込み（embedding）とリランクには日本語モデル **Ruri v3**（`cl-nagoya/ruri-v3-310m` / `cl-nagoya/ruri-v3-reranker-310m`）を使用し、フロントエンドは **Next.js**（静的エクスポート）を **Nginx** で配信します。

**オンプレミス運用**を前提に設計されており、各サービスが個別のDockerfileを持ち、`docker-compose.yml` で一括起動します。インターネットに接続できない環境（エアギャップ環境）への持ち込みにも対応しています。

アーキテクチャの詳細は [docs/01-tech-stack-va-kien-truc.md](docs/01-tech-stack-va-kien-truc.md) を参照してください。

---

## 目次

- [JP Legal GraphRAG（P1）](#jp-legal-graphragp1)
  - [目次](#目次)
  - [プロジェクト概要](#プロジェクト概要)
  - [主な機能](#主な機能)
  - [アーキテクチャ](#アーキテクチャ)
    - [システム全体構成](#システム全体構成)
    - [コンテナ構成](#コンテナ構成)
    - [技術スタック](#技術スタック)
  - [検索パイプライン（Retrieval）](#検索パイプラインretrieval)
  - [取り込みパイプライン（Ingest）](#取り込みパイプラインingest)
    - [取り込み方法](#取り込み方法)
    - [処理ステップ](#処理ステップ)
    - [ID設計](#id設計)
  - [データモデル](#データモデル)
    - [Neo4j（グラフ）](#neo4jグラフ)
    - [Qdrant（ベクトル）](#qdrantベクトル)
    - [PostgreSQL（メタデータ）](#postgresqlメタデータ)
  - [画面構成](#画面構成)
  - [APIとCLI](#apiとcli)
  - [クイックスタート](#クイックスタート)
  - [LLMの設定](#llmの設定)
    - [デフォルト：Docker Compose内のOllama](#デフォルトdocker-compose内のollama)
    - [外部LLMを使う場合](#外部llmを使う場合)
  - [評価結果](#評価結果)
  - [性能に関する注意](#性能に関する注意)
  - [環境変数](#環境変数)
  - [エアギャップ環境（オフライン環境）](#エアギャップ環境オフライン環境)
  - [e-Gov 法令APIの利用制限](#e-gov-法令apiの利用制限)
  - [よく使うコマンド](#よく使うコマンド)
  - [ディレクトリ構成](#ディレクトリ構成)
  - [ローカル開発（Dockerなし）](#ローカル開発dockerなし)
  - [CI/CDとEC2へのデプロイ](#cicdとec2へのデプロイ)
  - [ロードマップ](#ロードマップ)
  - [制限事項・リスク](#制限事項リスク)
  - [データの著作権・出典表示](#データの著作権出典表示)

---

## プロジェクト概要

日本の法令は、条文同士の引用（「第〇条」「前条」「準用」など）や、法律から施行令・施行規則への委任によって強く結びついています。そのため、ベクトル検索だけでは「質問に答えるために本当に必要な条文一式」を取りこぼすことがあります。

本プロジェクトは、法令XMLの構造と引用関係を **決定的（deterministic）に** 解析してグラフを構築し、ベクトル検索の結果をそのグラフで補完することで、複数条文にまたがる質問（multi-hop質問）にも対応します。LLMによるエンティティ抽出に依存しないため、取り込み結果が再現可能で、検証もしやすい設計です。

現在は **P1フェーズ** で、労働分野の法令（労働基準法、労働基準法施行規則、労働契約法、労働安全衛生法、最低賃金法など）をサンプルデータとして収録しています。

---

## 主な機能

- **ハイブリッド検索**: Dense（Ruri v3）＋ BM25（Sudachi形態素解析、Qdrantのsparse vector）を1回のQdrantリクエストで実行し、DBSFで融合
- **クエリ書き換え**: 口語（残業代・クビ・36協定）を法令用語へ。辞書＋任意のLLM。検索クエリはログに残す
- **Graph展開**: 1ホップ。incoming `REFERS_TO` のハブ条は入次数で切る。委任先の施行令・規則は常に検索。準用は原文スパンをコンテキストへ。定義語 `:Term`
- **リランク**: Ruri v3リランカー（cross-encoder）で最終順位を決定
- **意図分類（Jev Choice）**: 質問の前に TypeSafe Jev で `greeting` / `rag_query` / `out_of_scope` を判定。挨拶・法令外は検索せず固定返信。`TYPESAFE_API_KEY` 未設定時は RAG へフォールバック
- **条文関連度（Jev Noul）**: 検索後に各条文へ独立の yes/no。閾値未満は LLM の根拠から除外。画面には `relevance_noul` を表示
- **根拠付き回答生成**: LiteLLM経由で `[労働基準法 第32条第1項]` 形式、施行日・e-Gov・PDL1.0付き。根拠がなければ「参照条文からは判断できません」
- **出力ガードレール（規則ベース）**: 項の引用は取得チャンクにその項があるときだけ許可。免責文を必ず付与
- **法令の取り込み**: e-Gov 法令API、e-Gov XML一括ダウンロード（ZIP）、ファイルアップロード（XML / PDF / DOCX / TXT）の3経路に対応。取り込みはジョブキューで非同期実行
- **法令・条文ブラウザ**: 取り込み済み法令の一覧・条文表示、関連グラフの可視化
- **検索評価**: Recall@k / MRR@10 / nDCG@10 / All@10 を構成別（dense / bm25 / hybrid / +graph / +rerank）に測定する評価基盤を内蔵
- **オンプレミス／エアギャップ対応**: モデルのイメージ同梱、イメージファイルの書き出し・読み込み、内部ミラー（PyPI / npm等）の指定に対応

---

## アーキテクチャ

### システム全体構成

```text
                    :8080
  ブラウザ ──► web（Nginx + Next.js静的配信） ──/api──► api（FastAPI）
                                                           │ enqueue（Redis / arq）
                                                           ▼
                                                        worker（取り込み処理）
        ┌─────────────┬──────────────┬──────────────┬─────┴────────┬──────────────┐
        ▼             ▼              ▼              ▼              ▼              ▼
  model-server      ollama         qdrant         neo4j        postgres         redis
 （Ruri v3による  （回答生成用LLM、  （ベクトル）   （グラフ）  （メタデータ、 （キュー、
   埋め込み＋       LiteLLM経由）                               ジョブ管理）    レート制限）
    リランク）
```

処理は大きく **取り込み（Ingest）** と **検索（Retrieval）** の2系統に分かれます。

- **Ingest**: 法令ファイルを取得・解析し、条文単位に分割（chunk化）したうえで、埋め込みベクトルをQdrantへ、構造と引用関係をNeo4jへ、メタデータをPostgreSQLへ保存します。APIからRedisキューへジョブを投入し、`worker` が非同期に処理します。
- **Retrieval**: 質問をDense＋BM25で検索し、Neo4jでグラフ展開して候補を補い、リランカーで並べ替えたうえで、LLMが根拠条文に基づく回答を生成します。

外部に公開されるのは `web`（Nginx）のポートのみで、その他のサービスはDocker内部ネットワーク内に閉じています。デバッグ時に各サービスのポートを `127.0.0.1` にだけ公開する `docker-compose.dev.yml` が用意されています。

### コンテナ構成

| サービス | Dockerfile / イメージ | 内部ポート | 役割 |
|---|---|---|---|
| web | `web/Dockerfile` | 80（ホスト側は `WEB_PORT`） | Nodeで `next build` した静的ファイルをNginxで配信。`/api` を `api:8000` へプロキシ（SSEはバッファリング無効） |
| api | `backend/Dockerfile.api` | 8000 | FastAPI。APIドキュメントは `/api/docs` |
| worker | `backend/Dockerfile.worker` | － | arqワーカー。アップロード、e-Gov API取得、XML一括取り込み、リンク再構築を実行 |
| model-server | `services/model-server/Dockerfile` | 8080 | `/v1/embeddings` と `/v1/rerank` を提供。デフォルトはCPU、GPUはオーバーライドで有効化 |
| ollama | `ollama/ollama:0.40.4` | 11434 | 回答生成用LLM。初回起動時に `ollama-pull` ジョブが `OLLAMA_MODEL` を自動ダウンロード |
| qdrant | `qdrant/qdrant:v1.19.2` | 6333 | ベクトルDB（dense＋sparseのハイブリッド検索） |
| neo4j | `neo4j:5.26-community` | 7687 | グラフDB（法令構造・引用関係） |
| postgres | `postgres:17` | 5432 | メタデータ、ジョブ状態、引用元の管理 |
| redis | `redis:8.2` | 6379 | ジョブキュー、e-Gov APIのレート制限 |

補助的なComposeファイルとして、GPU用（`docker-compose.gpu.yml`）、開発・デバッグ用（`docker-compose.dev.yml`）、EC2本番用（`docker-compose.prod.yml`：ビルド済みイメージのpullのみ）があります。

### 技術スタック

| レイヤー | 採用技術 | 備考 |
|---|---|---|
| フロントエンド | Next.js 16（App Router、TypeScript）、React 19、Tailwind CSS v4、`react-force-graph-2d` | 静的エクスポートしNginxで配信。画面は質問応答、データ取り込み、ジョブ進捗、法令・グラフ閲覧。日本語／ベトナム語のUI切り替え対応 |
| バックエンドAPI | Python 3.12、FastAPI、Pydantic v2、uv | `/api/ingest`、`/api/jobs`、`/api/laws`、`/api/search`、`/api/ask`（SSE） |
| ジョブキュー | Redis ＋ arq | 取り込みを非同期実行し、ジョブ状態とリトライを管理 |
| メタデータDB | PostgreSQL 17、SQLAlchemy（async） | 文書、取り込みジョブ、法令バージョン、引用情報（`legal_refs`）を管理。QdrantとNeo4jの同期の起点 |
| ベクトルDB | Qdrant | コレクション `articles`。768次元のdenseベクトル（cosine）とBM25 sparseベクトルを同一ポイントに格納 |
| グラフDB | Neo4j 5.26 Community | 埋め込みは持たず、法令構造と引用関係のみを保持 |
| モデルサーバー | FastAPI ＋ sentence-transformers | Ruri v3の埋め込み／リランク2モデルを1サービスで提供 |
| 埋め込みモデル | `cl-nagoya/ruri-v3-310m` | 768次元、最大8192トークン。接頭辞はクエリ側 `検索クエリ: `、文書側 `検索文書: ` |
| リランクモデル | `cl-nagoya/ruri-v3-reranker-310m` | cross-encoder、最大8192トークン。埋め込みモデルと同系列（ModernBERT-Ja系） |
| LLM | LiteLLM経由（Ollama / vLLM / 各種クラウド等） | 回答生成のみに使用。モデルは環境変数で切り替え可能 |
| パーサー | lxml（e-Gov XML）、PyMuPDF（PDF）、python-docx（DOCX） | 日本語の正規化にはNFKC＋漢数字変換、形態素解析にはSudachiPy（`sudachidict-core`） |
| 評価 | 独自スクリプト | Recall@k、MRR@10、nDCG@10、All@10 |
| インフラ | Docker Compose | `model-server` と `ollama` はGPU割り当て可能 |

---

## 検索パイプライン（Retrieval）

```text
質問 ─► Jev Choice（intent）
         greeting / out_of_scope ─► 固定返信（検索しない）
         rag_query ─► 口語→法令用語（辞書＋任意LLM）
                    ┬─► Dense検索（Ruri v3）        ─┐ Qdrantへ1リクエストで2件のprefetch
                    └─► BM25検索（Sudachi、sparse） ─┘ DBSF ─► seed ─► Graph（項・委任・定義語）─► リランク
                                                                                 │
                                                                                 ▼
                                                              Jev Noul（条文ごと関連度）─► LLM ─► 項の引用ガード
```

0. **意図分類（Jev Choice）**: `greeting` / `rag_query` / `out_of_scope`。挨拶と法令外は固定返信。
1. **クエリ書き換え**: 口語を法令用語に展開します（残業代→割増賃金、クビ→解雇、36協定→時間外労働・休日労働）。辞書に加え、LLMが有効なら短い法令用語クエリを追記します。展開後の文字列は埋め込みとBM25にだけ使い、画面・関連度・回答生成は元の質問のままです。`search_query` は評価用にログします。
2. **第1段階（Qdrantハイブリッド検索）**: denseとbm25の2つのprefetchを1回の `query_points` リクエストで実行し、DBSF（デフォルト）またはRRFで融合して上位の条文を取得します。各条文には Dense / BM25 / Graph のどの経路で見つかったか（出典ラベル）と経路別の順位・スコアが付きます。現行改正は `is_current=true`（または未設定の旧ポイント）のみを対象にします。
3. **Graph展開（Neo4j）**: 上位5件（seed）から引用・準用・委任を1ホップ辿ります。**入次数の大きい定義条への incoming `REFERS_TO` は切る**（`GRAPH_MAX_IN_DEGREE`）。outgoing を優先し、incoming のみの候補はスコアを下げます。準用エッジの `raw_span`（読み替え原文）はコンテキストに付けます。**委任は first-class**: seed の属する法律に `施行令`/`施行規則` があれば、常にその法令内で dense 検索します。定義語（「…とは…をいう」）は `:Term` から定義条文を足します。
4. **融合（Fusion）**: リランクなしの場合は **slots方式**（denseの結果を主とし、グラフ由来の新規条文を最大 `GRAPH_SLOTS` 件まで追加）。リランクありの場合は「第1段階の上位 ∪ グラフ候補」をリランカーに渡します。比較用にRRF方式（`FUSION_MODE=rrf`）も残しています。
5. **リランク**: Ruri v3リランカーで候補を再順位付けし、最終的に上位 `FINAL_K` 件を根拠条文とします。
6. **条文関連度（Jev Noul）**: 各条文について「この条文は質問の根拠になるか」を独立に判定。長い条文は先頭＋末尾（ただし書・委任条項が残るよう中略）で800字に収めて送ります。`JEV_RELEVANCE_MIN_NOUL` 未満は生成コンテキストから外します（一覧には残し、スコアを表示）。
7. **回答生成**: 関連度を満たした条文を `法令名 第◯条第◯項`、改正ID、施行日付きで渡し、根拠がなければ「参照条文からは判断できません」と書かせます。回答末尾に改正施行日・e-Gov・PDL1.0・免責を求めます。
8. **出力ガードレール**: `[法令名 第◯条第N項]` は、取得チャンクの項番号または本文にその項があるときだけ許可します。条だけ取得しているのに項を引用するのは拒否します。第32条の2と第32条は別条文です。

質問が挨拶や法令外と判定された場合は 1〜8 をスキップします。Jev の Choice の信頼度が `JEV_INTENT_MIN_CONFIDENCE` 未満のときは `rag_query` 扱いにして検索します。

**BM25の仕組み**

- BM25はキーワードの出現頻度に基づくスコアリング方式です。Sudachi（`sudachipy` ＋ `sudachidict-core`）で日本語を分かち書きし、各チャンクについてdenseベクトルと同じQdrantポイントにsparseベクトル `bm25` として保存します。IDFはQdrant側で計算します（`modifier: idf`）。新しいサービスは追加していません。
- 分かち書きの工夫として、条・項・号の前の漢数字を算用数字に正規化（`第三十七条` → `第37条` のため「37条」でもヒット）、複合語（割増賃金）とその構成語（割増、賃金）の両方を索引、`normalized_form` の採用（36協定 → 三六協定）を行っています。
- 有効／無効は `SPARSE_ENABLED`（デフォルト有効）またはUIの「キーワード（BM25）」チェックで切り替えます。
- 既存データ（sparseベクトルのないコレクション）からの移行は `make reindex-sparse` で行います。e-Govからの再取得や埋め込みの再計算は不要です。`BM25_K1`、`BM25_B`、`BM25_AVG_LEN`、`SUDACHI_DICT` を変更した場合も同じコマンドを再実行してください。

---

## 取り込みパイプライン（Ingest）

### 取り込み方法

| 方法 | 用途 | 入口 |
|---|---|---|
| Batch（CLI / cron） | e-Govからの初回取り込み、定期更新 | `jplegal ingest-egov --file /app/config/laws.yaml`（`make seed`）、XML一括ZIPは `jplegal ingest-bulk`（`make bulk`） |
| アップロード（UI） | 手元にある法令ファイルや補足資料（通達、社内規程、ガイドライン等） | 画面「データ取り込み」からXML / PDF / DOCX / TXTをアップロード、または `law_id` 指定、ZIP一括取り込み。進捗は画面「進捗」で確認 |

どの方法でも、最終的には `worker` 内の同一パイプラインで処理されます（入口の「取得方法」だけが異なります）。

### 処理ステップ

各ステップでジョブの状態を更新します。

1. **登録（Register）**: ファイルの `sha256` を計算し、同一ハッシュが取り込み済みならスキップ（冪等）。`documents` に `pending` として記録します。
2. **解析（Parse）**: e-Gov XMLは `法令 > 章・節 > 条（Article）> 項（Paragraph）> 号（Item）` の木構造として解析します。PDF / DOCX / TXTはテキストを抽出し、`第[漢数字・数字]+条` のパターンで条文に分割します（見つからない場合は見出し・段落単位にフォールバック）。
3. **正規化（Normalize）**: 選択的NFKCと漢数字の変換を行い、`第三十二条の二第一項` のような表記を `32_2` 条・1項として扱えるようにします。
4. **分割（Chunk）**: **1項＝1チャンク**（ただし書・号を項の本文に残す）。先頭に法令名・章節・見出し・項番号を付けます。1項が極端に長い場合のみさらに分割します。
5. **引用抽出（Reference extraction）**: ルールベースで「第◯条」「前条」「次条」「前項」「同条」「同法」「◯◯法第◯条」「政令で定める」「準用」などを抽出します。
6. **埋め込み（Embed）**: `検索文書: ` を付けてバッチ処理で埋め込みし、Qdrantへupsertします。
7. **グラフ登録（Graph load）**: 条文の `uid` をキーにNeo4jへMERGEします。
8. **完了（Finalize）**: `documents` を `done` にし、チャンク数・引用数、解決できなかった引用の一覧を保存します。

### ID設計

- 条文の識別子は `uid = {law_id}#{article_key}`（例：`322AC0000000049#32_2`、第32条の2）で、チャンクは `{uid}~p{項}~{part}` です。再取込時は `KEEP_REVISIONS=true`（デフォルト）なら旧Qdrantポイントを `is_current=false` にし、現行だけ検索します。Neo4jのグラフは現行改正です。時点指定（as-of）の完全な回答はまだ未対応です。
- `law_id` はe-Gov法令検索のURLに含まれる法令IDです。
- 同じ法令を再取り込みすると現行バージョンが置き換わります。法令バージョンの管理方針は [docs/01-tech-stack-va-kien-truc.md](docs/01-tech-stack-va-kien-truc.md) を参照してください。
- PostgreSQLの `legal_refs` テーブルが引用関係の正本であり、Neo4jのグラフはそこから `jplegal rebuild-links` で再構築できます。

---

## データモデル

### Neo4j（グラフ）

```text
(:Law {law_id, law_num, title, abbrev, law_type, promulgation_date, enforcement_date, revision_id, is_current, source})
(:Article {uid, law_id, article_key, article_title, caption, path, text})
(:Document {doc_id, title, source: 'upload'})   # 法令ではないアップロード資料

(:Law)-[:HAS_ARTICLE]->(:Article)
(:Article)-[:NEXT]->(:Article)
(:Article)-[:REFERS_TO {raw_span, ref_type}]->(:Article | :Law)
(:Article)-[:APPLIES_MUTATIS_MUTANDIS]->(:Article)   # 準用
(:Law)-[:DELEGATES_TO]->(:Law)                       # 法律 → 施行令 → 施行規則
(:Article)-[:DELEGATES_TO]->(:Article)
(:Article)-[:DEFINES]->(:Term {name, body})
(:Term)-[:DEFINED_IN]->(:Article)
```

### Qdrant（ベクトル）

コレクション `articles` の各ポイント（チャンク）に、denseベクトルとbm25 sparseベクトルを併せて格納します。

```python
client.create_collection(
    "articles",
    vectors_config={"dense": VectorParams(size=768, distance=Distance.COSINE)},
    sparse_vectors_config={"bm25": SparseVectorParams(modifier=Modifier.IDF)},
)
# bm25: Sudachi（core辞書）で分かち書きし、条・項・号の前の漢数字を算用数字に変換。
#       文書側の値は tf を BM25式（k1=1.2、b=0.75、avgdl=100）で計算し、クエリ側は 1.0/トークン。
# payload: chunk_uid, article_uid, law_id, article_key, para_num, proviso,
#          revision_id, enforcement_date, law_type, is_current, text
```

### PostgreSQL（メタデータ）

文書（ハッシュ、出典、状態）、取り込みジョブ、法令バージョン、引用情報（`legal_refs`）を保持します。QdrantとNeo4jの整合を取るための起点となるデータベースです。

---

## 画面構成

| 画面 | 内容 |
|---|---|
| 質問応答（トップ） | 質問入力、根拠条文の一覧（出典ラベル・各経路の順位を表示）、出典付き回答のストリーミング表示、関連グラフの表示 |
| データ取り込み | ファイルアップロード（XML / PDF / DOCX / TXT）、`law_id` 指定でのe-Gov取り込み、ZIP一括取り込み |
| 進捗 | 取り込みジョブの一覧と状態・進捗の確認 |
| 法令一覧・条文表示 | 取り込み済み法令と条文の閲覧、条文ページから関連グラフを表示 |

---

## APIとCLI

主なAPI（プレフィックスは `/api`、ドキュメントは `/api/docs`）は次のとおりです。

| メソッド・パス | 内容 |
|---|---|
| `GET /api/health`、`GET /api/status` | ヘルスチェックとLLM等の設定状態 |
| `POST /api/search` | 意図分類のあと検索のみ（JSONで根拠条文・`relevance_noul`・サブグラフを返却。挨拶等は `intent` と固定文） |
| `POST /api/ask` | 意図分類＋検索＋関連度＋回答生成（SSE：`retrieval` → `token` … → `done`。`done` に `guard`） |
| `POST /api/ingest/upload`、`POST /api/ingest/egov`、`POST /api/ingest/bulk`、`POST /api/ingest/rebuild-links` | ファイル取り込み、e-Gov取り込み、ZIP一括取り込み、グラフリンク再構築 |
| `GET /api/jobs`、`GET /api/jobs/{job_id}` | ジョブ一覧・詳細 |
| `GET /api/laws`、`GET /api/laws/{law_id}`、`GET /api/articles/graph`、`GET /api/graph/stats` | 法令・条文・グラフの取得 |

CLI（`jplegal` コマンド、Typer製）には `init`、`ingest-egov`、`ingest-bulk`、`ingest-file`、`rebuild-links`、`reindex-sparse`、`search`、`eval` などがあり、`docker compose exec api jplegal ...` の形で実行します。

---

## クイックスタート

動作要件：Docker Engine 24以上＋Compose v2。メモリは最低8GB程度（model-serverがCPUで約3GB、Neo4jが約2GB）を想定しています。GPUを使う場合はNVIDIA Container Toolkitが必要です。

```bash
cp .env.example .env           # POSTGRES_PASSWORD、NEO4J_PASSWORD、LLM設定を変更する
docker compose up -d --build   # CPUで起動
# GPU（model-server用）で起動する場合：
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build

docker compose ps                    # 全サービスが healthy になるまで待つ（model-server初回はモデルのダウンロードで1〜3分）
docker compose logs -f ollama-pull   # Ollamaが OLLAMA_MODEL（llama3.2、約2GB）を初回ダウンロードし、完了後にジョブが終了する
```

起動後、ブラウザで `http://<サーバーのアドレス>:8080` を開きます。

サンプル法令（労働基準法、施行規則、労働契約法など）をe-Gov 法令APIから取り込みます。

```bash
make seed        # = docker compose exec api jplegal ingest-egov --file /app/config/laws.yaml
```

画面の「データ取り込み」から、XML（e-Gov）/ PDF / DOCX / TXTのアップロード、`law_id` の指定、XML一括ダウンロードのZIP取り込みも行えます。進捗は画面「進捗」で確認します。

---

## LLMの設定

回答生成はLiteLLM経由で行うため、環境変数（`LLM_MODEL`、`LLM_API_BASE`、`LLM_API_KEY`）の変更だけでモデルを切り替えられます。`LLM_MODEL` を空にすると回答生成は行わず、検索結果（根拠条文）のみを返します。

### デフォルト：Docker Compose内のOllama

```text
OLLAMA_MODEL=llama3.2               # ollama-pull ジョブがダウンロードするモデル
LLM_MODEL=ollama_chat/llama3.2      # 「ollama_chat/」＋同じモデル名
LLM_API_BASE=http://ollama:11434    # サービス名で指定する（localhostではない）
LLM_NUM_CTX=16384                   # Ollamaのデフォルトは2048トークンでプロンプトが切れるため必須
```

- モデルの変更は `OLLAMA_MODEL` と `LLM_MODEL` を揃えて書き換え、`docker compose up -d` を実行します（`ollama-pull` が新しいモデルを取得します）。手動取得は `make ollama-pull MODEL=qwen2.5:7b`、一覧は `make ollama-list` です。
- `llama3.2`（3B）は軽量ですが日本の法令文には弱めです。メモリに余裕があれば `qwen2.5:7b` / `qwen2.5:14b` を推奨します。
- GPUは `make up-gpu` でmodel-serverとollamaの両方に割り当てます。**macOS版Docker DesktopではコンテナからGPUを利用できない**ため、Mac上ではDocker内OllamaはCPU動作で低速です。高速化したい場合は後述のネイティブOllamaを使ってください。
- Ollamaは内部ネットワーク内のみで公開され、外部ポートは開きません（Ollama自体に認証機能がないため）。ホストからデバッグする場合は `make up-dev` で `127.0.0.1:11434` に公開されます。

### 外部LLMを使う場合

Ollamaサービスを起動せずに使います。

```bash
make up-no-ollama   # ollama を起動しないでスタックを起動
```

vLLMを別途起動する例（同一マシンまたはGPUマシン）：

```bash
docker run -d --name vllm --gpus all -p 8001:8000 --ipc=host \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:latest --model Qwen/Qwen3-32B --reasoning-parser qwen3 --api-key my-secret
```

```text
LLM_MODEL=hosted_vllm/Qwen/Qwen3-32B
LLM_API_BASE=http://host.docker.internal:8001/v1   # 同一マシンの場合。別マシンはそのIPを指定
LLM_API_KEY=my-secret
```

ホスト上のネイティブOllamaを使う場合は `LLM_API_BASE=http://host.docker.internal:11434` とし、LinuxではOllama側に `OLLAMA_HOST=0.0.0.0:11434` の設定が必要です（ループバック以外でも待ち受けるため）。

`.env` を変更した後は `docker compose restart` ではなく `docker compose up -d api worker` を実行してください（restartでは `.env` が再読み込みされません）。なお `/api/status` の `"llm": {"ok": true}` は「設定済み」を示すだけなので、実際の接続はUIから1件質問して確認してください。

---

## 評価結果

`make eval` で、労働分野6法令を対象に、単一条文で答えられる20問（`backend/eval/queries.jsonl`）と、複数条文が必要なmulti-hop 38問（`backend/eval/queries_multihop.jsonl`）を測定しています。条件はCPU、`RERANK_TOP_N=10`、`RERANK_MAX_CHARS=800` です。

| 構成 | 20問（単一条文）R@10 | 同 MRR@10 | 同 All@10 | 38問（multi-hop）R@10 | 同 MRR@10 | 同 All@10 |
|---|---|---|---|---|---|---|
| dense | 0.933 | 0.892 | 0.900 | 0.816 | 0.834 | 0.658 |
| bm25 | 0.933 | 0.789 | 0.900 | 0.750 | 0.838 | 0.526 |
| hybrid（RRF） | 0.983 | 0.882 | 0.950 | 0.842 | 0.864 | 0.711 |
| hybrid（DBSF） | 0.983 | 0.907 | 0.950 | 0.842 | 0.876 | 0.711 |
| dense + graph | 0.950 | 0.892 | 0.950 | 0.803 | 0.834 | 0.632 |
| hybrid（DBSF）+ graph | **1.000** | 0.907 | **1.000** | 0.882 | 0.876 | 0.789 |
| dense + rerank | 0.933 | 0.925 | 0.900 | 0.816 | **0.890** | 0.658 |
| dense + graph + rerank | 0.933 | 0.925 | 0.900 | 0.882 | 0.864 | 0.789 |
| hybrid（RRF）+ graph + rerank | 0.983 | **0.975** | 0.950 | 0.908 | 0.858 | 0.842 |
| **hybrid（DBSF）+ graph + rerank（デフォルト）** | 0.983 | **0.975** | 0.950 | **0.921** | 0.858 | **0.868** |

- `All@10` は「必要な条文をすべて上位10件以内に取得できた質問の割合」です。
- 評価セットはまだ小規模（計58問）で、multi-hopでの0.026の差は約1問分に相当します。
- 取りこぼしの主因は、平均賃金（労働基準法第12条）のように用語定義経由の参照でした。`:Term`（「…とは…をいう」）で定義条文を足しますが、**58問は労働6法令に偏っており、DBSF vs RRF などの差 0.026 は約1問分**です。ハイパーパラメータの確定には使いません。
- 追加の罠セット `backend/eval/queries_traps.jsonl`（根拠なし、口語、定義語、施行日依存）を人間評価・引用忠実性の確認用に置いています。Recallだけでは測れません。

---

## 性能に関する注意

- 2 vCPU・GPUなしの環境での実測では、約250条文の埋め込みに約6分、dense＋graph検索は1回あたり約0.3〜0.5秒、20件の長い条文のリランクに約40秒かかりました。
- 本番運用ではmodel-serverをGPUで動かすことを推奨します（`make up-gpu`）。
- CPUで動かす場合は `RERANK_TOP_N`（例：10）と `RERANK_MAX_CHARS`（例：800）を下げるか、UIでリランクを無効化してください。

---

## 環境変数

設定はすべて `.env`（雛形は `.env.example`）で行います。主な項目は次のとおりです。

| 分類 | 主な変数 | 内容 |
|---|---|---|
| 公開ポート | `WEB_BIND`、`WEB_PORT` | Nginxの待ち受けアドレスとポート（デフォルト `0.0.0.0:8080`） |
| 認証情報 | `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`、`NEO4J_PASSWORD` | **本番では必ず変更**。Neo4jのヒープ／ページキャッシュは `NEO4J_HEAP`、`NEO4J_PAGECACHE` |
| LLM | `OLLAMA_MODEL`、`LLM_MODEL`、`LLM_API_BASE`、`LLM_API_KEY`、`LLM_NUM_CTX`、`LLM_TIMEOUT` | LiteLLM経由の回答生成設定。`LLM_MODEL` が空なら検索のみ |
| Jev（TypeSafe） | `TYPESAFE_API_KEY`、`TYPESAFE_API_BASE`、`JEV_MODEL`、`JEV_TIMEOUT`、`JEV_INTENT_MIN_CONFIDENCE`、`JEV_RELEVANCE_ENABLED`、`JEV_RELEVANCE_MIN_NOUL` | 意図分類（Choice）と条文関連度（Noul）。キー未設定時は検索へフォールバック |
| モデルサーバー | `MODEL_DEVICE`、`MAX_SEQ_LENGTH`、`HF_HUB_OFFLINE`、`PRELOAD_MODELS` | デバイス選択（空なら自動）、最大系列長、オフライン動作、ビルド時のモデル同梱 |
| 検索 | `DENSE_TOP_K`、`SEED_K`、`GRAPH_MAX`、`GRAPH_MAX_IN_DEGREE`、`GRAPH_SLOTS`、`FUSION_MODE`、`FINAL_K`、`KEEP_REVISIONS` | 第1段階の取得件数、グラフ展開のseed数と入次数上限、融合方式、最終件数、旧改正の保持 |
| リランク | `RERANK_ENABLED`、`RERANK_TOP_N`、`RERANK_MAX_CHARS` | リランクの有効化、対象件数、1件あたりの最大文字数 |
| BM25 | `SPARSE_ENABLED`、`HYBRID_FUSION`、`SUDACHI_DICT`、`BM25_K1`、`BM25_B`、`BM25_AVG_LEN` | sparse検索の有効化、融合方式（`dbsf` / `rrf`）、Sudachi辞書、BM25パラメータ。変更時は `make reindex-sparse` が必要 |
| e-Gov | `EGOV_API_BASE`、`EGOV_BULK_URL`、`EGOV_MIN_INTERVAL_SEC`、`ENABLE_DAILY_UPDATE` | 法令APIの接続先、リクエスト間隔（システム全体で共有）、日次更新の有効化 |
| 内部ミラー等 | `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY`、`PIP_INDEX_URL`、`TORCH_INDEX_URL`、`NPM_REGISTRY`、各 `*_IMAGE` | 社内プロキシ、PyPI / npmミラー、ベースイメージの差し替え |

---

## エアギャップ環境（オフライン環境）

インターネットに接続できるマシンで事前に準備します。

```bash
# 1. イメージをビルドし、Ruri v3モデルをmodel-serverイメージに同梱する
PRELOAD_MODELS=true docker compose build
docker compose pull qdrant neo4j postgres redis ollama
make save-images                       # → jplegal-images.tar
make up && make ollama-export          # OLLAMA_MODELを取得して梱包 → ollama_models.tgz

# 2. 法令データ： https://laws.e-gov.go.jp/bulkdownload/ からZIP（全法令XML、約285MB）を取得する
```

オンプレミスのサーバー側では次のように取り込みます。

```bash
make load-images
echo "HF_HUB_OFFLINE=1" >> .env
make ollama-import                     # ollama_models.tgz をボリュームへ展開（up の前に実行）
docker compose up -d                   # --build は不要
cp all.zip ./data/import/all.zip       # このディレクトリは api / worker に /data/import として読み取り専用マウントされる
make bulk ZIP=/data/import/all.zip     # またはUIの「XML一括（bulk）」タブから取り込む
```

社内のレジストリやPyPI / npmミラーを使う場合は、`.env` の `PYTHON_IMAGE`、`NODE_IMAGE`、`PIP_INDEX_URL`、`TORCH_INDEX_URL`、`NPM_REGISTRY` などを指定します。

---

## e-Gov 法令APIの利用制限

e-Gov 法令API v2はAPIキー不要で、公式のレート制限は公表されていません。本システムではシステム全体で **1秒あたり1リクエスト** に自己制限しています（Redis上の共有ロックで制御し、`EGOV_MIN_INTERVAL_SEC` で調整可能）。429 / 5xx応答時はバックオフ付きでリトライします。大量の法令を取り込む場合は、APIを法令ごとに叩くのではなく、XML一括ダウンロードのZIPを使うことを推奨します。

---

## よく使うコマンド

| コマンド | 内容 |
|---|---|
| `make up` / `make up-gpu` / `make up-dev` | スタックの起動（通常 / GPU / デバッグポート公開） |
| `make up-no-ollama` | Ollamaを起動せずにスタックを起動（外部LLM利用時） |
| `make ollama-pull MODEL=...` / `make ollama-list` | Ollamaモデルの取得 / 一覧 |
| `make logs` | api、worker、model-server、ollamaのログ表示 |
| `make seed` | サンプル法令セットをe-Govから取り込み |
| `make bulk ZIP=...` | ZIP（XML一括ダウンロード）から取り込み |
| `make eval` / `make eval-quick` | 2種類の評価セットで構成別のRecall / MRR / nDCG / All@10を測定（`eval-quick` はリランク構成を省略） |
| `make reindex-sparse` | 取り込み済みデータにBM25を計算（旧バージョンからの移行、または `BM25_*` 変更時） |
| `docker compose exec api jplegal search "36協定" --stage sparse` | 1経路だけを試す（`dense` / `sparse` / `hybrid`） |
| `docker compose exec api jplegal search "残業代の割増率"` | CLIから検索を試す |
| `docker compose exec api jplegal rebuild-links` | 法令追加後にグラフの辺を再構築 |
| `make test` | バックエンドのユニットテスト |

---

## ディレクトリ構成

```text
backend/                 Python 3.12（uv）、パッケージ jplegal
  Dockerfile.api、Dockerfile.worker
  src/jplegal/
    api/                 FastAPIルート（/api/ingest、/api/jobs、/api/laws、/api/search、/api/ask SSE）
    worker/              arqタスク
    ingest/              e-Gov XML / PDF / DOCXパーサー、chunker、引用抽出、リンカー
    retrieval/           クエリ書き換え（口語→法令用語）+ intent（Jev）+ dense/BM25 + graph → 融合 → リランク → relevance（Jev）→ LLM → guardrails
    stores/              Qdrant、Neo4j
    clients/             e-Gov API（レート制限）、model-server、LiteLLM、Jev（TypeSafe）
    db/                  SQLAlchemyモデル（PostgreSQL）
    core/                設定（環境変数）、共通モデル、コンテナ
  config/laws.yaml       サンプル法令リスト
  eval/queries.jsonl             単一条文で答えられる20問
  eval/queries_multihop.jsonl    2〜3条文が必要な38問（法律＋委任先の施行規則・政令）
  prompts/answer_ja.txt  回答生成用プロンプト
  tests/
services/model-server/   FastAPI + sentence-transformers（Ruri v3）
web/                     Next.js 16（静的エクスポート）+ Tailwind v4、Nginx設定
data/import/             XML一括ZIPの配置場所（api / workerへ読み取り専用マウント）
deploy/                  EC2ブートストラップ、リモートデプロイのスクリプト
docs/                    技術スタック・アーキテクチャ、CI/CD手順
docker-compose.yml       メインのスタック定義
docker-compose.gpu.yml   GPU用オーバーライド
docker-compose.dev.yml   デバッグポート公開用オーバーライド
docker-compose.prod.yml  EC2本番用オーバーライド（イメージpullのみ）
```

---

## ローカル開発（Dockerなし）

```bash
cd backend && uv sync --group dev && uv run pytest -q
# インフラだけDockerで起動する：
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d qdrant neo4j postgres redis model-server
uv run uvicorn jplegal.api.main:app --reload --port 8000
uv run arq jplegal.worker.tasks.WorkerSettings

cd web && npm ci && NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```

`npm run dev` でAPIとオリジンが異なる場合は、API側に `CORS_ORIGINS=http://localhost:3000` を設定してください。

---

## CI/CDとEC2へのデプロイ

GitHub ActionsによるCI（プルリクエスト時）、GHCRへのイメージビルド、EC2へのDocker Composeデプロイの手順は [docs/02-ci-cd-github-actions-ec2.md](docs/02-ci-cd-github-actions-ec2.md) を参照してください。本番では `docker-compose.prod.yml` を重ね、サーバー上ではビルドせず、GHCRから取得したイメージ（`IMAGE_TAG` にGitのSHA）で起動します。EC2の初期構築とリモートデプロイには `deploy/ec2-bootstrap.sh` と `deploy/remote-deploy.sh` を使います。

---

## ロードマップ

| フェーズ | 内容 |
|---|---|
| **P0（完了）** | e-Gov API / 一括XML / アップロードによる取り込み、構造・引用・準用・委任のグラフ、Qdrant dense＋Neo4j展開＋slots／リランク、`/ask` ストリーミング、Next.js画面（質問応答、取り込み、進捗、法令・条文とグラフ表示）、Dockerオンプレミス構成、評価セット20問 |
| **P1（進行中）** | ✔ multi-hop評価セット　✔ BM25＋DBSF　✔ Jev Choice/Noul　✔ 引用ガードレール（項まで照合）　✔ 口語→法令用語（辞書＋任意LLM）　✔ 項単位チャンク　✔ 委任を first-class 検索　✔ `:Term` 定義語　✔ Qdrant `is_current`　☐ PDF / DOCXアップロードの安定化　☐ as-of（施行日で完全に条文を切り替える）　☐ `/ingest` `/ask` の認証・レート制限　☐ 店舗間の定期対査 |
| **P2** | 定義語の拡充、主体・法的概念、グラフのレビュー画面、引用忠実性の人手評価 |
| **P3** | Leidenコミュニティ＋コミュニティレポート（法令は構造が既にあるため優先度は低い） |
| **P4** | 改正施行日による完全なバージョン管理、判例・通達、TLS、Langfuse、LiteLLM Proxy |

---

## 制限事項・リスク

- 「同法」「同条」のような文脈依存の引用の解決は誤りやすいため、解決できなかった引用をログと画面で確認できるようにしています。
- Qdrant（payload本文）・Neo4j（条文text）・PostgreSQL に本文が三重保存されます。同期は取り込みパイプライン経由のみで、定期対査ジョブはありません。
- 附則はデフォルトで取り込みません（`INCLUDE_SUPPL_PROVISIONS`）。施行日はペイロードに保存し回答に出しますが、検索フィルタの as-of にはまだ使いません。
- 日本語PDF（縦書き、スキャン画像）は未対応です。テキストレイヤーを持つPDFのみを対象としています。
- 評価セットは労働6法令・58問で小さく、構成比較を過信しないでください。罠セットと人手の引用忠実性評価が必要です。
- 出力ガードレールは引用の粒度と免責文までです。正しい条文を引きつつ内容を誤って要約するケースは検知しません。
- `/ingest` と `/ask` に認証はありません。公開面は web:8080 です。Compose 内の Redis / Qdrant / Neo4j は TLS なしです。
- model-server は推論をセマフォ1本で直列化し、`MAX_SEQ_LENGTH` デフォルトは 2048（Ruri は 8192 まで対応）。CPU リランク約20件で数十秒かかります。
- Jev は外部 API です。エアギャップ環境では `TYPESAFE_API_KEY` を空のままにし、すべての質問が RAG に入ります。
- UI の既定言語は日本語です。`react-force-graph-2d` は `dynamic(..., { ssr: false })` で読み込みます。

---

## データの著作権・出典表示

法令データはe-Gov法令検索（デジタル庁）から、[公共データ利用規約（PDL1.0）](https://laws.e-gov.go.jp/terms/) に基づいて取得しています。表示の際は出典の明記が必要です（例：「出典：e-Gov法令検索（https://laws.e-gov.go.jp/）」）。UIのフッターには出典を表示しています。

本システムの回答は法的助言ではありません。実務判断の前には、必ず原文の法令を確認してください。
