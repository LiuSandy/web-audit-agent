"""TOTP multi-factor authentication code handling."""

import sys
import pyotp
from playwright.async_api import Page


class MFAHandler:
    def __init__(self) -> None:
        self.totp = pyotp.TOTP

    async def handle_totp(self, page: Page, totp_secret: str) -> bool:
        try:
            token = self.totp(totp_secret).now()
            mfa_input = page.locator(
                'input[name*="code"], input[name*="token"], input[name*="otp"], input[placeholder*="code"]'
            )
            if await mfa_input.count() > 0:
                await mfa_input.first.fill(token)
                submit_button = page.locator(
                    'button[type="submit"], button:has-text("verify"), button:has-text("continue")'
                )
                if await submit_button.count() > 0 and await submit_button.first.is_visible():
                    await submit_button.first.click()
                return True
            return False
        except Exception as error:  # noqa: BLE001 - source returns false on any failure
            print("处理 TOTP 验证码失败：", error, file=sys.stderr)
            return False

    async def handle_sms(self, _page: Page) -> None:
        print("遇到短信多因素认证；如无法自动处理，请人工完成验证。", file=sys.stderr)
