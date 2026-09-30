"""Coordinates login detection, execution, and session handling."""

from src.auth.credential_provider import CredentialProvider
from src.auth.login_detector import LoginFlowDetector
from src.auth.login_executor import LoginExecutor
from src.auth.session_manager import SessionManager


class AuthenticationManager:
    def __init__(self, db, config=None):
        self.credential_provider = CredentialProvider(db, config)
        self.login_detector = LoginFlowDetector()
        self.login_executor = LoginExecutor()
        self.session_manager = SessionManager(db)

    async def authenticate(self, page, app_identifier):
        try:
            if await self.is_authenticated(page):
                return {"success": True, "method": "session-reuse"}
            restored = await self.session_manager.restore_session(page, app_identifier)
            if restored and await self.is_authenticated(page):
                return {"success": True, "method": "session-restore"}
            login_flow = await self.login_detector.detect(page)
            if not login_flow:
                navigated = await self.login_detector.try_navigate_to_login(page)
                if navigated:
                    login_flow = await self.login_detector.detect(page)
            if not login_flow:
                return {"success": False, "method": "detection-failed",
                        "error": "未检测到登录流程"}
            try:
                credentials = await self.credential_provider.get_credentials(app_identifier)
            except Exception as error:
                return {"success": False, "method": "credential-retrieval", "error": str(error)}
            result = await self.login_executor.execute(page, login_flow, credentials)
            if result["success"]:
                await self.session_manager.save_session(page, app_identifier)
            return result
        except Exception as error:
            return {"success": False, "method": "unknown", "error": str(error)}

    async def is_authenticated(self, page):
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

    async def store_credentials(self, app_identifier, credentials):
        return await self.credential_provider.store_credentials(app_identifier, credentials)
