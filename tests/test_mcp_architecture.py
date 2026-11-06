"""MCP blijft HTTP-client; lokale transportwaarden drijven niet van API af."""

import ast
from pathlib import Path

from betonning import mcp_server
from betonning.repo import attachments, model_classes


def test_mcp_has_no_data_layer_imports():
    source = Path(mcp_server.__file__).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                assert module.split(".")[0] not in {"repo", "db"}
            assert not module.startswith(("betonning.repo", "betonning.db"))
        if isinstance(node, ast.Import):
            assert all(
                not alias.name.startswith(("betonning.repo", "betonning.db", "sqlite3"))
                for alias in node.names
            )


def test_transport_constants_follow_published_protocol():
    assert mcp_server._WORK_CLASS_ORDER == model_classes.CLASSES
    assert mcp_server.MAX_INLINE_ATTACHMENT_BYTES <= attachments.MAX_SIZE
