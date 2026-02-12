#!/bin/bash
# 启动前端开发服务器（Linux）
set -e
cd "$(dirname "$0")"

echo "========================================"
echo "  DWG 转切片 - 前端启动"
echo "========================================"
echo ""

if ! command -v node &>/dev/null; then
    echo "[错误] 未找到 Node.js，请先安装 Node.js 18+"
    echo "  Ubuntu/Debian: curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs"
    echo "  或使用 nvm: https://github.com/nvm-sh/nvm"
    exit 1
fi

echo "[1/2] 检查依赖..."
if [ ! -d node_modules ]; then
    echo "  首次运行，正在安装依赖..."
    npm install
else
    echo "  依赖已安装"
fi

echo "[2/2] 启动开发服务器..."
echo ""
echo "========================================"
echo "  前端地址: http://localhost:5173"
echo "  请确保后端已启动: http://localhost:8000"
echo "  按 Ctrl+C 停止"
echo "========================================"
echo ""

exec npm run dev
