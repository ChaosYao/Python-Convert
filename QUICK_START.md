# 快速开始指南

## 问题已修复 ✅

原始错误 `can't find '__main__' module` 已经解决。

## 正确的运行方式

### 方式 1: 使用虚拟环境的 Python（推荐）

```bash
# 确保在项目根目录
cd /Users/yaoqingqi/Yao/github/Python-Convert

# 运行服务器
./venv/bin/python -m python_project server

# 运行客户端
./venv/bin/python -m python_project client
```

### 方式 2: 激活虚拟环境后运行

```bash
# 激活虚拟环境
source venv/bin/activate

# 运行服务器
python -m python_project server

# 运行客户端
python -m python_project client
```

### 方式 3: 使用示例脚本

```bash
# 运行服务器
./venv/bin/python examples/ndn_demo.py server

# 运行客户端
./venv/bin/python examples/ndn_demo.py client
```

### 方式 4: 使用启动脚本

```bash
# 运行服务器
./scripts/start_server.sh

# 运行客户端
./scripts/start_client.sh
```

## 常见问题

### 问题 1: `python: command not found`
**解决**: 使用完整路径 `./venv/bin/python` 或先激活虚拟环境

### 问题 2: `No module named 'python_project'`
**解决**: 确保在项目根目录运行，并且包已安装（`pip install -e .`）

### 问题 3: `can't find '__main__' module`
**解决**: ✅ 已修复！已创建 `src/python_project/__main__.py` 文件

## 验证安装

运行以下命令验证一切正常：

```bash
./venv/bin/python -m python_project
```

应该看到使用说明，而不是错误信息。

