"""Shared AST probes for the boundary tests.

The rules these check -- no provider may import SQLAlchemy, only the
composition root may name a concrete provider -- are the kind that fail
silently. The code keeps working after the boundary is crossed; it just becomes
impossible to swap a provider or to trust where data came from. So they are
checked by reading imports rather than by trusting the docstrings.

Kept in one place so the two suites that need it cannot drift into checking
slightly different things.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
APP_ROOT = TESTS_ROOT.parent / "app"
PROVIDER_ROOT = APP_ROOT / "providers"
COMPOSITION_ROOT = APP_ROOT / "composition.py"

#: Modules allowed to name a concrete provider. Nothing else may.
CONCRETE_PROVIDERS = ("app.providers.data.mock", "app.providers.ai.mock")

#: Anything that could open a socket.
NETWORK_MODULES = frozenset(
    {"socket", "ssl", "http", "httpx", "requests", "urllib", "urllib3", "aiohttp"}
)

#: Anything that could reach persistence.
DATABASE_MODULES = frozenset({"sqlalchemy", "alembic"})

#: Anything that could write to the filesystem.
FILESYSTEM_MODULES = frozenset({"pathlib", "os", "shutil"})


def module_paths(root: Path) -> list[Path]:
    """Every Python module under `root`, in a stable order."""
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def imported_modules(path: Path) -> set[str]:
    """Every module name a file imports, however the import is spelled.

    Parsed rather than grepped, so a name inside a docstring or a comment is
    never mistaken for a dependency.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def top_level(names: set[str]) -> set[str]:
    """The root package of each imported name, for membership tests."""
    return {name.split(".")[0] for name in names}
