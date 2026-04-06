# Docker 构建和使用指南

## 构建镜像

### 基本构建

```bash
docker build -t python-convert:latest .
```

### 指定标签

```bash
docker build -t python-convert:v0.1.0 .
```

## 运行容器

### 基本运行

```bash
docker run -d \
  --name ndn-grpc-sidecar \
  -p 50051:50051 \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  python-convert:latest
```

### 使用环境变量

```bash
docker run -d \
  --name ndn-grpc-sidecar \
  -p 50051:50051 \
  -e MODE=sidecar \
  -e GRPC_SERVER_PORT=50051 \
  -e LOG_LEVEL=INFO \
  -e NDN_PIB_PATH=/home/appuser/.ndn/pib.db \
  -e NDN_TPM_PATH=/home/appuser/.ndn/ndnsec-key-file \
  python-convert:latest
```

### 持久化 NDN 数据

```bash
docker run -d \
  --name ndn-grpc-sidecar \
  -p 50051:50051 \
  -v ndn-data:/home/appuser/.ndn \
  python-convert:latest
```

## 使用 Docker Compose

### 启动服务

```bash
docker-compose up -d
```

### 查看日志

```bash
docker-compose logs -f sidecar
```

### 停止服务

```bash
docker-compose down
```

### 停止并删除数据卷

```bash
docker-compose down -v
```

## Kubernetes 部署

### 基本 Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ndn-grpc-sidecar
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ndn-grpc-sidecar
  template:
    metadata:
      labels:
        app: ndn-grpc-sidecar
    spec:
      containers:
      - name: sidecar
        image: python-convert:latest
        ports:
        - containerPort: 50051
          name: grpc
        env:
        - name: MODE
          value: "sidecar"
        - name: GRPC_SERVER_PORT
          value: "50051"
        - name: LOG_LEVEL
          value: "INFO"
        - name: NDN_PIB_PATH
          value: "/home/appuser/.ndn/pib.db"
        - name: NDN_TPM_PATH
          value: "/home/appuser/.ndn/ndnsec-key-file"
        volumeMounts:
        - name: ndn-data
          mountPath: /home/appuser/.ndn
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
      volumes:
      - name: ndn-data
        emptyDir: {}
```

### 作为 Sidecar 容器

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app-with-sidecar
spec:
  template:
    spec:
      containers:
      # 主容器
      - name: main-app
        image: my-app:latest
        ports:
        - containerPort: 8080
          name: grpc
      
      # Sidecar 容器
      - name: ndn-grpc-sidecar
        image: python-convert:latest
        ports:
        - containerPort: 50051
          name: sidecar-grpc
        env:
        - name: MODE
          value: "sidecar"
        - name: GRPC_SERVER_PORT
          value: "50051"
        - name: GRPC_CLIENT_HOST
          value: "localhost:8080"  # 主容器地址
        volumeMounts:
        - name: ndn-data
          mountPath: /home/appuser/.ndn
      volumes:
      - name: ndn-data
        emptyDir: {}
```

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `MODE` | 运行模式 (`sidecar` 或 `server`) | `sidecar` |
| `GRPC_SERVER_PORT` | gRPC Server 端口 | `50051` |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `NDN_PIB_PATH` | NDN PIB 数据库路径 | `/home/appuser/.ndn/pib.db` |
| `NDN_TPM_PATH` | NDN TPM 目录路径 | `/home/appuser/.ndn/ndnsec-key-file` |
| `GRPC_CLIENT_HOST` | gRPC 客户端地址（用于桥接） | `localhost:50051` |

## 健康检查

容器包含健康检查，每 30 秒检查一次 gRPC 服务器端口是否可访问。

查看健康状态：

```bash
docker ps
# 查看 HEALTHY/UNHEALTHY 状态
```

## 故障排查

### 查看日志

```bash
docker logs ndn-grpc-sidecar
docker logs -f ndn-grpc-sidecar  # 实时日志
```

### 进入容器

```bash
docker exec -it ndn-grpc-sidecar /bin/bash
```

### 检查端口

```bash
docker exec ndn-grpc-sidecar netstat -tlnp | grep 50051
```

### 测试 gRPC 连接

```bash
docker exec ndn-grpc-sidecar python -c "import socket; s = socket.socket(); s.connect(('localhost', 50051)); print('Connected')"
```

## 镜像优化

### 多阶段构建

Dockerfile 使用多阶段构建，减小最终镜像大小：
- Builder 阶段：安装编译依赖和构建 Python 包
- Production 阶段：只包含运行时依赖

### 非 root 用户

容器以非 root 用户 (`appuser`) 运行，提高安全性。

### 层缓存优化

Dockerfile 按照依赖变化频率排序，最大化利用 Docker 层缓存。

