# 远程服务器部署指南

本文档说明如何在远程服务器上部署和启动 NDN Server/Client。

## 1. 准备工作

### 1.1 服务器要求
- Python 3.8+
- NDN 网络环境（NFD - NDN Forwarding Daemon）
- 足够的磁盘空间用于日志和配置文件

### 1.2 上传代码到服务器

```bash
# 方法 1: 使用 git
git clone <your-repo-url>
cd python_project

# 方法 2: 使用 scp
scp -r python_project user@server:/path/to/destination/
```

## 2. 环境配置

### 2.1 创建虚拟环境

```bash
cd /path/to/python_project
python3 -m venv .venv
source .venv/bin/activate
```

### 2.2 安装依赖

```bash
pip install -r requirements.txt
```

### 2.3 创建配置文件

```bash
# 复制示例配置
cp config.yaml.example config.yaml

# 编辑配置文件
vi config.yaml
```

**重要配置项：**
- `ndn.pib_path`: PIB 数据库路径（如 `/root/.ndn/pib.db`）
- `ndn.tpm_path`: TPM 目录路径（如 `/root/.ndn/ndnsec-key-file`）
- `mode`: 运行模式（`server` 或 `client`）
- `server.routes`: Server 注册的路由前缀
- `server.data`: Server 存储的数据

## 3. 启动服务

### 3.1 使用启动脚本（推荐）

```bash
# 给脚本添加执行权限
chmod +x scripts/*.sh

# 启动 Server
./scripts/start_server.sh

# 启动 Client
./scripts/start_client.sh

# 查看状态
./scripts/status.sh

# 停止服务
./scripts/stop_server.sh
./scripts/stop_client.sh
```

### 3.2 使用 systemd（生产环境推荐）

创建 systemd 服务文件：

**`/etc/systemd/system/ndn-server.service`:**
```ini
[Unit]
Description=NDN Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/path/to/python_project
Environment="PATH=/path/to/python_project/.venv/bin"
ExecStart=/path/to/python_project/.venv/bin/python -m python_project server --config=/path/to/python_project/config.yaml
Restart=always
RestartSec=10
StandardOutput=append:/path/to/python_project/logs/server.log
StandardError=append:/path/to/python_project/logs/server.error.log

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/ndn-client.service`:**
```ini
[Unit]
Description=NDN Client
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/path/to/python_project
Environment="PATH=/path/to/python_project/.venv/bin"
ExecStart=/path/to/python_project/.venv/bin/python -m python_project client --config=/path/to/python_project/config.yaml
Restart=always
RestartSec=10
StandardOutput=append:/path/to/python_project/logs/client.log
StandardError=append:/path/to/python_project/logs/client.error.log

[Install]
WantedBy=multi-user.target
```

**使用 systemd 管理：**
```bash
# 重新加载 systemd
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start ndn-server
sudo systemctl start ndn-client

# 设置开机自启
sudo systemctl enable ndn-server
sudo systemctl enable ndn-client

# 查看状态
sudo systemctl status ndn-server
sudo systemctl status ndn-client

# 查看日志
sudo journalctl -u ndn-server -f
sudo journalctl -u ndn-client -f

# 停止服务
sudo systemctl stop ndn-server
sudo systemctl stop ndn-client
```

### 3.3 使用 screen/tmux（开发/测试）

```bash
# 使用 screen
screen -S ndn-server
source .venv/bin/activate
python -m python_project server
# 按 Ctrl+A, 然后按 D 退出 screen

# 重新连接
screen -r ndn-server

# 使用 tmux
tmux new -s ndn-server
source .venv/bin/activate
python -m python_project server
# 按 Ctrl+B, 然后按 D 退出 tmux

# 重新连接
tmux attach -t ndn-server
```

### 3.4 直接运行（前台）

```bash
source .venv/bin/activate
python -m python_project server --config=config.yaml
```

## 4. 环境变量配置

可以通过环境变量覆盖配置：

```bash
# 设置配置文件路径
export NDN_CONFIG_FILE=/path/to/config.yaml

# 设置 PIB/TPM 路径
export NDN_PIB_PATH=/root/.ndn/pib.db
export NDN_TPM_PATH=/root/.ndn/ndnsec-key-file

# 设置日志目录
export NDN_LOG_DIR=/path/to/logs

# 设置 PID 文件路径
export NDN_PID_FILE=/path/to/server.pid

# 然后启动
./scripts/start_server.sh
```

## 5. 日志管理

### 5.1 日志位置

- 默认日志目录：`logs/`
- Server 日志：`logs/server_YYYYMMDD_HHMMSS.log`
- Client 日志：`logs/client_YYYYMMDD_HHMMSS.log`

### 5.2 查看日志

```bash
# 实时查看最新日志
tail -f logs/server_*.log

# 查看最近的日志
ls -lt logs/ | head -5

# 搜索日志
grep "ERROR" logs/server_*.log
```

### 5.3 日志轮转

可以使用 `logrotate` 配置日志轮转：

**`/etc/logrotate.d/ndn-server`:**
```
/path/to/python_project/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 root root
}
```

## 6. 监控和维护

### 6.1 检查服务状态

```bash
# 使用脚本
./scripts/status.sh

# 检查进程
ps aux | grep python_project

# 检查端口（如果有）
netstat -tlnp | grep <port>
```

### 6.2 重启服务

```bash
# 使用脚本
./scripts/stop_server.sh
./scripts/start_server.sh

# 使用 systemd
sudo systemctl restart ndn-server
```

## 7. 故障排查

### 7.1 服务无法启动

1. 检查虚拟环境是否正确激活
2. 检查依赖是否安装完整：`pip list`
3. 检查配置文件是否存在且格式正确：`python -c "import yaml; yaml.safe_load(open('config.yaml'))"`
4. 检查 PIB/TPM 路径是否存在且有权限
5. 查看错误日志：`tail -f logs/server_*.log`

### 7.2 NDN 网络问题

1. 检查 NFD 是否运行：`ps aux | grep nfd`
2. 检查 NFD 连接：`nfdc face list`
3. 检查路由：`nfdc route list`

### 7.3 权限问题

```bash
# 确保有权限访问 PIB/TPM 路径
ls -la /root/.ndn/

# 如果权限不足，修改权限
chmod 755 /root/.ndn
chmod 644 /root/.ndn/pib.db
```

## 8. 安全建议

1. **不要使用 root 用户运行**（如果可能）
   - 创建专用用户：`useradd -m -s /bin/bash ndnuser`
   - 使用该用户运行服务

2. **配置文件权限**
   ```bash
   chmod 600 config.yaml  # 仅所有者可读写
   ```

3. **日志文件权限**
   ```bash
   chmod 644 logs/*.log
   ```

4. **防火墙配置**
   - 确保 NDN 相关端口已开放
   - 限制 SSH 访问

## 9. 快速部署脚本

创建一键部署脚本 `deploy.sh`:

```bash
#!/bin/bash
set -e

PROJECT_DIR="/path/to/python_project"
cd "$PROJECT_DIR"

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 创建配置文件（如果不存在）
if [ ! -f config.yaml ]; then
    cp config.yaml.example config.yaml
    echo "Please edit config.yaml before starting the service"
fi

# 创建日志目录
mkdir -p logs

# 设置脚本权限
chmod +x scripts/*.sh

echo "Deployment completed!"
echo "Next steps:"
echo "1. Edit config.yaml"
echo "2. Run: ./scripts/start_server.sh"
```

