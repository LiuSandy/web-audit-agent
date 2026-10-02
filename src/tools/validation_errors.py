"""Visible form validation message detection."""

from typing import TypedDict

from playwright.async_api import Page

from src.types.index import Location
from src.utils.logger import create_logger

logger = create_logger("tool:validation-errors")


class ValidationErrorFinding(TypedDict):
    message: str
    selector: str
    location: Location


async def find_validation_errors(page: Page) -> list[ValidationErrorFinding]:
    logger.log("正在检查页面上的表单校验提示……")
    findings = await page.evaluate("""() => {
      const errors = [];
      const errorSelectors = [
        '[role="alert"]', '.error', '.alert-danger', '.alert-error',
        '.validation-error', '.field-error', '.form-error', '.error-message',
        '.invalid-feedback', '[aria-invalid="true"]', '.text-danger',
        '.text-red-500', '.text-red-600',
      ];
      const getSelector = (el) => {
        if (el.id) return `#${CSS.escape(el.id)}`;
        let path = el.tagName.toLowerCase();
        if (el.className) {
          const classes = el.className.split(" ").filter(c => c.trim());
          if (classes.length > 0) path += `.${classes.map(c => CSS.escape(c)).join(".")}`;
        }
        return path;
      };
      for (const selector of errorSelectors) {
        const elements = document.querySelectorAll(selector);
        for (const el of elements) {
          const rect = el.getBoundingClientRect();
          if (rect.width === 0 || rect.height === 0) continue;
          const style = window.getComputedStyle(el);
          if (style.display === "none" || style.visibility === "hidden") continue;
          const text = el.textContent?.trim() || "";
          if (!text || text.length > 200) continue;
          errors.push({message: text, selector: getSelector(el), location: {x: rect.x, y: rect.y}});
        }
      }
      const invalidInputs = document.querySelectorAll(
        'input[aria-invalid="true"], textarea[aria-invalid="true"], select[aria-invalid="true"]'
      );
      for (const input of invalidInputs) {
        const rect = input.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        const ariaDescribedBy = input.getAttribute("aria-describedby");
        let errorMessage = "";
        if (ariaDescribedBy) {
          const errorEl = document.getElementById(ariaDescribedBy);
          if (errorEl) errorMessage = errorEl.textContent?.trim() || "";
        }
        if (!errorMessage) {
          const parent = input.parentElement;
          if (parent) {
            const nearbyError = parent.querySelector(".error, .invalid-feedback, .field-error");
            if (nearbyError) errorMessage = nearbyError.textContent?.trim() || "";
          }
        }
        if (errorMessage) {
          errors.push({
            message: `输入无效：${errorMessage}`,
            selector: getSelector(input), location: {x: rect.x, y: rect.y},
          });
        }
      }
      const seen = new Map();
      const unique = errors.filter(error => {
        const key = error.message;
        if (seen.has(key)) {
          const prevLocations = seen.get(key);
          const isDuplicate = prevLocations.some(loc =>
            Math.abs(error.location.x - loc.x) < 5 &&
            Math.abs(error.location.y - loc.y) < 5
          );
          if (isDuplicate) return false;
          prevLocations.push(error.location);
        } else seen.set(key, [error.location]);
        return true;
      });
      return unique;
    }""")
    logger.log(f"发现 {len(findings)} 条表单校验提示" if findings else "未发现表单校验提示")
    return findings
