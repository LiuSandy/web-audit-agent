"""API keys scoped to one WebAudit home; environment, OS keyring or opt-in file."""
import hashlib
import json
import os

from src.runtime import get_runtime, write_private


def service_name(runtime=None):
    runtime = runtime or get_runtime()
    return "webaudit:" + hashlib.sha256(str(runtime.home).encode()).hexdigest()[:24]


def key_account(provider):
    return "gemini" if provider == "gemini" else "openai"


def read_file_keys(runtime):
    path = runtime.credentials / "api_keys.json"
    if not path.exists():
        return {}
    keys = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(keys, dict):
        raise ValueError("API key 文件格式无效")
    return keys


def get_api_key(provider, runtime=None):
    runtime = runtime or get_runtime()
    names = ("GOOGLE_AI_STUDIO_API_KEY",) if provider == "gemini" else ("OPENAI_API_KEY", "OPEN_AI_API_KEY")
    if provider != "gemini" and os.environ.get("OPENAI_API_KEY") and os.environ.get("OPEN_AI_API_KEY") and os.environ["OPENAI_API_KEY"] != os.environ["OPEN_AI_API_KEY"]:
        import warnings
        warnings.warn("OPENAI_API_KEY 与旧变量 OPEN_AI_API_KEY 不同，使用 OPENAI_API_KEY", stacklevel=2)
    for name in names:
        if os.environ.get(name):
            return os.environ[name], name
    storage = runtime.settings["llm"].get("secret_storage")
    if storage == "keyring":
        import keyring
        try:
            key = keyring.get_password(service_name(runtime), key_account(provider))
        except Exception as error:
            raise RuntimeError("系统凭据库不可用，请设置 API key 环境变量或重新执行 config init") from error
        return key, "系统凭据库"
    if storage == "file":
        return read_file_keys(runtime).get(key_account(provider)), str(runtime.credentials / "api_keys.json")
    return None, "未配置"


def save_api_key(provider, key, storage, runtime=None):
    runtime = runtime or get_runtime()
    if storage == "keyring":
        import keyring
        try:
            keyring.set_password(service_name(runtime), key_account(provider), key)
            write_private(runtime.credentials / "keyring.json", json.dumps({"service": service_name(runtime)}))
        except Exception as error:
            raise RuntimeError("系统凭据库写入失败；可选择 --secret-storage file，或使用环境变量") from error
    elif storage == "file":
        keys = read_file_keys(runtime)
        keys[key_account(provider)] = key
        write_private(runtime.credentials / "api_keys.json", json.dumps(keys))
    else:
        raise ValueError("密钥存储方式仅支持 keyring / file")


def delete_keyring_keys(runtime=None):
    import keyring
    from keyring.errors import PasswordDeleteError
    runtime = runtime or get_runtime()
    for provider in ("openai", "gemini"):
        try:
            if keyring.get_password(service_name(runtime), provider) is not None:
                keyring.delete_password(service_name(runtime), provider)
        except PasswordDeleteError:
            raise RuntimeError("系统凭据删除失败，请解除凭据库锁定后重试")
