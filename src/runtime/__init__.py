"""Shared configuration and storage context for CLI, agents and MCP."""
from contextvars import ContextVar
from dataclasses import dataclass
import os
from pathlib import Path
import tomllib
import uuid


@dataclass(frozen=True)
class Runtime:
    home: Path
    data: Path
    config_file: Path
    settings: dict
    sources: dict

    @property
    def database(self):
        return self.data / "webaudit.sqlite"

    @property
    def runs(self):
        return self.data / "runs"

    @property
    def credentials(self):
        return self.home / "credentials"

    def run_dir(self, session_id, run_id):
        validate_identifier(session_id)
        validate_identifier(run_id)
        return self.runs / session_id / run_id

    def paths(self):
        return {"home": str(self.home), "config": str(self.config_file), "data": str(self.data),
                "database": str(self.database), "runs": str(self.runs),
                "credentials": str(self.credentials), "logs": str(self.home / "logs"),
                "cache": str(self.home / "cache")}


_current = ContextVar("webaudit_runtime", default=None)


def validate_identifier(value):
    if not isinstance(value, str) or not value or value in (".", "..") or any(c in value for c in ("/", "\\", "\x00")):
        raise ValueError("会话/运行 ID 必须是非空名称，不能包含路径分隔符")


def resolve_path(value, base=None):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base or Path.cwd()) / path
    return path.absolute()


def resolve_runtime(home=None, data_dir=None, config_file=None, overrides=None, ignore_config=False):
    root = resolve_path(home or os.environ.get("WEBAUDIT_HOME") or Path.home() / ".config" / "webaudit")
    config = resolve_path(config_file) if config_file else root / "config.toml"
    settings = {}
    sources = {}
    if config.exists() and not ignore_config:
        try:
            settings = tomllib.loads(config.read_text(encoding="utf-8"))
        except (ValueError, OSError) as error:
            raise ValueError(f"无法读取配置 {config}：{error}") from error
    for section in ("llm", "run", "storage"):
        if not isinstance(settings.get(section, {}), dict):
            raise ValueError(f"配置 [{section}] 必须是表")
        settings.setdefault(section, {})
        for key in settings[section]:
            sources[f"{section}.{key}"] = str(config)
    env_fields = {"WEBAUDIT_PROVIDER": ("llm", "provider"), "WEBAUDIT_MODEL": ("llm", "model"),
                  "WEBAUDIT_MAX_STEPS": ("run", "max_steps"), "WEBAUDIT_MAX_FAILURES": ("run", "max_failures")}
    for env, (section, key) in env_fields.items():
        if os.environ.get(env):
            value = os.environ[env]
            if section == "run":
                try:
                    value = int(value)
                except ValueError as error:
                    raise ValueError(f"{env} 必须是正整数") from error
            settings[section][key] = value
            sources[f"{section}.{key}"] = env
    if (overrides or {}).get("provider") is not None:
        settings["llm"]["provider"] = overrides["provider"]
        sources["llm.provider"] = "命令参数"
    provider = settings["llm"].get("provider")
    if not provider:
        if os.environ.get("OPENAI_API_KEY") or os.environ.get("OPEN_AI_API_KEY") or os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPEN_AI_API_URL"):
            provider = "openai"
        elif os.environ.get("GOOGLE_AI_STUDIO_API_KEY"):
            provider = "gemini"
        if provider:
            settings["llm"]["provider"] = provider
            sources["llm.provider"] = "环境变量自动选择"
    if provider in ("openai", "openai-compatible", None):
        fields = {"model": ("OPENAI_MODEL", "OPEN_AI_MODEL"), "base_url": ("OPENAI_BASE_URL", "OPEN_AI_API_URL")}
    else:
        fields = {"model": ("GEMINI_MODEL",)}
    for field, names in fields.items():
        if field == "model" and os.environ.get("WEBAUDIT_MODEL"):
            continue
        for name in names:
            if os.environ.get(name):
                settings["llm"][field] = os.environ[name]
                sources[f"llm.{field}"] = name
                break
    for key, value in (overrides or {}).items():
        if value is not None:
            settings["llm"][key] = value
            sources[f"llm.{key}"] = "命令参数"
    if settings["llm"].get("provider") not in (None, "openai", "openai-compatible", "gemini"):
        raise ValueError("provider 仅支持 openai / openai-compatible / gemini")
    for key in ("model", "base_url", "secret_storage"):
        if key in settings["llm"] and not isinstance(settings["llm"][key], str):
            raise ValueError(f"llm.{key} 必须是字符串")
    if settings["llm"].get("secret_storage") not in (None, "environment", "keyring", "file"):
        raise ValueError("llm.secret_storage 仅支持 environment / keyring / file")
    for key in ("max_steps", "max_failures"):
        value = settings["run"].get(key)
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError(f"run.{key} 必须是正整数")
    stored_data = settings["storage"].get("data_dir")
    if stored_data is not None and not isinstance(stored_data, str):
        raise ValueError("storage.data_dir 必须是路径字符串")
    if data_dir or os.environ.get("WEBAUDIT_DATA_DIR"):
        data = resolve_path(data_dir or os.environ["WEBAUDIT_DATA_DIR"])
    elif stored_data:
        data = resolve_path(stored_data, config.parent)
    else:
        data = root / "data"
    sources["storage.data_dir"] = "命令参数" if data_dir else "WEBAUDIT_DATA_DIR" if os.environ.get("WEBAUDIT_DATA_DIR") else str(config) if stored_data else "默认值"
    return Runtime(root, data, config, settings, sources)


def get_runtime():
    return _current.get() or resolve_runtime()


def set_runtime(runtime):
    return _current.set(runtime)


def reset_runtime(token):
    _current.reset(token)


def new_run_id():
    return "run-" + uuid.uuid4().hex


def private_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)


def write_private(path, content):
    private_directory(path.parent)
    # Atomic replacement avoids truncated config/key files on failed writes.
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_home(runtime=None):
    runtime = runtime or get_runtime()
    private_directory(runtime.home)
    marker = runtime.home / ".webaudit-home"
    if not marker.exists():
        write_private(marker, "WebAudit managed home\n")
