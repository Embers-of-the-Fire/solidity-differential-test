from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class CampaignConfig:
    root_dir: Path
    artifact_dir: Path
    solang_target: str = "solana"
    timeout_seconds: int = 20
    seed: int = 0

    @property
    def queue_dir(self) -> Path:
        return self.artifact_dir / "queue"

    @property
    def interesting_dir(self) -> Path:
        return self.artifact_dir / "interesting"

    @property
    def crashes_dir(self) -> Path:
        return self.artifact_dir / "crashes"

    @property
    def repro_dir(self) -> Path:
        return self.artifact_dir / "repro"


def default_config(root_dir: Path | None = None) -> CampaignConfig:
    resolved_root = (root_dir or Path(__file__).resolve().parents[2]).resolve()
    artifact_dir = resolved_root / "artifacts"
    return CampaignConfig(root_dir=resolved_root, artifact_dir=artifact_dir)
