"""Chinese labels for stable machine-readable values."""

FINDING_TYPES = {
    "broken_image": "图片加载异常",
    "console_error": "控制台错误",
    "network_error": "网络错误",
    "validation_error": "表单校验问题",
    "functional_bug": "功能问题",
    "ux_issue": "体验问题",
    "visual_regression": "视觉回归问题",
    "bug": "问题",
    "other": "其他问题",
}

SEVERITIES = {
    "info": "提示",
    "low": "低",
    "medium": "中",
    "high": "高",
    "critical": "严重",
    "warning": "警告",
    "error": "错误",
}

TEST_TYPES = {"e2e": "端到端测试"}

STATUSES = {
    "pending": "等待中",
    "started": "已启动",
    "running": "运行中",
    "planning": "规划中",
    "executing": "执行中",
    "stopping": "正在停止",
    "completed": "已完成",
    "stopped": "已停止",
    "failed": "失败",
    "passed": "通过",
    "skipped": "已跳过",
    "active": "进行中",
    "not_found": "未找到",
    "unknown": "未知",
}

ACTIONS = {
    "navigate": "访问页面",
    "click": "点击元素",
    "fill_form": "填写表单",
    "add_to_queue": "添加待访问页面",
    "find_broken_images": "检查破损图片",
    "record_finding": "记录问题",
    "finish": "结束探索",
    "error": "执行出错",
    "fill": "填写输入框",
    "select": "选择选项",
    "hover": "悬停元素",
    "wait": "等待",
    "verify": "验证结果",
}

BROKEN_IMAGE_REASONS = {
    "Missing both 'src' and 'srcset' attributes": "缺少 src 和 srcset 属性",
    "Image loaded with 0x0 dimensions (failed to decode or 404)": "图片尺寸为 0×0（解码失败或返回 404）",
}


def display_label(value, labels):
    """Translate known values while preserving unknown extension values."""
    return labels.get(value, value)
