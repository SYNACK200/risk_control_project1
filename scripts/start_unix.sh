#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[1/4] 读取 .env ..."
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
else
  echo "未找到 .env，将使用系统环境变量；可先复制 .env.example 为 .env"
fi
APP_PORT="${APP_PORT:-8000}"

echo "[2/4] 准备 Python 环境 ..."
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install -q -U pip
python -m pip install -q -r backend/requirements.txt

echo "[3/4] 检查前端构建产物 ..."
if [ ! -f frontend/dist/index.html ]; then
  echo "  构建借款侧前端（需要 Node.js）..."
  (cd frontend && npm ci && npm run build:app)
fi
if [ ! -f frontend-admin/dist/index.html ]; then
  echo "  构建银行侧前端（需要 Node.js）..."
  (cd frontend-admin && npm ci && npm run build:bank)
fi

echo "[4/4] 启动服务：http://127.0.0.1:${APP_PORT}/ （借款侧） /bank/（银行侧）"
exec python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port "${APP_PORT}"
