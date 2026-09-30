"""Same-domain link discovery that builds the visit queue."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse, urlunparse

from playwright.async_api import Page

from src.types.index import OrderedSet
from src.utils.logger import create_logger

logger = create_logger("tool:crawler")


async def crawl_site(page: Page, base_url: str, max_pages: int = 20) -> list[str]:
    visited = OrderedSet()
    queue = [base_url]
    found_urls = OrderedSet()
    base_hostname = urlparse(base_url).hostname
    logger.log(f"正在使用 Playwright 探索 {base_url}（最多 {max_pages} 页）……")

    while queue and len(visited) < max_pages:
        current_url = queue.pop(0)
        if current_url in visited:
            continue
        try:
            visited.add(current_url)
            found_urls.add(current_url)
            await page.goto(current_url, wait_until="domcontentloaded", timeout=10000)
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
                    parsed = urlparse(urljoin(current_url, href))
                    if not parsed.fragment.startswith("/"):
                        parsed = parsed._replace(fragment="")
                    clean_url = urlunparse(parsed)
                    if (parsed.hostname == base_hostname and clean_url not in visited
                            and clean_url not in queue and clean_url not in found_urls):
                        queue.append(clean_url)
                        found_urls.add(clean_url)
                except Exception:  # noqa: BLE001, S110 - invalid URL ignored by source
                    pass
        except Exception as error:  # noqa: BLE001 - source logs and continues
            logger.error(f"探索 {current_url} 时出错：{error}")
    logger.log(f"页面发现完成，共找到 {len(found_urls)} 个不同页面")
    return list(found_urls)
