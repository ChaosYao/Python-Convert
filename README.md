# Python Project

一个结构良好的Python项目模板，展示了Python项目的最佳实践。

## 项目结构

```
python_project/
├── src/
│   └── python_project/
│       ├── __init__.py
│       ├── main.py
│       └── utils.py
├── tests/
├── docs/
├── scripts/
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── .gitignore
└── README.md
```

## 功能特性

- 🚀 现代化的项目结构
- 📦 使用src布局的包管理
- 🧪 完整的测试框架设置
- 🔧 开发工具配置（代码格式化、类型检查等）
- 📚 详细的文档和示例

## 安装

### 使用pip安装

```bash
# 克隆项目
git clone <your-repo-url>
cd python_project

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 开发环境安装
pip install -r requirements-dev.txt
```

### 使用poetry安装（推荐）

```bash
# 安装poetry
curl -sSL https://install.python-poetry.org | python3 -

# 安装依赖
poetry install

# 激活虚拟环境
poetry shell
```

## 使用方法

### 基本使用

```python
from python_project import greet, main

# 问候功能
message = greet("Alice")
print(message)  # 输出: Hello, Alice! Welcome to the Python project.

# 运行主程序
main()
```

### 命令行使用

```bash
# 运行主程序
python -m python_project.main

# 或直接运行
python src/python_project/main.py
```

## 开发

### 运行测试

```bash
# 运行所有测试
pytest

# 运行测试并生成覆盖率报告
pytest --cov=python_project

# 运行特定测试文件
pytest tests/test_main.py
```

### 代码格式化

```bash
# 使用black格式化代码
black src/ tests/

# 使用flake8检查代码风格
flake8 src/ tests/

# 使用mypy进行类型检查
mypy src/
```

### 预提交钩子

```bash
# 安装预提交钩子
pre-commit install

# 手动运行所有钩子
pre-commit run --all-files
```

## 贡献

1. Fork 项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开 Pull Request

## 许可证

本项目使用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 联系方式

- 作者: Your Name
- 邮箱: your.email@example.com
- 项目链接: [https://github.com/yourusername/python_project](https://github.com/yourusername/python_project)
