"""CLI 退出码契约（spec §6）。"""

# 正常退出
OK = 0
# 运行时遇到错误
RUN_FAILED = 1
# 用法错误
USAGE = 2
# 用户中断运行（Ctrl+C）
INTERRUPTED = 130
