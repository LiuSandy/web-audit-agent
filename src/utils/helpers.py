"""Port of src/utils/helpers.ts for DOM-compatible element objects."""

import re


def getSelector(el) -> str:
    if el.id:
        return f"#{el.id}"
    path = el.tagName.lower()
    if el.className and isinstance(el.className, str):
        classes = [value for value in re.split(r"\s+", el.className) if value]
        if classes:
            path += "." + ".".join(classes)
    parent = el.parentElement
    if parent:
        siblings = [child for child in parent.children if child.tagName == el.tagName]
        if len(siblings) > 1:
            path += f":nth-of-type({siblings.index(el) + 1})"
        parentPath = parent.tagName.lower()
        if parent.id:
            parentPath = f"#{parent.id}"
        elif parent.className and isinstance(parent.className, str):
            classes = [value for value in re.split(r"\s+", parent.className) if value]
            if classes:
                parentPath += "." + ".".join(classes)
        path = f"{parentPath} > {path}"
    return path
