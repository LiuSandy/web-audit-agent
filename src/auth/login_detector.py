"""Detects login forms on a page."""

from urllib.parse import urlparse

from src.utils.logger import create_logger

logger = create_logger("auth:login-detector")


class LoginFlowDetector:
    async def detect(self, page):
        if not await self.is_login_page(page):
            return None
        username_field = await self.find_username_field(page)
        password_field = await self.find_password_field(page)
        submit_button = await self.find_submit_button(page)
        if (username_field or password_field) and submit_button:
            result = {"type": "form", "usernameField": username_field,
                      "passwordField": password_field, "submitButton": submit_button,
                      "mfaRequired": False}
            if username_field and "email" in username_field:
                result["emailField"] = username_field
            return result
        return {"type": "unknown"}

    async def is_login_page(self, page):
        url = page.url.lower()
        title = (await page.title()).lower()
        return any(kw in url or kw in title for kw in
                   ["login", "signin", "sign-in", "log-in", "authenticate", "auth"])

    async def try_navigate_to_login(self, page):
        parsed = urlparse(page.url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        for path in ["/sign-in", "/login", "/auth", "/signin"]:
            try:
                logger.info(f"正在尝试登录地址：{base}{path}")
                await page.goto(f"{base}{path}", wait_until="networkidle", timeout=10000)
                await page.wait_for_timeout(800)
                if await self.find_password_field(page):
                    logger.info(f"在 {base}{path} 发现登录表单")
                    return True
            except Exception:
                pass
        return False

    async def find_username_field(self, page):
        return await self._first_visible(page, ['input[type="email"]', 'input[name="email"]',
            'input[name="username"]', 'input[id="email"]', 'input[id="username"]',
            'input[type="text"]'])

    async def find_password_field(self, page):
        return await self._first_visible(page, ['input[type="password"]',
            'input[name="password"]', 'input[id="password"]'])

    async def find_submit_button(self, page):
        return await self._first_visible(page, ['button[type="submit"]',
            'input[type="submit"]', 'button:has-text("Login")',
            'button:has-text("Sign in")', 'button:has-text("Log in")'])

    async def _first_visible(self, page, selectors):
        for selector in selectors:
            if await page.locator(selector).first.is_visible():
                return selector
        return None
