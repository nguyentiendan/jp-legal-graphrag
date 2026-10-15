# CI/CD: GitHub Actions → GHCR → EC2 (Docker Compose)

## Luồng tổng quan

```
PR ───────────► CI: ruff + pytest │ tsc + next build │ compose config + shellcheck │ docker build thử (4 image)

push main ────► CI (tái sử dụng ci.yml)
                 └► build & push 4 image lên GHCR (api, worker, web, model-server), tag sha-<12 ký tự> + latest
                     └► SSH vào EC2: chép compose bundle, (tuỳ chọn) ghi .env từ secret
                         └► deploy/remote-deploy.sh: pull → up -d --no-build → chờ api/web healthy
                             └► fail → tự rollback về tag trước, job đỏ
```

Chạy tay: Actions → Deploy to EC2 → Run workflow. Nhập `image_tag` (ví dụ `sha-63cfead1a2b3`) để deploy lại / rollback mà không build.

## Các file đã thêm

| File | Vai trò |
|---|---|
| `.github/workflows/ci.yml` | CI cho PR, đồng thời là reusable workflow cho deploy |
| `.github/workflows/deploy-ec2.yml` | Build/push GHCR + deploy EC2 |
| `docker-compose.prod.yml` | Override production: bỏ `build` (`!reset`), chỉ pull image; giới hạn log |
| `deploy/remote-deploy.sh` | Chạy trên EC2: login GHCR qua stdin, pull, up, healthcheck, rollback, dọn image cũ |
| `deploy/ec2-bootstrap.sh` | Cài Docker + Compose plugin lần đầu trên EC2 (Amazon Linux 2023 / Ubuntu) |

> Workflow đặt ở root repo; app (backend/, web/, services/, docker-compose*.yml) cũng nằm ở root.

## Bước 1 — Chuẩn bị EC2

Cấu hình gợi ý (CPU, có Ollama + Neo4j + model-server Ruri v3): tối thiểu 4 vCPU / 16 GB RAM, EBS gp3 ≥ 60 GB.
Tắt Ollama (`ENABLE_OLLAMA=false`, dùng LLM ngoài) thì 8 GB RAM có thể đủ cho thử nghiệm.
GPU: dùng AMI có sẵn NVIDIA driver + NVIDIA Container Toolkit, rồi set `EC2_GPU=true`.

Security Group:
- Inbound `WEB_PORT` (mặc định 8080) hoặc 80/443 nếu đặt ALB / reverse proxy phía trước.
- Inbound 22 cho GitHub Actions. Runner của GitHub không có IP cố định, nên hoặc mở 22 rộng (chỉ cho phép key-based auth), hoặc dùng self-hosted runner / VPN. Các port DB (5432, 7687, 6333, 6379, 11434) không được publish ra host.

Cài Docker:

```bash
# repo private → copy script từ máy local lên EC2 (Amazon Linux: user ec2-user, Ubuntu: user ubuntu)
scp deploy/ec2-bootstrap.sh ec2-user@<EC2_HOST>:/tmp/
ssh ec2-user@<EC2_HOST> 'sudo APP_DIR=/opt/jplegal DEPLOY_USER=ec2-user bash /tmp/ec2-bootstrap.sh'
# đăng xuất rồi SSH lại để group docker có hiệu lực
```

Tạo SSH key riêng cho deploy (trên máy cá nhân):

```bash
ssh-keygen -t ed25519 -f gha_ec2 -N "" -C "github-actions-deploy"
ssh-copy-id -i gha_ec2.pub ec2-user@<EC2_HOST>     # hoặc thêm gha_ec2.pub vào ~/.ssh/authorized_keys
ssh-keyscan -H <EC2_HOST>                           # copy output → secret EC2_KNOWN_HOSTS
```

## Bước 2 — Cấu hình GitHub

Settings → Environments → tạo `production` (có thể bật Required reviewers để duyệt tay trước mỗi lần deploy).

Secrets (Environment `production` hoặc Repository):

| Secret | Bắt buộc | Ghi chú |
|---|---|---|
| `EC2_HOST` | có | Public IP / DNS (nên dùng Elastic IP) |
| `EC2_USER` | có | `ec2-user` / `ubuntu` |
| `EC2_SSH_KEY` | có | Nội dung private key `gha_ec2` |
| `EC2_KNOWN_HOSTS` | nên có | Output `ssh-keyscan -H`; thiếu thì workflow tự keyscan (kém an toàn hơn) |
| `EC2_SSH_PORT` | không | Mặc định 22 |
| `ENV_FILE` | không | Toàn bộ nội dung `.env` production. Không set thì tự tạo `/opt/jplegal/.env` trên server |

Variables:

| Variable | Mặc định | Ghi chú |
|---|---|---|
| `EC2_APP_DIR` | `/opt/jplegal` | Thư mục app trên EC2 |
| `EC2_PLATFORM` | `linux/amd64` | `linux/arm64` cho Graviton (build native trên runner ARM) |
| `EC2_GPU` | `false` | `true`: model-server build torch CUDA 12.8 và thêm `docker-compose.gpu.yml` |
| `ENABLE_OLLAMA` | `true` | `false`: `--scale ollama=0 --scale ollama-pull=0` |
| `HEALTH_TIMEOUT` | `900` | Giây chờ healthy; lần đầu model-server phải tải model nên sẽ lâu |
| `APP_URL` | — | Hiển thị link trên trang Environment |

`.env` production: lấy từ `.env.example`, bắt buộc đổi `POSTGRES_PASSWORD`, `NEO4J_PASSWORD`. Không cần sửa `IMAGE_PREFIX` / `IMAGE_TAG` vì script ghi đè qua `.env.deploy`.

Quyền GHCR: workflow dùng `GITHUB_TOKEN` (permission `packages: write`) để push, và truyền token ngắn hạn qua stdin để EC2 pull rồi `docker logout` ngay sau đó. Khi container restart không cần pull lại nên không phải lưu credential trên server.

## Bước 3 — Deploy

- Merge / push vào `main` → tự chạy.
- Lần đầu: model-server tải ~1–2 GB model Ruri vào volume `models`, Ollama tải `OLLAMA_MODEL`. Nạp dữ liệu mẫu sau khi lên: `ssh ec2-user@host 'cd /opt/jplegal && docker compose --env-file .env --env-file .env.deploy -f docker-compose.yml -f docker-compose.prod.yml exec api jplegal ingest-egov --file /app/config/laws.yaml'`.

## Vận hành trên server

```bash
cd /opt/jplegal
alias dcp='docker compose --env-file .env --env-file .env.deploy -f docker-compose.yml -f docker-compose.prod.yml'
dcp ps
dcp logs -f --tail=100 api worker model-server
cat .env.deploy .env.deploy.prev        # tag hiện tại / tag trước
# rollback tay:
IMAGE_PREFIX=ghcr.io/nguyentiendan/jplegal IMAGE_TAG=<tag-cũ> bash deploy/remote-deploy.sh   # cần docker login nếu package private
```

## Lựa chọn nâng cao

- Không muốn mở port 22: thay bước SSH bằng `aws ssm send-command` với OIDC (`aws-actions/configure-aws-credentials`) và IAM role cho EC2, hoặc chạy self-hosted runner ngay trên EC2.
- Dùng ECR thay GHCR: đổi `REGISTRY`, bước login sang `aws-actions/amazon-ecr-login`, EC2 pull bằng instance role.
- HTTPS: đặt ALB + ACM phía trước `WEB_PORT`, hoặc thêm Caddy/Traefik.
