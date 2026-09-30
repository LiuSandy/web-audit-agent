"""CLI 选项到 agent 配置的纯函数转换（无 I/O，直接单测）。"""
import uuid
from dataclasses import dataclass


@dataclass
class RunOptions:
    """run 子命令与向导共用的运行选项；生成的配置 dict 键保持 camelCase 契约。"""

    base_url: str = ""
    max_steps: int = 50
    autonomous: bool = True
    session_id: str | None = None
    verbose: bool = False
    json_output: bool = False
    auth_email: str | None = None
    auth_password: str | None = None
    auth_app_identifier: str | None = None
    use_saved_credentials: str | None = None
    generate_tests: bool = False
    test_mode: str = "dry-run"
    max_concurrency: int = 4
    timeout_ms: int = 30000
    retry_count: int = 2


def new_session_id() -> str:
    return "session-" + uuid.uuid4().hex


def build_auth(options: RunOptions) -> dict | None:
    """认证三来源：已保存凭据 > 显式密码 > 无。"""
    if options.use_saved_credentials:
        return {"required": True, "appIdentifier": options.use_saved_credentials}
    if options.auth_password is not None:
        return {"required": True, "appIdentifier": options.auth_app_identifier or "default-app",
                "credentials": {"email": options.auth_email or "", "password": options.auth_password}}
    return None


def build_config(options: RunOptions) -> dict:
    """键名对齐 ExploratoryAgent 的 camelCase 契约（spec §10）。"""
    return {
        "baseUrl": options.base_url,
        "maxSteps": options.max_steps,
        "sessionId": options.session_id or new_session_id(),
        "auth": build_auth(options),
        "enableTestGeneration": options.generate_tests,
        "testOutputDir": "./generated-tests",
        "includeE2ETests": True,
        "testDryRun": options.test_mode == "dry-run",
        "testParallelExecution": options.test_mode == "parallel",
        "testMaxConcurrency": options.max_concurrency,
        "testTimeout": options.timeout_ms,
        "testRetryCount": options.retry_count,
    }


def validate_auth(options: RunOptions) -> str | None:
    """校验认证参数组合；返回中文错误信息，None 表示合法。"""
    saved = options.use_saved_credentials
    password_given = options.auth_password is not None
    if saved and (password_given or options.auth_email or options.auth_app_identifier):
        return "--use-saved-credentials 不能与 --auth-password/--auth-email/--auth-app-identifier 同时使用"
    if options.auth_email and not password_given:
        return "--auth-email 需要搭配 --auth-password"
    if options.auth_app_identifier and not password_given:
        return "--auth-app-identifier 需要搭配 --auth-password，或改用 --use-saved-credentials"
    return None
