#!/bin/bash
# NDN Server 停止脚本

PID_FILE="${NDN_PID_FILE:-server.pid}"

if [ ! -f "$PID_FILE" ]; then
    echo "PID file not found: $PID_FILE"
    echo "Server may not be running"
    exit 1
fi

PID=$(cat "$PID_FILE")

if ! ps -p "$PID" > /dev/null 2>&1; then
    echo "Process $PID is not running"
    rm -f "$PID_FILE"
    exit 1
fi

echo "Stopping NDN Server (PID: $PID)..."
kill "$PID"

# 等待进程结束
for i in {1..10}; do
    if ! ps -p "$PID" > /dev/null 2>&1; then
        echo "Server stopped successfully"
        rm -f "$PID_FILE"
        exit 0
    fi
    sleep 1
done

# 如果还没停止，强制杀死
if ps -p "$PID" > /dev/null 2>&1; then
    echo "Force killing server..."
    kill -9 "$PID"
    rm -f "$PID_FILE"
    echo "Server force stopped"
fi

