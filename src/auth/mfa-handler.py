"""Port of src/auth/mfa-handler.ts."""

import pyotp
from playwright.async_api import Page


class MFAHandler:
    def __init__(self) -> None:
        self.totp = pyotp.TOTP

    async def handleTOTP(self, page: Page, totpSecret: str) -> bool:
        try:
            token = self.totp(totpSecret).now()
            mfaInput = page.locator(
                'input[name*="code"], input[name*="token"], input[name*="otp"], input[placeholder*="code"]'
            )
            if await mfaInput.count() > 0:
                await mfaInput.first.fill(token)
                submitButton = page.locator(
                    'button[type="submit"], button:has-text("verify"), button:has-text("continue")'
                )
                if await submitButton.count() > 0 and await submitButton.first.is_visible():
                    await submitButton.first.click()
                return True
            return False
        except Exception as error:  # noqa: BLE001 - source returns false on any failure
            print("处理 TOTP 验证码失败：", error)
            return False

    async def handleSMS(self, _page: Page) -> None:
        print("遇到短信多因素认证；如无法自动处理，请人工完成验证。")
