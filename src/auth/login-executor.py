"""Port of src/auth/login-executor.ts."""

import importlib
import re

MFAHandler = importlib.import_module("src.auth.mfa-handler").MFAHandler


class LoginExecutor:
    def __init__(self):
        self.mfaHandler = MFAHandler()

    async def execute(self, page, loginFlow, credentials):
        try:
            if loginFlow["type"] == "form":
                return await self.executeFormLogin(page, loginFlow, credentials)
            if loginFlow["type"] == "oauth":
                return {"success": False, "method": "oauth", "error": "尚未实现 OAuth 登录"}
            return {"success": False, "method": loginFlow["type"],
                    "error": "暂不支持该登录方式"}
        except Exception as error:
            return {"success": False, "method": loginFlow["type"], "error": str(error)}

    async def executeFormLogin(self, page, loginFlow, credentials):
        if loginFlow.get("emailField") and credentials.get("email"):
            await page.fill(loginFlow["emailField"], credentials["email"])
        elif loginFlow.get("usernameField") and credentials.get("username"):
            await page.fill(loginFlow["usernameField"], credentials["username"])
        elif loginFlow.get("usernameField") and credentials.get("email"):
            await page.fill(loginFlow["usernameField"], credentials["email"])
        if loginFlow.get("passwordField") and credentials.get("password"):
            await page.fill(loginFlow["passwordField"], credentials["password"])
        if loginFlow.get("submitButton"):
            try:
                await page.wait_for_selector(loginFlow["submitButton"], state="visible", timeout=5000)
                await page.locator(loginFlow["submitButton"]).click()
            except Exception:
                if loginFlow.get("passwordField"):
                    await page.locator(loginFlow["passwordField"]).press("Enter")
        elif loginFlow.get("passwordField"):
            await page.locator(loginFlow["passwordField"]).press("Enter")
        try:
            await page.wait_for_url(re.compile(r"^(?!.*sign-in)(?!.*login).*"), timeout=10000)
        except Exception:
            pass
        try:
            await page.wait_for_timeout(5000)
        except Exception:
            pass
        if credentials.get("totpSecret"):
            handled = await self.mfaHandler.handleTOTP(page, credentials["totpSecret"])
            if handled:
                await page.wait_for_timeout(2000)
        success = await self.verifyLoginSuccess(page)
        result = {"success": success, "method": "form"}
        if not success:
            result["error"] = "登录验证失败"
        return result

    async def verifyLoginSuccess(self, page):
        url = page.url.lower()
        if not any(x in url for x in ["sign-in", "signin", "login"]):
            return True
        indicators = await page.evaluate("""() => {
            let hasLogout = false;
            for (const el of document.querySelectorAll('a, button')) {
                const text = el.textContent?.toLowerCase() || '';
                if (['logout', 'sign out', 'log out', 'sair', 'exit'].some(x => text.includes(x))) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) { hasLogout = true; break; }
                }
            }
            if (!hasLogout) hasLogout = !!document.querySelector('a[href*="logout"]');
            const hasUserMenu = !!document.querySelector('[class*="user-menu"], [class*="profile"], [id*="user-menu"], [data-slot="avatar"], [class*="avatar"]');
            let hasErrorMessage = false;
            for (const el of document.querySelectorAll('[class*="error"], [class*="alert"], [role="alert"], [data-slot="toast"]')) {
                const rect = el.getBoundingClientRect(); const text = el.textContent?.trim();
                if (rect.width > 0 && rect.height > 0 && text && text.length > 0 &&
                    getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden') {
                    hasErrorMessage = true; break;
                }
            }
            const hasToastError = !!document.querySelector('[data-sonner-toast] [data-icon]');
            return {hasLogout, hasUserMenu, hasErrorMessage, hasToastError};
        }""")
        if (indicators["hasLogout"] or indicators["hasUserMenu"]) and not indicators["hasErrorMessage"] and not indicators["hasToastError"]:
            return True
        if not indicators["hasErrorMessage"] and not indicators["hasToastError"]:
            return True
        return False
