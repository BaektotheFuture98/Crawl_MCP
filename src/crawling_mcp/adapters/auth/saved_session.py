from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from crawling_mcp.domain.errors import AuthenticationRequiredError
from crawling_mcp.domain.models import AuthProfile


class _ProfilesDocument(BaseModel):
    profiles: dict[str, AuthProfile] = Field(default_factory=dict)


class AuthProfileStore:
    """Lookup store for non-secret authentication profiles."""

    def __init__(self, profiles: Mapping[str, AuthProfile]) -> None:
        self._profiles = dict(profiles)

    @classmethod
    def from_yaml(cls, path: Path) -> AuthProfileStore:
        """Load validated profiles from YAML, or an empty store when absent."""
        if not path.is_file():
            return cls({})
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        document = _ProfilesDocument.model_validate(raw)
        return cls(document.profiles)

    def get(self, name: str) -> AuthProfile:
        """Return a profile without resolving its secrets."""
        profile = self._profiles.get(name)
        if profile is None:
            raise AuthenticationRequiredError(profile=name, reason="profile_not_found")
        return profile.model_copy(deep=True)

    def names(self) -> tuple[str, ...]:
        """Return configured profile names."""
        return tuple(sorted(self._profiles))


def resolve_storage_path(auth_root: Path, candidate: Path) -> Path:
    """Resolve a JSON storage-state path confined to the authentication root."""
    root = auth_root.resolve()
    if candidate.suffix.lower() != ".json":
        raise AuthenticationRequiredError(reason="storage_state_must_be_json")
    if candidate.is_absolute():
        resolved = candidate.resolve()
    elif candidate.parent == Path("."):
        resolved = (root / candidate).resolve()
    elif candidate.parts[-3:-1] == ("data", "auth"):
        resolved = (root / candidate.name).resolve()
    else:
        resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise AuthenticationRequiredError(reason="storage_state_outside_auth_root") from error
    return resolved
