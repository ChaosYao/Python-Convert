#!/bin/bash
# NDN Server 启动脚本
# 用于在远程服务器上启动 NDN Server

set -e

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 进入项目目录
cd "$PROJECT_ROOT"

# 激活虚拟环境（如果存在）
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

# 配置文件路径（可通过环境变量覆盖）
CONFIG_FILE="${NDN_CONFIG_FILE:-config.yaml}"

# 日志文件路径
LOG_DIR="${NDN_LOG_DIR:-logs}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/server_$(date +%Y%m%d_%H%M%S).log"

# PID 文件路径
PID_FILE="${NDN_PID_FILE:-server.pid}"

# 检查是否已经在运行
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Server is already running with PID $OLD_PID"
        exit 1
    else
        echo "Removing stale PID file"
        rm -f "$PID_FILE"
    fi
fi

# 启动 Server
echo "Starting NDN Server..."
echo "Config file: $CONFIG_FILE"
echo "Log file: $LOG_FILE"
echo "PID file: $PID_FILE"

# 使用 nohup 在后台运行
nohup python -m python_project server \
    ${CONFIG_FILE:+"--config=$CONFIG_FILE"} \
    > "$LOG_FILE" 2>&1 &

# 保存 PID
echo $! > "$PID_FILE"
PID=$(cat "$PID_FILE")

echo "Server started with PID: $PID"
echo "Logs: $LOG_FILE"
echo "To stop: kill $PID or use stop_server.sh"

# 等待一下，检查是否启动成功
sleep 2
if ps -p "$PID" > /dev/null 2>&1; then
    echo "Server is running successfully"
    exit 0
else
    echo "Server failed to start. Check log: $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi

