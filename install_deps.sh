#!/bin/bash
# 安装项目依赖脚本

set -e

echo "=========================================="
echo "安装 Python-Convert 项目依赖"
echo "=========================================="

# 检查虚拟环境
if [ -d "venv" ]; then
    echo "使用现有虚拟环境: venv"
    PYTHON="./venv/bin/python"
    PIP="./venv/bin/pip"
elif [ -d ".venv" ]; then
    echo "使用现有虚拟环境: .venv"
    PYTHON="./.venv/bin/python"
    PIP="./.venv/bin/pip"
else
    echo "未找到虚拟环境，使用系统 Python"
    PYTHON="python3"
    PIP="pip3"
fi

echo ""
echo "Python 路径: $($PYTHON --version)"
echo "Python 可执行文件: $($PYTHON -c 'import sys; print(sys.executable)')"
echo ""

# 检查 yaml 模块
echo "检查 yaml 模块..."
if $PYTHON -c "import yaml" 2>/dev/null; then
    echo "✓ yaml 模块已安装"
else
    echo "✗ yaml 模块未安装，正在安装..."
    $PIP install pyyaml
    echo "✓ yaml 模块安装完成"
fi

echo ""
echo "安装所有依赖..."
$PIP install -r requirements.txt

echo ""
echo "=========================================="
echo "依赖安装完成！"
echo "=========================================="
echo ""
echo "使用方法："
if [ -d "venv" ] || [ -d ".venv" ]; then
    echo "  激活虚拟环境:"
    if [ -d "venv" ]; then
        echo "    source venv/bin/activate"
    else
        echo "    source .venv/bin/activate"
    fi
    echo ""
    echo "  运行程序:"
    echo "    python -m python_project server"
    echo "    python -m python_project client"
else
    echo "  运行程序:"
    echo "    $PYTHON -m python_project server"
    echo "    $PYTHON -m python_project client"
fi
echo ""

