"""Port of src/auth/auth-manager.ts."""

import importlib

CredentialProvider = importlib.import_module("src.auth.credential-provider").CredentialProvider
LoginFlowDetector = importlib.import_module("src.auth.login-detector").LoginFlowDetector
LoginExecutor = importlib.import_module("src.auth.login-executor").LoginExecutor
SessionManager = importlib.import_module("src.auth.session-manager").SessionManager


class AuthenticationManager:
    def __init__(self, db, config=None):
        self.credentialProvider = CredentialProvider(db, config)
        self.loginDetector = LoginFlowDetector()
        self.loginExecutor = LoginExecutor()
        self.sessionManager = SessionManager(db)

    async def authenticate(self, page, appIdentifier):
        try:
            if await self.isAuthenticated(page):
                return {"success": True, "method": "session-reuse"}
            restored = await self.sessionManager.restoreSession(page, appIdentifier)
            if restored and await self.isAuthenticated(page):
                return {"success": True, "method": "session-restore"}
            loginFlow = await self.loginDetector.detect(page)
            if not loginFlow:
                navigated = await self.loginDetector.tryNavigateToLogin(page)
                if navigated:
                    loginFlow = await self.loginDetector.detect(page)
            if not loginFlow:
                return {"success": False, "method": "detection-failed",
                        "error": "未检测到登录流程"}
            try:
                credentials = await self.credentialProvider.getCredentials(appIdentifier)
            except Exception as error:
                return {"success": False, "method": "credential-retrieval", "error": str(error)}
            result = await self.loginExecutor.execute(page, loginFlow, credentials)
            if result["success"]:
                await self.sessionManager.saveSession(page, appIdentifier)
            return result
        except Exception as error:
            return {"success": False, "method": "unknown", "error": str(error)}

    async def isAuthenticated(self, page):
        indicators = await page.evaluate("""() => {
            let hasLogout = false;
            for (const el of document.querySelectorAll('button, a')) {
                const text = el.textContent?.toLowerCase() || '';
                if (text.includes('logout') || text.includes('sign out')) { hasLogout = true; break; }
            }
            if (!hasLogout) hasLogout = !!document.querySelector('a[href*="logout"]');
            const hasUserMenu = !!document.querySelector('[class*="user-menu"], [class*="profile"], [id*="user-menu"], [class*="user-email"]');
            return {hasLogout, hasUserMenu};
        }""")
        return indicators["hasLogout"] or indicators["hasUserMenu"]

    async def storeCredentials(self, appIdentifier, credentials):
        return await self.credentialProvider.storeCredentials(appIdentifier, credentials)
