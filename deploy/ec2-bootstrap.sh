#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Chạy 1 lần trên EC2 mới (Amazon Linux 2023 hoặc Ubuntu 22.04/24.04):
#   curl -fsSL <raw-url>/deploy/ec2-bootstrap.sh | sudo APP_DIR=/opt/jplegal DEPLOY_USER=ec2-user bash
# Cài Docker Engine + Compose plugin, tạo thư mục app, thêm user deploy vào group docker.
# ---------------------------------------------------------------------------
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/jplegal}"
DEPLOY_USER="${DEPLOY_USER:-${SUDO_USER:-ec2-user}}"
COMPOSE_VERSION="${COMPOSE_VERSION:-v2.39.4}"

[ "$(id -u)" -eq 0 ] || { echo "Cần chạy bằng sudo/root"; exit 1; }
. /etc/os-release

case "$ID" in
  amzn)
    dnf install -y docker tar gzip
    ARCH="$(uname -m)"
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -fsSL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-${ARCH}" \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
    ;;
  ubuntu|debian)
    apt-get update -y
    apt-get install -y ca-certificates curl tar gzip
    curl -fsSL https://get.docker.com | sh   # docker-ce + compose plugin
    ;;
  *)
    echo "OS $ID chưa hỗ trợ, cài Docker + Compose plugin thủ công"; exit 1 ;;
esac

# log rotate mặc định cho mọi container
mkdir -p /etc/docker
if [ ! -f /etc/docker/daemon.json ]; then
  cat > /etc/docker/daemon.json <<'EOF'
{ "log-driver": "json-file", "log-opts": { "max-size": "20m", "max-file": "5" } }
EOF
fi

systemctl enable --now docker
usermod -aG docker "$DEPLOY_USER"

mkdir -p "$APP_DIR/data/import" "$APP_DIR/deploy"
chown -R "$DEPLOY_USER":"$DEPLOY_USER" "$APP_DIR"

docker --version
docker compose version
echo
echo "Xong. Đăng xuất/đăng nhập lại để $DEPLOY_USER dùng docker không cần sudo."
echo "Tiếp theo: tạo $APP_DIR/.env (từ .env.example) hoặc set secret ENV_FILE trên GitHub."
