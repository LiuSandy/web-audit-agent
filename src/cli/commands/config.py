"""Configuration onboarding, effective settings and storage discovery."""
import json

import typer

from src.runtime import get_runtime, write_private
from src.cli.core.errors import command_errors
from src.runtime.secrets import get_api_key, save_api_key

config_app = typer.Typer(help="初始化和查看配置")


@config_app.command("init")
@command_errors
def init_config(
    provider: str | None = typer.Option(None, "--provider"),
    model: str | None = typer.Option(None, "--model"),
    base_url: str | None = typer.Option(None, "--api-url"),
    secret_storage: str = typer.Option("keyring", "--secret-storage", help="keyring / file（文件明文，仅当前用户可读）"),
    non_interactive: bool = typer.Option(False, "--non-interactive", help="使用参数和环境变量配置，不保存环境变量中的密钥"),
    force: bool = typer.Option(False, "--force", help="更新已有配置"),
):
    runtime = get_runtime()
    previous = runtime.settings["llm"]
    if runtime.config_file.exists() and not force:
        if non_interactive or not typer.confirm(f"配置已存在：{runtime.config_file}。是否修改？", default=False):
            raise typer.Exit(0)
    provider = provider or previous.get("provider")
    if not non_interactive:
        provider = typer.prompt("模型服务商（openai / gemini / openai-compatible）", default=provider or "openai")
    provider = provider or "openai"
    if provider not in ("openai", "gemini", "openai-compatible"):
        raise typer.BadParameter("provider 仅支持 openai / gemini / openai-compatible")
    if secret_storage not in ("keyring", "file"):
        raise typer.BadParameter("secret-storage 仅支持 keyring / file")
    same_provider = provider == previous.get("provider")
    model = model or (previous.get("model") if same_provider else None) or ("gemini-2.5-flash-lite" if provider == "gemini" else "gpt-4o-mini")
    base_url = base_url if base_url is not None else previous.get("base_url", "") if same_provider else ""
    if not non_interactive:
        base_url = typer.prompt("接口地址（留空使用默认地址）", default=base_url, show_default=False)
        model = typer.prompt("模型名称", default=model)
    if base_url and not base_url.startswith(("https://", "http://")):
        raise typer.BadParameter("接口地址必须是 HTTP/HTTPS URL")
    try:
        key, source = get_api_key(provider, runtime)
    except RuntimeError:
        key, source = None, "系统凭据库不可用"
    storage = previous.get("secret_storage", "environment")
    if not non_interactive:
        entered = typer.prompt("API Key（隐藏输入，留空保留已有配置/使用环境变量）", default="", hide_input=True, show_default=False)
        if entered:
            if secret_storage == "file":
                typer.echo("API key 将保存为仅当前用户可读的明文文件。")
            save_api_key(provider, entered, secret_storage, runtime)
            storage = secret_storage
            source = secret_storage
            key = entered
    if not key and not (provider == "openai-compatible" and base_url):
        raise typer.BadParameter("缺少 API key，请输入密钥或设置 OPENAI_API_KEY / GOOGLE_AI_STUDIO_API_KEY")
    llm = {"provider": provider, "model": model, "secret_storage": storage}
    if base_url:
        llm["base_url"] = base_url
    sections = {"llm": llm, "run": {"max_steps": runtime.settings["run"].get("max_steps", 50),
                                      "max_failures": runtime.settings["run"].get("max_failures", 3)}}
    if runtime.settings["storage"]:
        sections["storage"] = runtime.settings["storage"]
    content = ""
    for section, values in sections.items():
        content += f"[{section}]\n"
        for name, value in values.items():
            if isinstance(value, (str, int, float, bool)):
                content += f"{name} = {json.dumps(value, ensure_ascii=False)}\n"
        content += "\n"
    from src.runtime import ensure_home
    ensure_home(runtime)
    write_private(runtime.config_file, content)
    typer.echo(f"配置已保存：{runtime.config_file}")
    typer.echo(f"API key 来源：{storage if source == '未配置' else source}")


@config_app.command("show")
@command_errors
def show_config(sources: bool = typer.Option(False, "--sources", help="显示每项配置的来源")):
    runtime = get_runtime()
    llm = runtime.settings["llm"]
    output = {"llm": {k: v for k, v in llm.items() if k in ("provider", "model", "base_url", "secret_storage")},
              "run": {k: v for k, v in runtime.settings["run"].items() if k in ("max_steps", "max_failures")},
              "storage": {"data_dir": str(runtime.data)}}
    key, source = get_api_key(llm.get("provider", "openai"), runtime)
    output["llm"]["api_key"] = "已配置（隐藏）" if key else "未配置"
    if sources:
        output["sources"] = {**runtime.sources, "llm.api_key": source}
    typer.echo(json.dumps(output, ensure_ascii=False, indent=2))


@command_errors
def paths_command():
    typer.echo(json.dumps(get_runtime().paths(), ensure_ascii=False, indent=2))


@config_app.command("reset")
@command_errors
def reset_config(yes: bool = typer.Option(False, "--yes")):
    path = get_runtime().config_file
    if not path.exists():
        typer.echo("配置文件不存在。")
        return
    typer.echo(f"删除配置：{path}（数据和凭据保留）")
    if not yes:
        typer.confirm("确认重置配置？", abort=True, default=False)
    path.unlink()
