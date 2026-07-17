from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_desk.operations.config import OperationsConfiguration


def test_operations_are_disabled_and_loopback_only_by_default() -> None:
    configuration = OperationsConfiguration()
    assert configuration.enabled is False
    assert configuration.host == "127.0.0.1"
    assert configuration.read_only is True
    assert configuration.allow_remote_bind is False
    assert configuration.environment == "IG DEMO"


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.2", "example.com", "::"])
def test_remote_bind_is_rejected(host: str) -> None:
    with pytest.raises(ValidationError, match="loopback|remote"):
        OperationsConfiguration(host=host)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_bind_is_accepted(host: str) -> None:
    assert OperationsConfiguration(host=host).host == host


def test_authority_and_environment_cannot_be_changed() -> None:
    with pytest.raises(ValidationError):
        OperationsConfiguration.model_validate({"read_only": False})
    with pytest.raises(ValidationError):
        OperationsConfiguration.model_validate({"environment": "LIVE"})
    with pytest.raises(ValidationError):
        OperationsConfiguration.model_validate({"allow_remote_bind": True})


def test_limits_and_configuration_are_immutable() -> None:
    configuration = OperationsConfiguration(maximum_query_records=50, maximum_replay_records=100)
    with pytest.raises(ValidationError):
        OperationsConfiguration(maximum_query_records=101, maximum_replay_records=100)
    with pytest.raises(ValidationError):
        configuration.port = 9000  # type: ignore[misc]


def test_configuration_fingerprint_is_stable_and_path_safe(tmp_path: Path) -> None:
    first = OperationsConfiguration(frontend_directory=tmp_path / "dist")
    second = OperationsConfiguration(frontend_directory=tmp_path / "dist")
    assert first.configuration_fingerprint == second.configuration_fingerprint
    assert len(first.configuration_fingerprint) == 64
