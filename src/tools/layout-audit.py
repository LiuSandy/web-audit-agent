"""Layout audit for a page; DOM heuristics run in the browser."""

import importlib

from src.utils.logger import createLogger

captureLayoutFindingScreenshots = importlib.import_module("src.tools.screenshot").captureLayoutFindingScreenshots
logger = createLogger("tool:layout-audit")

_LAYOUT_CALLBACK = r'''
(opts) => {
  const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "META", "LINK", "NOSCRIPT", "BASE", "HEAD"]);
  const results = [];
  const all = Array.from(document.querySelectorAll("*")).filter((el) => !SKIP_TAGS.has(el.tagName)).slice(0, opts.maxElements);
  const enabled = (h) => !opts.heuristics || opts.heuristics.length === 0 || opts.heuristics.includes(h);
  const getSelector = (el) => {
    if (el.id)
      return `#${el.id}`;
    if (el.className && typeof el.className === "string") {
      const cls = el.className.split(/\s+/).filter(Boolean).join(".");
      if (cls)
        return `${el.tagName.toLowerCase()}.${cls}`;
    }
    const tag = el.tagName.toLowerCase();
    if (el.parentElement) {
      const same = Array.from(el.parentElement.children).filter((c) => c.tagName === el.tagName);
      if (same.length > 1) {
        const idx = same.indexOf(el) + 1;
        return `${el.parentElement.tagName.toLowerCase()} > ${tag}:nth-of-type(${idx})`;
      }
    }
    return tag;
  };
  const flaggedMisalignedParents = new Set;
  for (const el of all) {
    if (!(el instanceof HTMLElement))
      continue;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const vpW = window.innerWidth;
    const vpH = window.innerHeight;
    const selector = getSelector(el);
    if (style.display === "none" || style.visibility === "hidden")
      continue;
    if (enabled("invisible-interactive")) {
      const interactive = ["BUTTON", "A", "INPUT", "SELECT", "TEXTAREA"].includes(el.tagName);
      if (interactive && rect.width === 0 && rect.height === 0) {
        results.push({
          type: "invisible-interactive",
          severity: "error",
          category: "layout",
          message: `交互元素 ${selector} 的宽和高均为零，无法点击`,
          selector
        });
      }
    }
    if (enabled("zero-size-parent")) {
      if (style.display !== "contents" && rect.width === 0 && rect.height === 0 && el.children.length > 0) {
        results.push({
          type: "zero-size-container",
          severity: "error",
          category: "layout",
          message: `容器 ${selector} 尺寸为零，但包含 ${el.children.length} 个子元素`,
          selector
        });
      }
    }
    if (rect.width < 3 && rect.height < 3)
      continue;
    if (enabled("orphan-text")) {
      const directText = Array.from(el.childNodes).filter((n) => n.nodeType === Node.TEXT_NODE).map((n) => n.textContent).join("").trim();
      const orphanParent = el.parentElement && el.parentElement.tagName === "BODY";
      if (orphanParent && el.children.length === 0 && directText.length > 30) {
        results.push({
          type: "orphan-text",
          severity: "warning",
          category: "layout",
          message: `${selector} 中的文本节点直接位于 body 下，缺少合适的块级容器`,
          selector
        });
      }
    }
    if (enabled("empty-container")) {
      const empty = el.children.length === 0 && !Array.from(el.childNodes).some((n) => n.nodeType === Node.TEXT_NODE && n.textContent?.trim());
      const big = rect.width >= 10 && rect.height >= 10;
      if (empty && big) {
        const spacer = style.flex === "1" || style.flexGrow === "1" || parseFloat(style.minWidth) > 0 || parseFloat(style.minHeight) > 0;
        if (!spacer) {
          results.push({
            type: "empty-container",
            severity: "info",
            category: "layout",
            message: `${selector} 是空容器（${Math.round(rect.width)}×${Math.round(rect.height)} 像素）`,
            selector
          });
        }
      }
    }
    if (enabled("misaligned-siblings")) {
      if (style.display.includes("flex") && el.children.length >= 2) {
        if (!flaggedMisalignedParents.has(el)) {
          const children = Array.from(el.children).filter((c) => c instanceof HTMLElement);
          for (let i = 0;i < children.length - 1; i++) {
            const a = children[i];
            const b = children[i + 1];
            const ra = a.getBoundingClientRect();
            const rb = b.getBoundingClientRect();
            const sameRow = style.flexDirection.includes("row") && Math.abs(ra.top - rb.top) < 5 || style.flexDirection.includes("column") && Math.abs(ra.left - rb.left) < 5 || Math.abs(ra.top - rb.top) < 5;
            if (sameRow && ra.height > 10 && rb.height > 10) {
              const ratio = Math.max(ra.height, rb.height) / Math.min(ra.height, rb.height);
              if (ratio > 4) {
                results.push({
                  type: "misaligned-siblings",
                  severity: "info",
                  category: "layout",
                  message: `${selector} 的 Flex 子元素高度差异较大（${Math.round(ra.height)} 与 ${Math.round(rb.height)} 像素）`,
                  selector
                });
                flaggedMisalignedParents.add(el);
                break;
              }
            }
          }
        }
      }
    }
    if (enabled("overlapping-elements")) {
      if (style.position === "absolute" || style.position === "fixed") {
        const siblings = Array.from(el.parentElement?.children || []).filter((s) => s !== el && s instanceof HTMLElement);
        for (const sib of siblings) {
          const sr = sib.getBoundingClientRect();
          const interX = Math.max(0, Math.min(rect.right, sr.right) - Math.max(rect.left, sr.left));
          const interY = Math.max(0, Math.min(rect.bottom, sr.bottom) - Math.max(rect.top, sr.top));
          const overlapArea = interX * interY;
          const minArea = Math.min(rect.width * rect.height, sr.width * sr.height);
          if (minArea > 0 && overlapArea / minArea > 0.5) {
            results.push({
              type: "overlapping-elements",
              severity: "warning",
              category: "layout",
              message: `元素 ${selector} 与同级元素明显重叠`,
              selector
            });
            break;
          }
        }
      }
    }
    if (enabled("off-screen-element")) {
      if (style.position !== "fixed" && style.position !== "sticky") {
        const farOff = rect.bottom < -50 || rect.top > vpH + 50 || rect.right < -50 || rect.left > vpW + 50;
        if (farOff && rect.width > 0 && rect.height > 0) {
          results.push({
            type: "off-screen-element",
            severity: "warning",
            category: "layout",
            message: `元素 ${selector} 远离可见视口`,
            selector
          });
        }
      }
    }
  }
  return results;
}
'''


