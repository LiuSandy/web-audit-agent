"""Visual regression check between page screenshots."""

import hashlib
import re
from datetime import datetime
from pathlib import Path

from PIL import Image
from pixelmatch.contrib.PIL import pixelmatch

from src.utils.logger import createLogger

logger = createLogger("tool:visual-regression")


def generateScreenshotPaths(url, viewport, config):
    urlHash = hashlib.sha256(url.encode()).hexdigest()[:16]
    urlSlug = re.sub(r"[^a-zA-Z0-9_-]", "_", re.sub(r"^https?://", "", url))[:50]
    baseName = f"{urlSlug}_{urlHash}_{viewport['name']}_{viewport['width']}x{viewport['height']}"
    return {"baseline": str(Path(config["baselineDir"]) / f"{baseName}.png"),
            "current": str(Path(config["currentDir"]) / f"{baseName}.png"),
            "diff": str(Path(config["diffDir"]) / f"{baseName}_diff.png")}


async def ensureDir(dir):
    Path(dir).mkdir(parents=True, exist_ok=True)


async def fileExists(path):
    return Path(path).exists()


async def captureScreenshot(page, viewport, outputPath, fullPage):
    await page.set_viewport_size({"width": viewport["width"], "height": viewport["height"]})
    await page.wait_for_timeout(500)
    await ensureDir(Path(outputPath).parent)
    await page.screenshot(path=outputPath, full_page=fullPage)
    logger.log(f"已截图：{outputPath}（{viewport['name']}：{viewport['width']}×{viewport['height']}）")


async def compareImages(baselinePath, currentPath, diffPath, threshold):
    baselineImg = Image.open(baselinePath).convert("RGBA")
    currentImg = Image.open(currentPath).convert("RGBA")
    width, height = baselineImg.size
    if baselineImg.size != currentImg.size:
        logger.warn(f"图片尺寸不一致：基线 {width}×{height}，当前 {currentImg.width}×{currentImg.height}")
        return {"match": False, "diffPixelCount": -1, "diffPercentage": 100}
    diffImg = Image.new("RGBA", (width, height))
    diffPixelCount = pixelmatch(baselineImg, currentImg, diffImg,
                                threshold=threshold, includeAA=False)
    diffPercentage = diffPixelCount / (width * height) * 100
    await ensureDir(Path(diffPath).parent)
    diffImg.save(diffPath)
    return {"match": diffPixelCount == 0, "diffPixelCount": diffPixelCount,
            "diffPercentage": diffPercentage}


async def runVisualRegression(page, url, config):
    if not config["enabled"]:
        logger.log("未启用视觉差异检查，已跳过")
        return []
    logger.info(f"正在检查页面视觉差异：{url}")
    results = []
    for key in ["baselineDir", "currentDir", "diffDir"]:
        await ensureDir(config[key])
    originalViewport = page.viewport_size
    for viewport in config["viewports"]:
        paths = generateScreenshotPaths(url, viewport, config)
        await captureScreenshot(page, viewport, paths["current"], config["captureFullPage"])
        baselineExists = await fileExists(paths["baseline"])
        if baselineExists:
            logger.log(f"正在与基线比较：{paths['baseline']}")
            comparison = await compareImages(paths["baseline"], paths["current"],
                                             paths["diff"], config["pixelmatchThreshold"])
            passesThreshold = comparison["diffPercentage"] <= config["threshold"] * 100
            result = {"url": url, "viewport": viewport, "baselineExists": True,
                      "baselinePath": paths["baseline"], "currentPath": paths["current"],
                      "match": passesThreshold, "diffPercentage": comparison["diffPercentage"],
                      "diffPixelCount": comparison["diffPixelCount"], "isNewBaseline": False}
            if config["generateDiffImages"]:
                result["diffPath"] = paths["diff"]
            if not passesThreshold:
                logger.warn(f"{viewport['name']} 视觉差异检查失败：差异 {comparison['diffPercentage']:.2f}%（{comparison['diffPixelCount']} 像素）")
            else:
                logger.log(f"{viewport['name']} 视觉差异检查通过：差异 {comparison['diffPercentage']:.2f}%")
        else:
            logger.log(f"未找到基线，正在创建：{paths['baseline']}")
            await ensureDir(Path(paths["baseline"]).parent)
            Path(paths["baseline"]).write_bytes(Path(paths["current"]).read_bytes())
            result = {"url": url, "viewport": viewport, "baselineExists": False,
                      "baselinePath": paths["baseline"], "currentPath": paths["current"],
                      "match": True, "diffPercentage": 0, "diffPixelCount": 0,
                      "isNewBaseline": True}
        results.append(result)
    if originalViewport:
        await page.set_viewport_size(originalViewport)
    logger.info(f"视觉差异检查完成：已测试 {len(results)} 个视口")
    return results


async def updateBaseline(page, url, viewport, config):
    paths = generateScreenshotPaths(url, viewport, config)
    await page.set_viewport_size({"width": viewport["width"], "height": viewport["height"]})
    await page.goto(url, wait_until="networkidle")
    await page.wait_for_timeout(500)
    await ensureDir(Path(paths["baseline"]).parent)
    await page.screenshot(path=paths["baseline"], full_page=config["captureFullPage"])
    logger.info(f"基线已更新：{paths['baseline']}")
    return paths["baseline"]


async def listBaselines(config):
    if not Path(config["baselineDir"]).exists():
        return []
    baselines = []
    for path in Path(config["baselineDir"]).iterdir():
        if path.suffix == ".png":
            try:
                path.read_bytes()
            except OSError:
                continue
            parts = path.stem.split("_")
            match = re.match(r"(\d+)x(\d+)", parts[-1])
            viewport = f"{match.group(1)}x{match.group(2)}" if match else "unknown"
            baselines.append({"path": str(path), "url": "_".join(parts[:-2]),
                              "viewport": viewport, "created": datetime.now()})
    return baselines


async def deleteBaseline(path):
    try:
        Path(path).unlink()
        logger.info(f"基线已删除：{path}")
        return True
    except Exception as error:
        logger.error(f"删除基线失败：{path}", error)
        return False
