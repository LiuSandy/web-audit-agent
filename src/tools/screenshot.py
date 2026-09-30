"""Full-page and element screenshot capture."""

import re
import time
from pathlib import Path

from src.utils.logger import createLogger

logger = createLogger("tool:screenshot")


async def ensureDir(dir):
    Path(dir).mkdir(parents=True, exist_ok=True)


def generateFilename(selector, index, suffix):
    clean = re.sub(r"[^a-zA-Z0-9_-]", "_", selector)[:50]
    return f"finding_{index}_{clean}_{suffix}_{int(time.time() * 1000)}.png"


async def highlightElement(page, selector, color="#FF0000"):
    try:
        return await page.evaluate("""({sel, highlightColor}) => {
            const el = document.querySelector(sel);
            if (!el || !(el instanceof HTMLElement)) return false;
            const originalOutline = el.style.outline;
            const originalOutlineOffset = el.style.outlineOffset;
            const originalPosition = el.style.position;
            const originalZIndex = el.style.zIndex;
            el.style.outline = `4px solid ${highlightColor}`;
            el.style.outlineOffset = '2px';
            el.style.position = 'relative';
            el.style.zIndex = '99999';
            el.__screenshotOriginalStyles = {
                outline: originalOutline, outlineOffset: originalOutlineOffset,
                position: originalPosition, zIndex: originalZIndex
            };
            el.scrollIntoView({behavior: 'instant', block: 'center', inline: 'center'});
            return true;
        }""", {"sel": selector, "highlightColor": color})
    except Exception as error:
        logger.warn(f"高亮元素 {selector} 失败：", error)
        return False


async def removeHighlight(page, selector):
    try:
        await page.evaluate("""sel => {
            const el = document.querySelector(sel);
            if (!el || !(el instanceof HTMLElement)) return;
            const original = el.__screenshotOriginalStyles;
            if (original) {
                el.style.outline = original.outline;
                el.style.outlineOffset = original.outlineOffset;
                el.style.position = original.position;
                el.style.zIndex = original.zIndex;
                delete el.__screenshotOriginalStyles;
            }
        }""", selector)
    except Exception as error:
        logger.log(f"移除元素 {selector} 的高亮失败：", error)


async def captureFullPageScreenshot(page, config, filename):
    if not config["enabled"]:
        return None
    try:
        await ensureDir(config["outputDir"])
        filepath = str(Path(config["outputDir"]) / filename)
        await page.screenshot(path=filepath, full_page=config["fullPage"],
                              type=config.get("type") or "png")
        logger.log(f"整页截图已保存：{filepath}")
        return filepath
    except Exception as error:
        logger.error("整页截图失败：", error)
        return None


async def captureElementScreenshot(page, selector, config, filename, severity="warning"):
    if not config["enabled"]:
        return None
    colors = {"error": "#FF0000", "warning": "#FFA500", "info": "#0080FF"}
    highlighted = False
    try:
        await ensureDir(config["outputDir"])
        filepath = str(Path(config["outputDir"]) / filename)
        if config["highlightElements"]:
            highlighted = await highlightElement(page, selector, colors[severity])
            await page.wait_for_timeout(100)
        try:
            await page.locator(selector).first.screenshot(path=filepath,
                                                           type=config.get("type") or "png")
            logger.log(f"元素截图已保存：{filepath}")
            return filepath
        except Exception:
            logger.log(f"元素 {selector} 截图失败，改为截取视口")
            await page.screenshot(path=filepath, full_page=False,
                                  type=config.get("type") or "png")
            logger.log(f"视口截图已保存：{filepath}")
            return filepath
    except Exception as error:
        logger.error(f"截取元素 {selector} 失败：", error)
        return None
    finally:
        if highlighted and config["highlightElements"]:
            await removeHighlight(page, selector)


async def captureLayoutFindingScreenshots(page, findings, config, sessionId):
    screenshotMap = {}
    if not config["enabled"] or not findings:
        return screenshotMap
    sessionDir = str(Path(config["outputDir"]) / sessionId)
    await ensureDir(sessionDir)
    fullPageFilename = f"layout_audit_full_{int(time.time() * 1000)}.png"
    fullPagePath = await captureFullPageScreenshot(
        page, {**config, "outputDir": sessionDir}, fullPageFilename)
    for i, finding in enumerate(findings):
        result = {}
        if fullPagePath:
            result["fullPagePath"] = fullPagePath
        if finding.get("selector"):
            filename = generateFilename(finding["selector"], i, finding["type"])
            elementPath = await captureElementScreenshot(
                page, finding["selector"], {**config, "outputDir": sessionDir},
                filename, finding["severity"])
            if elementPath:
                result["elementPath"] = elementPath
        screenshotMap[i] = result
        if i < len(findings) - 1:
            await page.wait_for_timeout(50)
    return screenshotMap
