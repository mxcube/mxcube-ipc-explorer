"""Renders a JSON-like Python value (dict/list/scalar) into a Textual
Tree, one collapsible node per key/index - the result pane's "browse the
nested queue" view.
"""

from __future__ import annotations

from typing import Any

from textual.widgets import Tree
from textual.widgets.tree import TreeNode


def _label_for(value: Any) -> str:
    if isinstance(value, dict):
        return f"{{ }}  {len(value)} key{'s' if len(value) != 1 else ''}"
    if isinstance(value, list):
        return f"[ ]  {len(value)} item{'s' if len(value) != 1 else ''}"
    return repr(value)


def _populate(node: TreeNode, value: Any) -> None:
    if isinstance(value, dict):
        items = value.items()
    elif isinstance(value, list):
        items = enumerate(value)
    else:
        return

    for key, child in items:
        label = f"{key}: {_label_for(child)}"
        if isinstance(child, (dict, list)) and child:
            child_node = node.add(label, data=child)
            _populate(child_node, child)
        else:
            node.add_leaf(f"{key}: {child!r}", data=child)


def render_json_tree(tree: Tree, value: Any) -> None:
    """Clears <tree> and rebuilds it to represent <value>, expanded one
    level deep (nested containers start collapsed).

    The tree's root row itself is hidden (App.on_mount sets
    show_root = False), so a bare scalar (or an empty dict/list) - which
    _populate() adds no children for - has to be represented as a leaf
    under the root, not just as the root's own label, or it wouldn't be
    visible at all.
    """
    tree.clear()
    tree.root.data = value
    if isinstance(value, (dict, list)) and value:
        tree.root.label = _label_for(value)
        _populate(tree.root, value)
    else:
        tree.root.label = "result"
        tree.root.add_leaf(repr(value), data=value)
    tree.root.expand()
