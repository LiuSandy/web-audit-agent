"""CLI 选项到 agent 配置的纯函数转换（无 I/O，直接单测）。"""
import uuid
from urllib.parse import urlparse
from dataclasses import dataclass

from src.runtime import get_runtime, new_run_id


@dataclass
class RunOptions:
    """run 子命令与向导共用的运行选项；生成的配置 dict 键保持 camelCase 契约。"""

    base_url: str = ""
    max_steps: int = 50
    max_failures: int = 3
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
    output_dir: str | None = None


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
    session_id = options.session_id or new_session_id()
    run_id = new_run_id()
    artifact_dir = get_runtime().run_dir(session_id, run_id)
    return {
        "runId": run_id,
        "artifactDir": str(artifact_dir),
        "exportDir": options.output_dir,
        "baseUrl": options.base_url,
        "maxSteps": options.max_steps,
        "maxFailures": options.max_failures,
        "sessionId": session_id,
        "auth": build_auth(options),
        "enableTestGeneration": options.generate_tests,
        "testOutputDir": str(artifact_dir / "generated-tests"),
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


def validate_options(options: RunOptions) -> str | None:
    try:
        url = urlparse(options.base_url)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            return "目标地址必须是有效的 HTTP/HTTPS URL，且不能包含登录凭据"
        url.port
    except ValueError:
        return "目标地址无效"
    for name, value in (("max-steps", options.max_steps), ("max-failures", options.max_failures),
                        ("max-concurrency", options.max_concurrency), ("timeout", options.timeout_ms)):
        if value < 1:
            return f"--{name} 必须为正整数"
    if options.retry_count < 0:
        return "--retry-count 不能为负数"
    if options.test_mode not in ("dry-run", "sequential", "parallel"):
        return "--test-mode 仅支持 dry-run | sequential | parallel"
    if options.session_id and any(c in options.session_id for c in ("/", "\\", "\x00")):
        return "会话 ID 不能包含路径分隔符或空字符"
    if options.session_id in (".", ".."):
        return "会话 ID 不能为 . 或 .."
    return validate_auth(options)
