"""Convert filesystem/configuration failures into concise CLI errors."""
from functools import wraps

import typer


def command_errors(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (OSError, ValueError, RuntimeError) as error:
            typer.echo(f"错误：{error}", err=True)
            raise typer.Exit(1) from error
    return wrapped
