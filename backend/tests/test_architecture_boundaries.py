"""Architectural boundaries, checked mechanically.

These are the rules that hold as the codebase grows, and every one of them is
the kind that decays quietly: a provider that starts importing SQLAlchemy, a
service that reaches for a concrete class, a mock that acquires an HTTP client.
None of them fail loudly when they break -- the code still works, just with the
wrong dependency -- so they are checked here by reading the imports rather than
by trusting the docstrings.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from _ast_probe import (
    APP_ROOT,
    COMPOSITION_ROOT,
    CONCRETE_PROVIDERS,
    DATABASE_MODULES,
    FILESYSTEM_MODULES,
    NETWORK_MODULES,
    PROVIDER_ROOT,
    imported_modules,
    module_paths,
    top_level,
)

from app.composition import build_ad_provider, build_ai_provider
from app.providers.ai.base import AIProvider
from app.providers.data.base import AdDataProvider
from app.providers.data.provenance import DataOrigin, EvidenceClass

PROVIDER_MODULES = module_paths(PROVIDER_ROOT)
APP_MODULES = module_paths(APP_ROOT)


# ============================================================
# A provider is not allowed to know about persistence or files
# ============================================================


@pytest.mark.parametrize("path", PROVIDER_MODULES, ids=lambda p: p.name)
def test_no_provider_imports_the_database(path: Path) -> None:
    """A provider returns data. The orchestrator persists it.

    A provider with a session could decide what gets stored, which is exactly
    the split that makes providers replaceable.
    """
    imported = imported_modules(path)
    assert not top_level(imported) & DATABASE_MODULES
    assert not any(name.startswith("app.db") for name in imported)


@pytest.mark.parametrize("path", PROVIDER_MODULES, ids=lambda p: p.name)
def test_no_provider_can_write_a_file(path: Path) -> None:
    """No caching, no media, no writing logs to disk."""
    assert not top_level(imported_modules(path)) & FILESYSTEM_MODULES


@pytest.mark.parametrize("path", PROVIDER_MODULES, ids=lambda p: p.name)
def test_no_provider_reaches_the_network(path: Path) -> None:
    """Not a rule imposed on mocks only -- no provider may, ever, in S0.3.

    A real provider will need HTTP in a later checkpoint. That checkpoint has to
    change this deliberately, rather than discover that the guard was quietly
    switched off.
    """
    assert not top_level(imported_modules(path)) & NETWORK_MODULES


# ============================================================
# Concrete providers are reachable only through the composition root
# ============================================================


@pytest.mark.parametrize("path", APP_MODULES, ids=lambda p: p.name)
def test_only_the_composition_root_names_a_concrete_provider(path: Path) -> None:
    """Business code receives a provider. It must not be able to build one.

    A provider's own module names itself and the composition root builds it.
    Nothing else may, or a service could quietly depend on the mock and stop
    working the day a real provider replaced it.
    """
    hits = {
        name
        for name in imported_modules(path)
        if any(name.startswith(f"{concrete}.") for concrete in CONCRETE_PROVIDERS)
    }
    if path.name == "mock.py" or path == COMPOSITION_ROOT:
        return
    assert not hits, f"{path.name} imports a concrete provider: {sorted(hits)}"


def test_the_composition_root_returns_protocols_not_classes() -> None:
    """A caller handed the concrete type can reach past the interface.

    Annotated as the protocol, so `result.fetch_fixture()` does not exist and a
    future provider swap cannot leak implementation detail into a caller.
    """
    assert inspect.signature(build_ad_provider).return_annotation == "AdDataProvider"
    assert inspect.signature(build_ai_provider).return_annotation == "AIProvider"


def test_the_composition_root_builds_something_usable() -> None:
    assert isinstance(build_ad_provider({}), AdDataProvider)
    assert isinstance(build_ai_provider({}), AIProvider)
    assert build_ad_provider({}).name == "mock"
    assert build_ai_provider({}).name == "mock-ai"


# ============================================================
# The seams are separate modules, not one growing file
# ============================================================


def test_each_protocol_has_its_own_module() -> None:
    """A single `contracts.py` would be a place where unrelated seams accumulate.

    Checked through `__module__` rather than by grepping the source, so
    reformatting the class declaration cannot silently turn this into a test
    that passes for the wrong reason.
    """
    assert AdDataProvider.__module__ == "app.providers.data.base"
    assert AIProvider.__module__ == "app.providers.ai.base"


def test_the_media_and_queue_seams_do_not_depend_on_the_provider_seam() -> None:
    """Media and jobs are not ad collection.

    Co-locating them would invite a provider to reach for one, and would make
    swapping an ad provider look like a storage change.
    """
    services = APP_ROOT / "services"
    for module in ("media.py", "jobs.py"):
        imported = imported_modules(services / module)
        assert not any(name.startswith("app.providers") for name in imported), module
        assert not any(name.startswith("app.services") for name in imported), module
    assert "MediaStore" not in (services / "jobs.py").read_text(encoding="utf-8")


def test_provenance_lives_in_its_own_small_module() -> None:
    """The two axes are shared vocabulary, not provider-specific detail.

    Keeping them in their own module is what makes it visible that services and
    schemas may import them without importing a provider, and the data models
    import them from that one home rather than declaring their own.
    """
    assert DataOrigin.__module__ == "app.providers.data.provenance"
    assert EvidenceClass.__module__ == "app.providers.data.provenance"
    assert "app.providers.data.provenance" in imported_modules(PROVIDER_ROOT / "data" / "models.py")
