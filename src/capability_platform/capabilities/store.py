import json
from pathlib import Path

from capability_platform.models import CapabilityArtifact


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, artifact: CapabilityArtifact) -> Path:
        path = self.root / f"{artifact.qualified_id}.json"
        path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, qualified_id: str) -> CapabilityArtifact:
        path = self.root / f"{qualified_id}.json"
        return CapabilityArtifact.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[CapabilityArtifact]:
        return [
            CapabilityArtifact.model_validate(json.loads(p.read_text()))
            for p in self.root.glob("*.json")
        ]
