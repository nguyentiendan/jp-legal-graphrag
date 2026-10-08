COMPOSE ?= docker compose
GPU_FILES = -f docker-compose.yml -f docker-compose.gpu.yml
DEV_FILES = -f docker-compose.yml -f docker-compose.dev.yml

.PHONY: env build up up-gpu up-dev down logs ps init seed bulk eval test save-images load-images

env:            ## tạo .env từ mẫu
	@test -f .env || cp .env.example .env && echo ".env ready"

build:          ## build tất cả image
	$(COMPOSE) build

up:             ## chạy stack (CPU)
	$(COMPOSE) up -d --build

up-gpu:         ## chạy stack với GPU cho model-server
	$(COMPOSE) $(GPU_FILES) up -d --build

up-dev:         ## chạy stack + mở cổng debug ra 127.0.0.1
	$(COMPOSE) $(DEV_FILES) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100 api worker model-server

ps:
	$(COMPOSE) ps

init:           ## tạo schema (API cũng tự tạo khi khởi động)
	$(COMPOSE) exec api jplegal init

seed:           ## nạp bộ luật mẫu (lĩnh vực 労働) từ e-Gov API
	$(COMPOSE) exec api jplegal ingest-egov --file /app/config/laws.yaml

bulk:           ## nạp từ zip đã chép vào volume: make bulk ZIP=/data/raw/bulk/all.zip
	$(COMPOSE) exec api jplegal ingest-bulk --zip $(ZIP)

eval:           ## đo Recall/MRR/nDCG cho dense / dense+graph / +rerank
	$(COMPOSE) exec api jplegal eval --queries /app/eval/queries.jsonl

test:           ## unit test backend (chạy trên máy dev, cần uv)
	cd backend && uv run --group dev pytest -q

save-images:    ## đóng gói image để mang sang máy air-gapped
	docker save -o jplegal-images.tar $$(docker compose config --images)

load-images:
	docker load -i jplegal-images.tar
