"""Port of src/tools/crawler.ts."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse, urlunparse

from playwright.async_api import Page

from src.types.index import OrderedSet
from src.utils.logger import createLogger

logger = createLogger("tool:crawler")


async def crawlSite(page: Page, baseUrl: str, maxPages: int = 20) -> list[str]:
    visited = OrderedSet()
    queue = [baseUrl]
    foundUrls = OrderedSet()
    baseHostname = urlparse(baseUrl).hostname
    logger.log(f"正在使用 Playwright 探索 {baseUrl}（最多 {maxPages} 页）……")

    while queue and len(visited) < maxPages:
        currentUrl = queue.pop(0)
        if currentUrl in visited:
            continue
        try:
            visited.add(currentUrl)
            foundUrls.add(currentUrl)
            await page.goto(currentUrl, wait_until="domcontentloaded", timeout=10000)
            try:
                await page.evaluate("""async () => {
                  await new Promise(resolve => {
                    let totalHeight = 0;
                    const distance = 100;
                    const timer = setInterval(() => {
                      const scrollHeight = document.body.scrollHeight;
                      window.scrollBy(0, distance);
                      totalHeight += distance;
                      if (totalHeight >= scrollHeight) {
                        clearInterval(timer); resolve();
                      }
                    }, 100);
                  });
                }""")
            except Exception:  # noqa: BLE001, S110 - same best-effort scrolling
                pass
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:  # noqa: BLE001, S110 - same best-effort idle wait
                pass
            hrefs = await page.evaluate("""() => Array.from(document.querySelectorAll('a'))
              .map(a => a.href).filter(Boolean)""")
            for href in hrefs:
                try:
                    parsed = urlparse(urljoin(currentUrl, href))
                    if not parsed.fragment.startswith("/"):
                        parsed = parsed._replace(fragment="")
                    cleanUrl = urlunparse(parsed)
                    if (parsed.hostname == baseHostname and cleanUrl not in visited
                            and cleanUrl not in queue and cleanUrl not in foundUrls):
                        queue.append(cleanUrl)
                        foundUrls.add(cleanUrl)
                except Exception:  # noqa: BLE001, S110 - invalid URL ignored by source
                    pass
        except Exception as error:  # noqa: BLE001 - source logs and continues
            logger.error(f"探索 {currentUrl} 时出错：{error}")
    logger.log(f"页面发现完成，共找到 {len(foundUrls)} 个不同页面")
    return list(foundUrls)
