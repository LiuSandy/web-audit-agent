"""Visual regression check between page screenshots."""

import hashlib
import re
from datetime import datetime
from pathlib import Path

from PIL import Image
from pixelmatch.contrib.PIL import pixelmatch

from src.utils.logger import create_logger

logger = create_logger("tool:visual-regression")


def generate_screenshot_paths(url, viewport, config):
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    url_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", re.sub(r"^https?://", "", url))[:50]
    base_name = f"{url_slug}_{url_hash}_{viewport['name']}_{viewport['width']}x{viewport['height']}"
    return {"baseline": str(Path(config["baselineDir"]) / f"{base_name}.png"),
            "current": str(Path(config["currentDir"]) / f"{base_name}.png"),
            "diff": str(Path(config["diffDir"]) / f"{base_name}_diff.png")}


async def ensure_dir(dir):
    Path(dir).mkdir(parents=True, exist_ok=True)


async def file_exists(path):
    return Path(path).exists()


async def capture_screenshot(page, viewport, output_path, full_page):
    await page.set_viewport_size({"width": viewport["width"], "height": viewport["height"]})
    await page.wait_for_timeout(500)
    await ensure_dir(Path(output_path).parent)
    await page.screenshot(path=output_path, full_page=full_page)
    logger.log(f"已截图：{output_path}（{viewport['name']}：{viewport['width']}×{viewport['height']}）")


async def compare_images(baseline_path, current_path, diff_path, threshold):
    baseline_img = Image.open(baseline_path).convert("RGBA")
    current_img = Image.open(current_path).convert("RGBA")
    width, height = baseline_img.size
    if baseline_img.size != current_img.size:
        logger.warn(f"图片尺寸不一致：基线 {width}×{height}，当前 {current_img.width}×{current_img.height}")
        return {"match": False, "diffPixelCount": -1, "diffPercentage": 100}
    diff_img = Image.new("RGBA", (width, height))
    diff_pixel_count = pixelmatch(baseline_img, current_img, diff_img,
                                threshold=threshold, includeAA=False)
    diff_percentage = diff_pixel_count / (width * height) * 100
    await ensure_dir(Path(diff_path).parent)
    diff_img.save(diff_path)
    return {"match": diff_pixel_count == 0, "diffPixelCount": diff_pixel_count,
            "diffPercentage": diff_percentage}


async def run_visual_regression(page, url, config):
    if not config["enabled"]:
        logger.log("未启用视觉差异检查，已跳过")
        return []
    logger.info(f"正在检查页面视觉差异：{url}")
    results = []
    for key in ["baselineDir", "currentDir", "diffDir"]:
        await ensure_dir(config[key])
    original_viewport = page.viewport_size
    for viewport in config["viewports"]:
        paths = generate_screenshot_paths(url, viewport, config)
        await capture_screenshot(page, viewport, paths["current"], config["captureFullPage"])
        baseline_exists = await file_exists(paths["baseline"])
        if baseline_exists:
            logger.log(f"正在与基线比较：{paths['baseline']}")
            comparison = await compare_images(paths["baseline"], paths["current"],
                                             paths["diff"], config["pixelmatchThreshold"])
            passes_threshold = comparison["diffPercentage"] <= config["threshold"] * 100
            result = {"url": url, "viewport": viewport, "baselineExists": True,
                      "baselinePath": paths["baseline"], "currentPath": paths["current"],
                      "match": passes_threshold, "diffPercentage": comparison["diffPercentage"],
                      "diffPixelCount": comparison["diffPixelCount"], "isNewBaseline": False}
            if config["generateDiffImages"]:
                result["diffPath"] = paths["diff"]
            if not passes_threshold:
                logger.warn(f"{viewport['name']} 视觉差异检查失败：差异 {comparison['diffPercentage']:.2f}%（{comparison['diffPixelCount']} 像素）")
            else:
                logger.log(f"{viewport['name']} 视觉差异检查通过：差异 {comparison['diffPercentage']:.2f}%")
        else:
            logger.log(f"未找到基线，正在创建：{paths['baseline']}")
            await ensure_dir(Path(paths["baseline"]).parent)
            Path(paths["baseline"]).write_bytes(Path(paths["current"]).read_bytes())
            result = {"url": url, "viewport": viewport, "baselineExists": False,
                      "baselinePath": paths["baseline"], "currentPath": paths["current"],
                      "match": True, "diffPercentage": 0, "diffPixelCount": 0,
                      "isNewBaseline": True}
        results.append(result)
    if original_viewport:
        await page.set_viewport_size(original_viewport)
    logger.info(f"视觉差异检查完成：已测试 {len(results)} 个视口")
    return results


async def update_baseline(page, url, viewport, config):
    paths = generate_screenshot_paths(url, viewport, config)
    await page.set_viewport_size({"width": viewport["width"], "height": viewport["height"]})
    await page.goto(url, wait_until="networkidle")
    await page.wait_for_timeout(500)
    await ensure_dir(Path(paths["baseline"]).parent)
    await page.screenshot(path=paths["baseline"], full_page=config["captureFullPage"])
    logger.info(f"基线已更新：{paths['baseline']}")
    return paths["baseline"]


async def list_baselines(config):
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


async def delete_baseline(path):
    try:
        Path(path).unlink()
        logger.info(f"基线已删除：{path}")
        return True
    except Exception as error:
        logger.error(f"删除基线失败：{path}", error)
        return False
