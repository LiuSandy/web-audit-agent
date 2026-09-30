"""Shared helpers for DOM snapshots and page utilities."""

import re


def get_selector(el) -> str:
    if el.id:
        return f"#{el.id}"
    path = el.tag_name.lower()
    if el.className and isinstance(el.className, str):
        classes = [value for value in re.split(r"\s+", el.className) if value]
        if classes:
            path += "." + ".".join(classes)
    parent = el.parentElement
    if parent:
        siblings = [child for child in parent.children if child.tag_name == el.tag_name]
        if len(siblings) > 1:
            path += f":nth-of-type({siblings.index(el) + 1})"
        parent_path = parent.tag_name.lower()
        if parent.id:
            parent_path = f"#{parent.id}"
        elif parent.className and isinstance(parent.className, str):
            classes = [value for value in re.split(r"\s+", parent.className) if value]
            if classes:
                parent_path += "." + ".".join(classes)
        path = f"{parent_path} > {path}"
    return path
