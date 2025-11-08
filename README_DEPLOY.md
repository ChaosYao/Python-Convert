# 远程服务器快速启动指南

## 快速开始

### 1. 上传代码到服务器

```bash
# 使用 scp 上传
scp -r python_project root@your-server:/root/

# 或使用 git
ssh root@your-server
git clone <your-repo-url>
cd python_project
```

### 2. 配置环境

```bash
# 进入项目目录
cd /root/python_project

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置 config.yaml

```bash
# 复制示例配置
cp config.yaml.example config.yaml

# 编辑配置文件（根据你的服务器路径修改）
vi config.yaml
```

**重要配置：**
- `ndn.pib_path`: 设置为服务器上的实际路径，如 `/root/.ndn/pib.db`
- `ndn.tpm_path`: 设置为服务器上的实际路径，如 `/root/.ndn/ndnsec-key-file`
- `server.routes`: 设置要注册的路由前缀
- `server.data`: 设置要存储的数据

### 4. 启动服务

#### 方法 1: 使用启动脚本（最简单）

```bash
# 给脚本添加执行权限
chmod +x scripts/*.sh

# 启动 Server
./scripts/start_server.sh

# 启动 Client（如果需要）
./scripts/start_client.sh

# 查看状态
./scripts/status.sh

# 查看日志
tail -f logs/server_*.log
```

#### 方法 2: 使用 systemd（推荐用于生产环境）

```bash
# 创建 systemd 服务文件
sudo vi /etc/systemd/system/ndn-server.service
```

内容：
```ini
[Unit]
Description=NDN Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/python_project
Environment="PATH=/root/python_project/.venv/bin"
ExecStart=/root/python_project/.venv/bin/python -m python_project server --config=/root/python_project/config.yaml
Restart=always
RestartSec=10
StandardOutput=append:/root/python_project/logs/server.log
StandardError=append:/root/python_project/logs/server.error.log

[Install]
WantedBy=multi-user.target
```

然后：
```bash
# 重新加载 systemd
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start ndn-server

# 设置开机自启
sudo systemctl enable ndn-server

# 查看状态
sudo systemctl status ndn-server

# 查看日志
sudo journalctl -u ndn-server -f
```

#### 方法 3: 使用 screen（适合测试）

```bash
# 启动 screen
screen -S ndn-server

# 激活虚拟环境并启动
source .venv/bin/activate
python -m python_project server --config=config.yaml

# 按 Ctrl+A, 然后按 D 退出 screen（服务继续运行）

# 重新连接
screen -r ndn-server
```

### 5. 验证服务运行

```bash
# 检查进程
ps aux | grep python_project

# 查看日志
tail -f logs/server_*.log

# 检查 NDN 路由（如果 NFD 运行）
nfdc route list | grep /yao/test/demo/B
```

## 常用命令

```bash
# 启动 Server
./scripts/start_server.sh

# 停止 Server
./scripts/stop_server.sh

# 重启 Server
./scripts/stop_server.sh && ./scripts/start_server.sh

# 查看状态
./scripts/status.sh

# 查看最新日志
tail -f logs/server_*.log

# 查看所有日志
ls -lt logs/
```

## 环境变量

可以通过环境变量覆盖配置：

```bash
# 指定配置文件
export NDN_CONFIG_FILE=/path/to/config.yaml

# 指定日志目录
export NDN_LOG_DIR=/path/to/logs

# 指定 PID 文件
export NDN_PID_FILE=/path/to/server.pid

# 然后启动
./scripts/start_server.sh
```

## 故障排查

1. **服务无法启动**
   - 检查虚拟环境：`source .venv/bin/activate && which python`
   - 检查依赖：`pip list | grep python-ndn`
   - 检查配置文件：`python -c "import yaml; print(yaml.safe_load(open('config.yaml')))"`
   - 查看错误日志：`tail -f logs/server_*.log`

2. **NDN 网络问题**
   - 检查 NFD 是否运行：`ps aux | grep nfd`
   - 检查 NFD 连接：`nfdc face list`

3. **权限问题**
   - 确保 PIB/TPM 路径存在且有权限：`ls -la /root/.ndn/`

## 详细文档

更多详细信息请参考：`docs/DEPLOYMENT.md`

