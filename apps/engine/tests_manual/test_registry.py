"""Deterministic check of the model registry (no network/DB/training).

Run: .venv\\Scripts\\python.exe -m tests_manual.test_registry
"""

import tempfile
from pathlib import Path

from app.learning.registry import ModelRegistry


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        reg = ModelRegistry(base, "M5")

        assert reg.champion() is None
        assert reg.champion_dir() is None
        assert reg.versions() == []

        # First version becomes champion; create its model file so champion_dir resolves.
        v1 = reg.version_dir("v1")
        v1.mkdir(parents=True)
        (v1 / "model.joblib").write_bytes(b"x")
        reg.add_version("v1", {"horizon": 12}, {"sharpe": -5.0}, make_champion=True)
        assert reg.champion() == "v1", reg.champion()
        assert reg.champion_dir() == v1

        # Second version promoted -> champion moves.
        v2 = reg.version_dir("v2")
        v2.mkdir(parents=True)
        (v2 / "model.joblib").write_bytes(b"x")
        reg.add_version("v2", {"horizon": 24}, {"sharpe": -2.0}, make_champion=True)
        assert reg.champion() == "v2", reg.champion()
        assert len(reg.versions()) == 2

        # Persistence: a fresh instance reads the same champion.
        assert ModelRegistry(base, "M5").champion() == "v2"

        # Champion pointing at a missing model file -> champion_dir is None.
        reg.set_champion("v_missing")
        assert reg.champion_dir() is None

    print("OK: registre valide")


if __name__ == "__main__":
    main()
