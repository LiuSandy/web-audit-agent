"""Port of src/auth/login-detector.ts."""

from urllib.parse import urlparse

from src.utils.logger import createLogger

logger = createLogger("auth:login-detector")


class LoginFlowDetector:
    async def detect(self, page):
        if not await self.isLoginPage(page):
            return None
        usernameField = await self.findUsernameField(page)
        passwordField = await self.findPasswordField(page)
        submitButton = await self.findSubmitButton(page)
        if (usernameField or passwordField) and submitButton:
            result = {"type": "form", "usernameField": usernameField,
                      "passwordField": passwordField, "submitButton": submitButton,
                      "mfaRequired": False}
            if usernameField and "email" in usernameField:
                result["emailField"] = usernameField
            return result
        return {"type": "unknown"}

    async def isLoginPage(self, page):
        url = page.url.lower()
        title = (await page.title()).lower()
        return any(kw in url or kw in title for kw in
                   ["login", "signin", "sign-in", "log-in", "authenticate", "auth"])

    async def tryNavigateToLogin(self, page):
        parsed = urlparse(page.url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        for path in ["/sign-in", "/login", "/auth", "/signin"]:
            try:
                logger.info(f"正在尝试登录地址：{base}{path}")
                await page.goto(f"{base}{path}", wait_until="networkidle", timeout=10000)
                await page.wait_for_timeout(800)
                if await self.findPasswordField(page):
                    logger.info(f"在 {base}{path} 发现登录表单")
                    return True
            except Exception:
                pass
        return False

    async def findUsernameField(self, page):
        return await self._firstVisible(page, ['input[type="email"]', 'input[name="email"]',
            'input[name="username"]', 'input[id="email"]', 'input[id="username"]',
            'input[type="text"]'])

    async def findPasswordField(self, page):
        return await self._firstVisible(page, ['input[type="password"]',
            'input[name="password"]', 'input[id="password"]'])

    async def findSubmitButton(self, page):
        return await self._firstVisible(page, ['button[type="submit"]',
            'input[type="submit"]', 'button:has-text("Login")',
            'button:has-text("Sign in")', 'button:has-text("Log in")'])

    async def _firstVisible(self, page, selectors):
        for selector in selectors:
            if await page.locator(selector).first.is_visible():
                return selector
        return None
