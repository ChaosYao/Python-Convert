# 故障排除指南

## 常见错误及解决方案

### 1. `ModuleNotFoundError: No module named 'yaml'`

**错误信息：**
```
ModuleNotFoundError: No module named 'yaml'
```

**原因：**
- 未安装 `pyyaml` 包
- 使用了错误的 Python 环境（系统 Python 而不是虚拟环境）

**解决方案：**

#### 方法 1: 使用安装脚本（推荐）
```bash
./install_deps.sh
```

#### 方法 2: 手动安装
```bash
# 如果使用虚拟环境
source venv/bin/activate  # 或 source .venv/bin/activate
pip install pyyaml

# 或者使用完整路径
./venv/bin/pip install pyyaml
```

#### 方法 3: 安装所有依赖
```bash
# 使用虚拟环境
source venv/bin/activate
pip install -r requirements.txt

# 或使用完整路径
./venv/bin/pip install -r requirements.txt
```

### 2. `can't find '__main__' module`

**错误信息：**
```
can't find '__main__' module in '/path/to/Python-Convert'
```

**原因：**
- 命令格式错误，把目录当作模块运行

**解决方案：**
```bash
# ❌ 错误
python Python-Convert server

# ✅ 正确
python -m python_project server

# 或使用完整路径
./venv/bin/python -m python_project server
```

### 3. `unable to open database file` 或 `no such table: tpmInfo`

**错误信息：**
```
sqlite3.OperationalError: unable to open database file
# 或
sqlite3.OperationalError: no such table: tpmInfo
```

**原因：**
- PIB 数据库路径错误或未初始化
- 配置文件使用了错误的路径（如 `/root/.ndn/pib.db`）

**解决方案：**

#### 步骤 1: 检查配置文件
确保 `config.yaml` 中的路径正确：
```yaml
ndn:
  pib_path: ~/.ndn/pib.db  # 使用 ~ 而不是 /root
  tpm_path: ~/.ndn/ndnsec-key-file
```

#### 步骤 2: 初始化 NDN 数据库
```bash
# 使用 ndnsec 工具初始化
ndnsec key-gen /localhost

# 如果 ndnsec 不可用，可以删除旧数据库让系统重新创建
rm -f ~/.ndn/pib.db
```

#### 步骤 3: 让系统使用默认路径
如果仍有问题，可以删除配置文件中的路径，让系统使用默认值：
```yaml
ndn:
  # pib_path: ~/.ndn/pib.db  # 注释掉
  # tpm_path: ~/.ndn/ndnsec-key-file  # 注释掉
```

### 4. `asyncio.run() cannot be called from a running event loop`

**错误信息：**
```
RuntimeError: asyncio.run() cannot be called from a running event loop
```

**原因：**
- `NDNApp.run_forever()` 内部已经调用了 `asyncio.run()`，而外层代码又使用了 `asyncio.run()`，导致嵌套调用
- 在已有事件循环的环境中运行（如 Jupyter notebook）

**解决方案：**
- ✅ **已修复**：代码已更新，直接调用 `app.run_forever()` 而不使用外层的 `asyncio.run()`
- 如果仍有问题，确保使用最新版本的代码
- 在普通终端中运行，而不是在 Jupyter notebook 中

### 5. 使用错误的 Python 环境

**问题：**
- 系统 Python 没有安装依赖
- 虚拟环境未激活

**解决方案：**

```bash
# 检查当前使用的 Python
which python
python --version

# 激活虚拟环境
source venv/bin/activate  # Linux/Mac
# 或
.venv\Scripts\activate  # Windows

# 验证虚拟环境
which python  # 应该显示 venv/bin/python
pip list  # 应该显示已安装的包
```

## 快速检查清单

运行程序前，请确认：

- [ ] 虚拟环境已创建：`python3 -m venv venv`
- [ ] 虚拟环境已激活：`source venv/bin/activate`
- [ ] 依赖已安装：`pip install -r requirements.txt`
- [ ] yaml 模块可用：`python -c "import yaml"`
- [ ] 配置文件路径正确：检查 `config.yaml` 中的 `ndn.pib_path` 和 `ndn.tpm_path`
- [ ] NDN 数据库已初始化：`ndnsec key-gen /localhost`（如果需要）
- [ ] 使用正确的命令：`python -m python_project server`（不是 `python Python-Convert server`）

## 获取帮助

如果以上方法都无法解决问题，请提供：
1. 完整的错误信息
2. 运行的命令
3. Python 版本：`python --version`
4. 操作系统信息
5. 是否使用了虚拟环境

