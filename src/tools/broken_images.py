"""Broken image detection for a page."""

from playwright.async_api import Page

from src.types.index import BrokenImageFinding
from src.utils.logger import create_logger

logger = create_logger("tool:broken-images")


async def find_broken_images(page: Page) -> list[BrokenImageFinding]:
    logger.log("正在检查页面中的破损图片……")
    findings = await page.evaluate("""async () => {
      const getSelector = (el) => {
        if (el.id) return `#${el.id}`;
        let path = el.tagName.toLowerCase();
        if (el.className && typeof el.className === 'string') {
          const classes = el.className.split(/\\s+/).filter(c => c.length > 0);
          if (classes.length > 0) path += `.${classes.join(".")}`;
        }
        const parent = el.parentElement;
        if (parent) {
          const siblings = Array.from(parent.children).filter(c => c.tagName === el.tagName);
          if (siblings.length > 1) {
            const index = siblings.indexOf(el) + 1;
            path += `:nth-of-type(${index})`;
          }
          let parentPath = parent.tagName.toLowerCase();
          if (parent.id) parentPath = `#${parent.id}`;
          else if (parent.className && typeof parent.className === 'string') {
            const classes = parent.className.split(/\\s+/).filter(c => c.length > 0);
            if (classes.length > 0) parentPath += `.${classes.join(".")}`;
          }
          path = `${parentPath} > ${path}`;
        }
        return path;
      };
      const images = Array.from(document.querySelectorAll("img"));
      const broken = [];
      for (const img of images) {
        const rect = img.getBoundingClientRect();
        const currentSrc = img.getAttribute("src") || "";
        const currentSrcset = img.getAttribute("srcset") || "";
        const result = {
          src: currentSrc, srcset: currentSrcset, alt: img.alt || "",
          selector: getSelector(img), location: {x: rect.x, y: rect.y}, reason: "",
        };
        if (!result.src && !result.srcset) {
          result.reason = "Missing both 'src' and 'srcset' attributes";
          broken.push(result);
          continue;
        }
        if (img.complete && (img.naturalWidth === 0 && img.naturalHeight === 0)) {
          result.reason = "Image loaded with 0x0 dimensions (failed to decode or 404)";
          broken.push(result);
        }
      }
      return broken;
    }""")
    logger.log(f"发现 {len(findings)} 张破损图片" if findings else "未发现破损图片")
    return findings
