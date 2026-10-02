"""Remove only a managed WebAudit home; package removal belongs to the installer."""
from pathlib import Path
import shutil

import typer

from src.cli.core.errors import command_errors
from src.database.database import AppDatabase
from src.runtime import get_runtime
from src.runtime.secrets import delete_keyring_keys


@command_errors
def uninstall_command():
    runtime = get_runtime()
    root = runtime.home
    if root.is_symlink() or root.resolve() in (Path(root.anchor), Path.home().resolve(), Path.cwd().resolve()):
        raise typer.BadParameter(f"拒绝删除不安全的根目录：{root}")
    if not root.exists():
        typer.echo(f"目录不存在，无需清理：{root}")
        return
    if not (root / ".webaudit-home").is_file():
        raise typer.BadParameter(f"目录没有 WebAudit 管理标识，拒绝删除：{root}")
    if runtime.settings["llm"].get("secret_storage") == "keyring" or (runtime.credentials / "keyring.json").exists():
        try:
            delete_keyring_keys(runtime)
        except Exception as error:
            typer.echo(f"无法删除系统凭据，请先解除凭据库锁定后重试：{error}", err=True)
            raise typer.Exit(1)
    AppDatabase.reset()
    # rmtree removes links themselves rather than following their targets.
    shutil.rmtree(root)
    typer.echo(f"已删除配置和数据：{root}")
    if not runtime.data.is_relative_to(root):
        typer.echo(f"根目录外的数据目录已保留：{runtime.data}")
    if not runtime.config_file.is_relative_to(root):
        typer.echo(f"根目录外的配置文件已保留：{runtime.config_file}")
    typer.echo("程序安装包仍保留；使用安装工具卸载（例如 uv tool uninstall web-audit-agent）。")