async def runLayoutAudit(page, config=None):
    config = config or {}
    logger.log("正在检查页面布局……")
    maxElements = config.get("maxElements", 300)
    heuristics = config.get("heuristics")
    findings = await page.evaluate(_LAYOUT_CALLBACK, {"maxElements": maxElements,
                                                      "heuristics": heuristics})
    logger.log(f"页面布局检查发现 {len(findings)} 个疑似问题")
    screenshots = config.get("screenshots") or {}
    if screenshots.get("enabled") and findings:
        logger.log("正在为布局问题截图……")
        screenshotConfig = {"enabled": True,
            "outputDir": screenshots.get("outputDir") or "./test-results/layout-audit",
            "fullPage": True,
            "highlightElements": screenshots.get("highlightElements", True),
            "type": screenshots.get("type") or "png"}
        screenshotMap = await captureLayoutFindingScreenshots(
            page, findings, screenshotConfig, config.get("sessionId") or "unknown")
        for index, paths in screenshotMap.items():
            if index < len(findings):
                if paths.get("elementPath"):
                    findings[index]["screenshot"] = paths["elementPath"]
                if paths.get("fullPagePath"):
                    findings[index]["fullPageScreenshot"] = paths["fullPagePath"]
        logger.log(f"已为 {len(screenshotMap)} 个布局问题截图")
    return findings
