"""Attribution extension point for multiplayer Figma write auditing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class AttributionEvidence:
    status: str
    actor: str
    revision: str
    source: str
    reason: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "actor": self.actor,
            "revision": self.revision,
            "source": self.source,
            "reason": self.reason,
        }


class AttributionProvider(Protocol):
    def resolve(self, transaction: Any) -> AttributionEvidence: ...


class UnavailableAttributionProvider:
    """Current default: Figma Plugin API has no authoritative actor/revision."""

    def resolve(self, transaction: Any) -> AttributionEvidence:
        del transaction
        return AttributionEvidence(
            status="unavailable",
            actor="unknown",
            revision="unknown",
            source="figma-plugin-api",
            reason=(
                "Figma Plugin API does not expose an authoritative write "
                "actor or revision"
            ),
        )
