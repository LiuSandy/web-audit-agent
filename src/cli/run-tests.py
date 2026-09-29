"""Run generated Python Playwright tests with pytest."""

import subprocess
import sys
from pathlib import Path

import questionary


def showHelp():
    print("""
📚 Python Playwright 常用命令：

# 首次安装浏览器
uv run python -m playwright install chromium

# 运行全部生成的测试
uv run pytest generated-tests/

# 运行单个生成的测试文件
uv run pytest generated-tests/<category>/<file>_spec.py

# 显示完整测试输出
uv run pytest -v -s generated-tests/
""")


def runAllTests():
    print("🚀 正在运行全部生成的测试……")
    print("执行命令：python -m pytest generated-tests/")
    code = subprocess.call([sys.executable, "-m", "pytest", "-o", "python_files=*_spec.py", "generated-tests/"])
    if code != 0:
        print(f"❌ 测试失败（退出码：{code}）", file=sys.stderr)
        sys.exit(code)
    print("✅ 所有测试均已通过！")


async def main():
    print("🧪 Python Playwright 测试运行器")
    if not Path("./generated-tests").exists():
        print("❌ 未找到生成的测试", file=sys.stderr)
        print("💡 请先运行代理：uv run python -m src.index")
        return
    choice = await questionary.select("选择测试操作：", choices=[
        questionary.Choice("🚀 运行全部测试", value="all"),
        questionary.Choice("📋 查看命令", value="help")]).ask_async()
    if choice == "help":
        showHelp()
        return
    runAllTests()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
