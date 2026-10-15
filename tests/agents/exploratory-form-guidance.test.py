"""系统提示包含表单与交互探测指引的回归测试（渲染后断言，跟随 golden 机制）。"""
import json
from pathlib import Path

from src.agents.exploratory import _SYSTEM_PROMPT_TEMPLATE

GOLDEN = Path(__file__).parent / "fixtures" / "exploratory-prompt-golden.json"


def _rendered_with_history() -> str:
    # 取值与 exploratory-prompt.test.py 的 GOLDEN_VARS["withHistory"] 保持一致
    golden_vars = {
        "baseUrl": "https://demo.example.com",
        "url": "https://demo.example.com/products?page=2",
        "title": "商品列表 - 演示商城",
        "visitedCount": "7",
        "todoQueueJson": json.dumps(
            ["https://demo.example.com/cart", "https://demo.example.com/login"],
            separators=(",", ":")),
        "recentHistory": "第 5 步：click（原因：尝试加入购物车）→ 结果：已点击 #add-to-cart",
    }
    return _SYSTEM_PROMPT_TEMPLATE.format(**golden_vars)


def test_prompt_contains_form_probing_checklist():
    rendered = _rendered_with_history()
    assert "表单与交互探测" in rendered
    assert "负数" in rendered          # FN-2：负数数量被接受
    assert "无任何提示" in rendered      # FN-5：操作失败且无提示
    assert "清空" in rendered          # FN-4：清空购物车无效


def test_guidance_survives_golden_snapshot():
    # golden 由 Step 3 重新生成后，此测试钉住指引不会在后续改动中被误删
    rendered = _rendered_with_history()
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["withHistory"]
    assert rendered == golden
    assert "表单与交互探测" in golden
