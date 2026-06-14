"""Model registry: versioned models + a champion pointer, on disk.

Layout under models/<granularity>/:
  registry.json          -> {champion, versions[]}
  <version_id>/          -> model.joblib, meta.json, report.json

The champion is the model the live strategy loads. Each retraining round
registers a new version and promotes the round winner, so weaker configs are
naturally left behind (abandoned) and the best is reinforced.
"""

import json
from pathlib import Path


class ModelRegistry:
    def __init__(self, base_dir: Path, granularity: str):
        self._dir = Path(base_dir) / granularity
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "registry.json"

    def _load(self) -> dict:
        if self._path.exists():
            return json.loads(self._path.read_text(encoding="utf-8"))
        return {"granularity": self._dir.name, "champion": None, "versions": []}

    def _save(self, data: dict) -> None:
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def version_dir(self, version_id: str) -> Path:
        return self._dir / version_id

    def champion(self) -> str | None:
        return self._load().get("champion")

    def champion_dir(self) -> Path | None:
        champ = self.champion()
        if champ:
            directory = self.version_dir(champ)
            if (directory / "model.joblib").exists():
                return directory
        return None

    def versions(self) -> list[dict]:
        return self._load().get("versions", [])

    def add_version(
        self, version_id: str, config: dict, metrics: dict, make_champion: bool
    ) -> None:
        data = self._load()
        data["versions"].append(
            {"id": version_id, "config": config, "metrics": metrics}
        )
        # Keep the list bounded — old versions stay on disk but the registry
        # only tracks the most recent ones for the dashboard.
        data["versions"] = data["versions"][-50:]
        if make_champion:
            data["champion"] = version_id
        self._save(data)

    def set_champion(self, version_id: str) -> None:
        data = self._load()
        data["champion"] = version_id
        self._save(data)
