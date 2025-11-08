#!/bin/bash
# 检查 Server 和 Client 的运行状态

check_process() {
    local name=$1
    local pid_file=$2
    
    if [ -f "$pid_file" ]; then
        PID=$(cat "$pid_file")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "$name: Running (PID: $PID)"
            return 0
        else
            echo "$name: Not running (stale PID file: $pid_file)"
            rm -f "$pid_file"
            return 1
        fi
    else
        echo "$name: Not running"
        return 1
    fi
}

echo "NDN Service Status:"
echo "=================="
check_process "Server" "${NDN_PID_FILE:-server.pid}"
check_process "Client" "${NDN_PID_FILE:-client.pid}"

