"""Tests du kill switch dynamique persistant."""

from pathlib import Path

import pytest

from app.risk.kill_switch import KillSwitch


def test_initial_state_unlocked(tmp_path: Path):
    ks = KillSwitch(tmp_path / "ks.json")
    assert ks.locked is False
    assert ks.reason is None


def test_lock_sets_reason_and_persists(tmp_path: Path):
    path = tmp_path / "ks.json"
    ks = KillSwitch(path)
    status = ks.lock("Perte quotidienne atteinte", source="auto")
    assert status["locked"] is True
    assert status["reason"] == "Perte quotidienne atteinte"
    assert status["source"] == "auto"

    # Un redémarrage (nouvelle instance) doit retrouver le verrou.
    ks2 = KillSwitch(path)
    assert ks2.locked is True
    assert ks2.reason == "Perte quotidienne atteinte"


def test_lock_is_idempotent_and_keeps_first_reason(tmp_path: Path):
    ks = KillSwitch(tmp_path / "ks.json")
    ks.lock("Première cause")
    ks.lock("Deuxième cause")
    assert ks.locked is True
    assert ks.reason == "Première cause"
    # Les deux événements restent tracés.
    events = ks.status()["recent_events"]
    assert len(events) == 2
    assert events[1]["already_locked"] is True


def test_unlock_requires_reason(tmp_path: Path):
    ks = KillSwitch(tmp_path / "ks.json")
    ks.lock("Cause")
    with pytest.raises(ValueError):
        ks.unlock("")
    with pytest.raises(ValueError):
        ks.unlock("   ")
    assert ks.locked is True


def test_unlock_with_reason(tmp_path: Path):
    path = tmp_path / "ks.json"
    ks = KillSwitch(path)
    ks.lock("Cause")
    status = ks.unlock("Analyse faite, conditions revenues à la normale")
    assert status["locked"] is False

    ks2 = KillSwitch(path)
    assert ks2.locked is False


def test_corrupt_state_file_locks_preventively(tmp_path: Path):
    path = tmp_path / "ks.json"
    path.write_text("{invalid json", encoding="utf-8")
    ks = KillSwitch(path)
    # Un état illisible ne doit JAMAIS se traduire par « tout est permis ».
    assert ks.locked is True
    assert "illisible" in (ks.reason or "")
