# ndn_demo.py vs main.py 区别说明

## 主要区别

### 1. **定位和用途**

#### `examples/ndn_demo.py` - 示例/演示脚本
- **位置**: `examples/` 目录
- **用途**: 用于演示和学习 NDN 功能
- **特点**: 简单直接，适合快速测试

#### `src/python_project/main.py` - 正式主入口
- **位置**: `src/python_project/` 目录（作为包的一部分）
- **用途**: 生产环境使用的正式入口点
- **特点**: 功能完整，支持多种配置方式

### 2. **调用方式**

#### ndn_demo.py
```bash
# 直接运行脚本
python examples/ndn_demo.py server
python examples/ndn_demo.py client
```

#### main.py
```bash
# 作为模块运行（推荐）
python -m python_project server
python -m python_project client

# 或直接运行
python src/python_project/main.py server
```

### 3. **配置支持**

#### ndn_demo.py
- ✅ 支持配置文件（自动查找 `config.yaml`）
- ✅ 支持环境变量（`NDN_PIB_PATH`, `NDN_TPM_PATH`）
- ❌ 不支持 `--config` 参数指定配置文件路径
- ❌ 不支持从配置文件读取日志级别

#### main.py
- ✅ 支持配置文件（自动查找 `config.yaml`）
- ✅ 支持环境变量（`NDN_PIB_PATH`, `NDN_TPM_PATH`, `MODE`, `LOG_LEVEL`）
- ✅ 支持 `--config` 参数指定配置文件路径
- ✅ 支持从配置文件读取日志级别
- ✅ 支持从配置文件读取运行模式

### 4. **功能对比**

| 功能 | ndn_demo.py | main.py |
|------|-------------|---------|
| 命令行参数 | ✅ 基础支持 | ✅ 完整支持 |
| 环境变量 | ✅ 部分支持 | ✅ 完整支持 |
| 配置文件 | ✅ 自动查找 | ✅ 自动查找 + 手动指定 |
| 日志级别配置 | ❌ 固定 INFO | ✅ 可配置 |
| 运行模式配置 | ❌ 仅命令行 | ✅ 命令行/环境变量/配置文件 |
| 错误处理 | ✅ 基础 | ✅ 完善 |
| 使用说明 | ✅ 简单 | ✅ 详细 |

### 5. **代码结构**

#### ndn_demo.py
```python
# 需要手动添加路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

# 简单的参数处理
if len(sys.argv) > 1:
    mode = sys.argv[1].lower()
    # ...
```

#### main.py
```python
# 作为包的一部分，直接导入
from .ndn.client import NDNClient
from .config import get_config

# 完善的参数和配置处理
def get_mode(config_path: Optional[str] = None) -> Optional[str]:
    # 支持多种方式获取模式
    # 1. 命令行参数
    # 2. 环境变量
    # 3. 配置文件
```

### 6. **使用场景**

#### 使用 `ndn_demo.py` 当你：
- 🎓 学习 NDN 功能
- 🧪 快速测试和调试
- 📝 查看示例代码
- 🚀 快速原型开发

#### 使用 `main.py` 当你：
- 🏭 生产环境部署
- 🔧 需要灵活配置
- 📦 作为系统服务运行
- 🎯 需要完整的配置管理

### 7. **实际使用示例**

#### ndn_demo.py
```bash
# 简单使用
python examples/ndn_demo.py server
python examples/ndn_demo.py client

# 使用环境变量
NDN_PIB_PATH=/path/to/pib.db python examples/ndn_demo.py server
```

#### main.py
```bash
# 基础使用
python -m python_project server
python -m python_project client

# 指定配置文件
python -m python_project server --config=/path/to/config.yaml

# 使用环境变量
MODE=server LOG_LEVEL=DEBUG python -m python_project

# 组合使用
NDN_PIB_PATH=/path/to/pib.db python -m python_project server --config=prod_config.yaml
```

### 8. **配置文件支持**

两者都支持 `config.yaml`，但 `main.py` 支持更灵活：

```bash
# ndn_demo.py - 只能自动查找
python examples/ndn_demo.py server  # 自动查找 config.yaml

# main.py - 可以指定路径
python -m python_project server --config=custom_config.yaml
```

### 9. **系统集成**

#### main.py 可以作为系统服务
```ini
# systemd 服务示例
[Service]
ExecStart=/path/to/python -m python_project server
```

#### ndn_demo.py 不适合作为系统服务
- 路径依赖问题
- 配置不够灵活

## 总结

- **ndn_demo.py**: 适合学习和快速测试
- **main.py**: 适合生产环境和正式使用

**推荐**: 在开发阶段可以使用 `ndn_demo.py` 快速测试，在生产环境使用 `main.py`。

