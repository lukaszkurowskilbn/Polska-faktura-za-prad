"""Fixtures testów warstwy HA (uruchamiane tylko, gdy zainstalowano plugin HA)."""

import pytest

try:  # plugin jest opcjonalny — bez niego testy z tests/ha są pomijane
    import pytest_homeassistant_custom_component  # noqa: F401
except ImportError:  # pragma: no cover
    collect_ignore_glob = ["test_*.py"]
else:

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Pozwala HA ładować custom_components z repozytorium."""
        yield
