"""Figma Plugin API 适配器（通过本地 WebSocket 桥接）。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import ssl
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from src.app.services.bridge_config import load_bridge_config
from src.app.services.job_namespace import (
    JOB_NAMESPACE_PREFIX,
    JobNamespaceError,
    build_job_namespace,
    validate_job_namespace,
)
from src.app.services.rendering.adapter_base import (
    PrototypeAdapter,
    _offset_box,
    _single_line_text,
)
from src.app.services.rendering.write_job_ledger import CompensationScope
from src.config.settings import Config

logger = logging.getLogger(__name__)
SEMANTIC_FIGMA_COMPONENTS_FILENAME = "21_semantic_components_figma.json"


@dataclass(frozen=True, slots=True)
class PermissionOutcome:
    category: str
    retryable: bool
    no_resend: bool
    manual_review: bool
    reason: str
    retry_after_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "retryable": self.retryable,
            "no_resend": self.no_resend,
            "manual_review": self.manual_review,
            "reason": self.reason,
            "retry_after_ms": self.retry_after_ms,
        }


@dataclass(frozen=True, slots=True)
class ManualReviewDecision:
    action: str
    transaction_state: str
    recommendation: str
    actor: str
    revision: str
    resend_allowed: bool
    manual_review_required: bool
    owned_node_ids: tuple[str, ...]
    current_state: Any
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "transaction_state": self.transaction_state,
            "recommendation": self.recommendation,
            "actor": self.actor,
            "revision": self.revision,
            "resend_allowed": self.resend_allowed,
            "manual_review_required": self.manual_review_required,
            "owned_node_ids": list(self.owned_node_ids),
            "current_state": self.current_state,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ExpectedRegionEvaluation:
    classification: str
    checks: dict[str, str]
    matched: int
    mismatched: int
    unknown: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "checks": dict(self.checks),
            "matched": self.matched,
            "mismatched": self.mismatched,
            "unknown": self.unknown,
        }


@dataclass(frozen=True, slots=True)
class RegionCompensationPlan:
    status: str
    scope: dict[str, Any]
    remove_node_ids: tuple[str, ...]
    preserved_node_ids: tuple[str, ...]
    unknown_node_ids: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "scope": dict(self.scope),
            "remove_node_ids": list(self.remove_node_ids),
            "preserved_node_ids": list(self.preserved_node_ids),
            "unknown_node_ids": list(self.unknown_node_ids),
            "reason": self.reason,
        }


def evaluate_expected_region(
    expected: dict[str, Any],
    readback: dict[str, Any],
) -> ExpectedRegionEvaluation:
    checks: dict[str, str] = {}
    for key in (
        "imageFillSha256",
        "layoutSnapshot",
        "bounds",
        "textRuns",
        "regionMembership",
    ):
        if key not in expected:
            continue
        if key not in readback:
            checks[key] = "unknown"
        else:
            checks[key] = (
                "matched"
                if _expected_value_matches(key, expected[key], readback.get(key))
                else "mismatched"
            )
    unknown = sum(value == "unknown" for value in checks.values())
    matched = sum(value == "matched" for value in checks.values())
    mismatched = sum(value == "mismatched" for value in checks.values())
    if not checks:
        classification = "indeterminate"
    elif matched == len(checks):
        classification = "matches-intended"
    elif matched > 0:
        classification = "partial-match"
    elif mismatched > 0:
        classification = "does-not-match-intended"
    else:
        classification = "indeterminate"
    return ExpectedRegionEvaluation(
        classification=classification,
        checks=checks,
        matched=matched,
        mismatched=mismatched,
        unknown=unknown,
    )


def plan_region_compensation(
    scope: CompensationScope,
    *,
    owned_nodes: dict[str, dict[str, Any]],
) -> RegionCompensationPlan:
    if scope.user_takeover_state not in {"none", "clear", "not-observed"}:
        return RegionCompensationPlan(
            status="rollback-incomplete/manual-review",
            scope=scope.to_dict(),
            remove_node_ids=(),
            preserved_node_ids=tuple(scope.node_ids),
            unknown_node_ids=(),
            reason="User takeover makes automatic compensation unsafe.",
        )
    remove: list[str] = []
    preserved: list[str] = []
    unknown: list[str] = []
    for node_id in scope.node_ids:
        marker = owned_nodes.get(node_id)
        if not isinstance(marker, dict):
            unknown.append(node_id)
            continue
        if (
            marker.get("job_id") == scope.job_id
            and marker.get("owner") == "figma_auto_agent"
        ):
            marker_region = str(marker.get("region_id") or marker.get("regionId") or "")
            if marker_region == scope.region_id:
                remove.append(node_id)
            elif marker_region:
                preserved.append(node_id)
            else:
                unknown.append(node_id)
        else:
            preserved.append(node_id)
    if unknown:
        return RegionCompensationPlan(
            status="rollback-incomplete/manual-review",
            scope=scope.to_dict(),
            remove_node_ids=(),
            preserved_node_ids=tuple(preserved),
            unknown_node_ids=tuple(unknown),
            reason="Ownership evidence is incomplete.",
        )
    return RegionCompensationPlan(
        status="compensable",
        scope=scope.to_dict(),
        remove_node_ids=tuple(remove),
        preserved_node_ids=tuple(preserved),
        unknown_node_ids=(),
        reason="Only nodes with the exact job and owner markers are removable.",
    )


def classify_permission_failure(error: Any) -> PermissionOutcome:
    payload = error if isinstance(error, dict) else {}
    code = str(payload.get("code") or getattr(error, "code", "") or "")
    message = str(payload.get("message") or payload.get("error") or str(error) or "")
    text = f"{code} {message}".lower()
    retry_after_ms = payload.get("retryAfterMs")
    if not isinstance(retry_after_ms, (int, float)):
        retry_after_ms = getattr(error, "retry_after_ms", None)
    retry_value = (
        int(retry_after_ms) if isinstance(retry_after_ms, (int, float)) else None
    )
    if any(
        token in text for token in ("view-only", "view only", "readonly", "read-only")
    ):
        return PermissionOutcome(
            category="view-only",
            retryable=False,
            no_resend=True,
            manual_review=True,
            reason="The document is view-only.",
        )
    if any(token in text for token in ("rate limit", "too many requests", "429")):
        return PermissionOutcome(
            category="rate-limited",
            retryable=True,
            no_resend=False,
            manual_review=False,
            reason="Figma rate limit rejected the operation before commit.",
            retry_after_ms=retry_value,
        )
    if any(
        token in text
        for token in (
            "token revoked",
            "revoked token",
            "invalid token",
            "unauthorized",
            "401",
        )
    ):
        return PermissionOutcome(
            category="plugin-token-revoked",
            retryable=False,
            no_resend=True,
            manual_review=True,
            reason="The plugin token is revoked or no longer authorized.",
        )
    if any(
        token in text for token in ("takeover", "replaced by", "connection replaced")
    ):
        return PermissionOutcome(
            category="plugin-takeover",
            retryable=False,
            no_resend=True,
            manual_review=True,
            reason="Another plugin connection took over the writer.",
        )
    if any(
        token in text
        for token in ("permission", "forbidden", "403", "access denied", "not allowed")
    ):
        return PermissionOutcome(
            category="permission-denied",
            retryable=False,
            no_resend=True,
            manual_review=True,
            reason="Figma denied the requested write.",
        )
    if any(
        token in text
        for token in (
            "precondition",
            "modified",
            "collaborator",
            "conflict",
            "not found",
        )
    ):
        return PermissionOutcome(
            category="user-modification",
            retryable=False,
            no_resend=True,
            manual_review=True,
            reason="The target changed after intent was recorded.",
        )
    return PermissionOutcome(
        category="unknown",
        retryable=False,
        no_resend=True,
        manual_review=True,
        reason="The failure category is not authoritative.",
    )


def reconciliation_policy(
    transaction: Any,
    readback: Any,
    attribution: Any,
) -> ManualReviewDecision:
    tx = _object_mapping(transaction)
    rb = _object_mapping(readback)
    attr = _object_mapping(attribution)
    authoritative = str(attr.get("status") or "") == "authoritative" and bool(
        attr.get("actor") and attr.get("revision")
    )
    actor = str(attr.get("actor") or "unknown") if authoritative else "unknown"
    revision = str(attr.get("revision") or "unknown") if authoritative else "unknown"
    state = str(tx.get("state") or "unknown")
    status = str(rb.get("status") or "indeterminate")
    owned = tuple(str(item) for item in (rb.get("owned_node_ids") or ()))
    if status in {"node-deleted", "deleted", "parent-deleted"}:
        recommendation = "rollback-incomplete-manual-review"
        reason = "An owned node was deleted concurrently."
    elif status in {"mismatch", "conflict", "external-conflict"}:
        recommendation = "operator-resolve-conflict"
        reason = "Current state conflicts with the write intent."
    elif status == "partial-match":
        recommendation = "operator-reconcile-partial-state"
        reason = "Only part of the intended state is observable; operator review is required."
    elif status in {"matches", "matches-intended"}:
        recommendation = "operator-confirm-no-resend"
        reason = (
            "Matching state is current-state evidence only; it does not prove "
            "the actor or revision."
        )
    else:
        recommendation = "operator-reconcile-unknown"
        reason = "The current state cannot be attributed safely."
    return ManualReviewDecision(
        action="manual-review",
        transaction_state=state,
        recommendation=recommendation,
        actor=actor,
        revision=revision,
        resend_allowed=False,
        manual_review_required=True,
        owned_node_ids=owned,
        current_state=rb.get("current_state"),
        reason=reason,
    )


def _expected_value_matches(property_name: str, expected: Any, actual: Any) -> bool:
    if property_name == "layoutSnapshot" and isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            actual.get(name) == value for name, value in expected.items()
        )
    if property_name == "textRuns" and isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        for expected_run, actual_run in zip(expected, actual, strict=True):
            if isinstance(expected_run, dict):
                if not isinstance(actual_run, dict) or not all(
                    actual_run.get(name) == value
                    for name, value in expected_run.items()
                ):
                    return False
            elif expected_run != actual_run:
                return False
        return True
    if property_name == "regionMembership" and isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            actual.get(name) == value for name, value in expected.items()
        )
    return actual == expected


def _object_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    names = (
        "transactionId",
        "transaction_id",
        "state",
        "action",
        "status",
        "owned_node_ids",
        "current_state",
        "actor",
        "revision",
    )
    return {name: getattr(value, name) for name in names if hasattr(value, name)}


class FigmaBridgeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        outcome: str,
        request_id: str,
        retry_after_ms: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.outcome = outcome
        self.request_id = request_id
        self.retry_after_ms = retry_after_ms


class FigmaBridgeAdapter(PrototypeAdapter):
    """通过本地 WebSocket 桥接调用 Figma Plugin API。"""

    # Figma 只有 FRAME 能裁子元素（clipsContent），所以走真嵌套：
    # 子元素真的挂到裁剪容器下，坐标由 adapter_base 换成父级相对。
    supports_clip_frames = True

    def __init__(
        self,
        bridge_url: str | None = None,
        timeout: float | None = None,
        *,
        client_id: str | None = None,
        auth_token: str | None = None,
        client_token: str | None = None,
        allow_legacy_job_ids: bool | None = None,
        config_path: str | None = None,
    ):
        file_config = load_bridge_config(config_path)
        client_config = file_config.client
        self._client_config = client_config
        self.config_path = file_config.config_path
        environment = os.environ if file_config.allow_env_overrides else {}
        env_url = environment.get("FIGMA_BRIDGE_URL", "").strip()
        self.bridge_url = str(bridge_url or env_url or client_config.url).rstrip("/")
        env_timeout = environment.get("FIGMA_BRIDGE_TIMEOUT", "").strip()
        self.timeout = float(
            timeout if timeout is not None else env_timeout or client_config.timeout
        )
        resolved_client_token = (
            client_token
            if client_token is not None
            else environment.get("FIGMA_BRIDGE_CLIENT_TOKEN", "").strip()
            or client_config.client_token
        )
        self.client_token = (
            str(resolved_client_token).strip()
            if resolved_client_token is not None
            else None
        ) or None
        normalized_client_id = str(client_id or client_config.client_id or "").strip()
        if self.client_token and not normalized_client_id:
            raise ValueError("client_id is required when client_token is configured")
        self.client_id = normalized_client_id or uuid.uuid4().hex
        if allow_legacy_job_ids is None:
            env_legacy = (
                environment.get(
                    "FIGMA_BRIDGE_ALLOW_LEGACY_JOB_IDS",
                    "",
                )
                .strip()
                .lower()
            )
            if env_legacy in {"1", "true", "yes"}:
                allow_legacy_job_ids = True
            elif env_legacy in {"0", "false", "no", ""}:
                allow_legacy_job_ids = client_config.allow_legacy_job_ids
            else:
                raise ValueError("FIGMA_BRIDGE_ALLOW_LEGACY_JOB_IDS must be a boolean")
        self.allow_legacy_job_ids = bool(allow_legacy_job_ids)
        self.auth_token = (
            auth_token
            if auth_token is not None
            else environment.get("FIGMA_BRIDGE_TOKEN", "").strip()
            or client_config.auth_token
        )
        self.ws = None
        self._semantic_rendered: dict[str, dict[str, Any]] = {}
        self._semantic_componentization_attempted = False
        self.semantic_componentization_result: dict[str, Any] | None = None

        try:
            import websocket

            self._websocket = websocket
        except ImportError as exc:
            raise ImportError(
                "websocket-client 未安装，请执行 pip install websocket-client"
            ) from exc

    def connect(self) -> None:
        if self.ws is not None:
            return
        url = self.bridge_url.rstrip("/") + "/command"
        options: dict[str, Any] = {"timeout": self.timeout}
        headers: dict[str, str] = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        if self.client_token:
            headers["X-Figma-Client-Id"] = self.client_id
            headers["X-Figma-Client-Token"] = self.client_token
        if headers:
            options["header"] = headers
        if self._client_config.tls.enabled:
            sslopt: dict[str, Any] = {
                "cert_reqs": (
                    ssl.CERT_REQUIRED
                    if self._client_config.tls.verify
                    else ssl.CERT_NONE
                ),
                "check_hostname": self._client_config.tls.verify,
            }
            if self._client_config.tls.ca_file is not None:
                sslopt["ca_certs"] = str(self._client_config.tls.ca_file)
            if self._client_config.tls.certfile is not None:
                sslopt["certfile"] = str(self._client_config.tls.certfile)
            if self._client_config.tls.keyfile is not None:
                sslopt["keyfile"] = str(self._client_config.tls.keyfile)
            options["sslopt"] = sslopt
        self.ws = self._websocket.create_connection(url, **options)
        logger.info(f"已连接到 Figma 桥接服务器: {url}")

    def disconnect(self) -> None:
        if self.ws is not None:
            self.ws.close()
            self.ws = None
            logger.info("已断开 Figma 桥接服务器")

    def _discard_connection(self) -> None:
        ws = self.ws
        self.ws = None
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001 - the peer already closed
                pass

    def _send(
        self,
        action: str,
        params: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> Any:
        if self.ws is None:
            raise RuntimeError("未连接到 Figma 桥接服务器")
        request_id = request_id or uuid.uuid4().hex
        payload = {
            "action": action,
            "params": params,
            "clientId": self.client_id,
            "requestId": request_id,
        }
        self.ws.send(json.dumps(payload, ensure_ascii=False))
        try:
            response = self.ws.recv()
        except self._websocket.WebSocketConnectionClosedException as exc:
            self._discard_connection()
            raise FigmaBridgeError(
                "Figma 桥接连接在响应前关闭，写入结果未知",
                code="BRIDGE_DISCONNECTED",
                outcome="unknown",
                request_id=request_id,
            ) from exc
        if response is None or response == "" or response == b"":
            self._discard_connection()
            raise FigmaBridgeError(
                "Figma 桥接连接返回空响应，写入结果未知",
                code="BRIDGE_EMPTY_RESPONSE",
                outcome="unknown",
                request_id=request_id,
            )
        logger.info(f"收到桥接响应: {response!r}")
        try:
            data = json.loads(response)
        except (TypeError, ValueError) as exc:
            self._discard_connection()
            raise FigmaBridgeError(
                "Figma 桥接返回了无法解析的响应，写入结果未知",
                code="BRIDGE_RESPONSE_INVALID",
                outcome="unknown",
                request_id=request_id,
            ) from exc
        returned_id = str(data.get("requestId") or "")
        if returned_id and returned_id != request_id:
            raise RuntimeError(
                f"桥接响应 requestId 不匹配: {returned_id} != {request_id}"
            )
        if data.get("error"):
            retry_after_ms = data.get("retryAfterMs")
            raise FigmaBridgeError(
                f"Figma 插件返回错误: {data['error']}",
                code=str(data.get("code") or "UNKNOWN"),
                outcome=str(data.get("outcome") or "unknown"),
                request_id=request_id,
                retry_after_ms=(
                    int(retry_after_ms)
                    if isinstance(retry_after_ms, (int, float))
                    else None
                ),
            )
        return data.get("result")

    def create_frame(self, spec: dict[str, Any]) -> str | None:
        node_id = self._send("create_frame", spec)
        self._record_semantic_node(node_id, spec, node_type="FRAME")
        return node_id

    def _record_semantic_node(
        self,
        node_id: Any,
        spec: Mapping[str, Any],
        *,
        node_type: str,
    ) -> None:
        if not node_id:
            return
        group_id = str(spec.get("semanticGroupId") or "").strip()
        role = str(spec.get("semanticRole") or "").strip()
        signature = str(spec.get("semanticStructuralSignature") or "").strip()
        member_count = spec.get("semanticMemberCount")
        if not group_id or not role or not signature or not isinstance(member_count, int):
            return
        group = self._semantic_rendered.setdefault(
            group_id,
            {
                "groupId": group_id,
                "role": role,
                "structuralSignature": signature,
                "memberCount": member_count,
                "members": {},
            },
        )
        group["memberCount"] = max(int(group["memberCount"]), member_count)
        sources = [
            int(value)
            for value in spec.get("semanticSourceDomIndices") or []
            if isinstance(value, int) and not isinstance(value, bool)
        ]
        key = str(tuple(sources)) if sources else str(node_id)
        group["members"].setdefault(
            key,
            {
                "nodeId": str(node_id),
                "sourceDomIndices": sources,
                "nodeType": node_type,
            },
        )

    def _semantic_groups_for_componentization(self) -> list[dict[str, Any]]:
        groups = []
        for group in sorted(
            self._semantic_rendered.values(),
            key=lambda item: str(item.get("groupId") or ""),
        ):
            members = list(group["members"].values())
            if len(members) < 2 or len(members) != int(group["memberCount"]):
                continue
            if any(member["nodeType"] not in {"FRAME", "GROUP"} for member in members):
                continue
            groups.append(
                {
                    "groupId": group["groupId"],
                    "role": group["role"],
                    "structuralSignature": group["structuralSignature"],
                    "members": members,
                }
            )
        return groups

    def componentize_semantic_groups(
        self,
        groups: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if not Config().dom_semantic_component_instances:
            return {
                "status": "disabled",
                "masters": [],
                "instances": [],
                "rejected": [],
                "geometry_checks": [],
            }
        accepted = []
        rejected = []
        for group_index, group in enumerate(groups):
            if not isinstance(group, Mapping):
                rejected.append(
                    {
                        "groupId": f"group-{group_index}",
                        "code": "GROUP_INVALID",
                        "reason": "group must be an object",
                    }
                )
                continue
            group_id = str(group.get("groupId") or f"group-{group_index}")
            signature = str(group.get("structuralSignature") or "").strip()
            members = group.get("members")
            if not isinstance(members, list) or len(members) < 2:
                rejected.append(
                    {
                        "groupId": group_id,
                        "code": "INSUFFICIENT_MEMBERS",
                        "reason": "at least two members are required",
                    }
                )
                continue
            normalized_members = []
            invalid = None
            for member in members:
                if not isinstance(member, Mapping):
                    invalid = "MEMBER_INVALID"
                    break
                node_id = str(member.get("nodeId") or "").strip()
                if not node_id:
                    invalid = "NODE_ID_REQUIRED"
                    break
                member_signature = str(
                    member.get("structuralSignature") or signature
                ).strip()
                if not signature:
                    signature = member_signature
                if not signature or member_signature != signature:
                    invalid = "STRUCTURAL_SIGNATURE_MISMATCH"
                    break
                normalized_members.append(
                    {
                        **dict(member),
                        "nodeId": node_id,
                    }
                )
            if invalid is not None:
                rejected.append(
                    {
                        "groupId": group_id,
                        "code": invalid,
                        "reason": invalid.replace("_", " ").lower(),
                    }
                )
                continue
            accepted.append(
                {
                    **dict(group),
                    "groupId": group_id,
                    "structuralSignature": signature,
                    "members": normalized_members,
                }
            )

        if not accepted:
            return {
                "status": "rejected",
                "masters": [],
                "instances": [],
                "rejected": rejected,
                "geometry_checks": [],
            }
        result = self._send(
            "componentize_semantic_groups",
            {"groups": accepted},
        )
        bridge_rejected = list(result.get("rejected") or [])
        all_rejected = [*rejected, *bridge_rejected]
        result["rejected"] = all_rejected
        if all_rejected and result.get("status") == "committed":
            result["status"] = "partial"
        return result

    def apply_batch(
        self,
        actions: list[dict[str, Any]],
        *,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        transaction_id = (
            self._owned_job_id(transaction_id)
            if transaction_id is not None
            else build_job_namespace(self.client_id, uuid.uuid4().hex)
        )
        request_id = (
            transaction_id
            if len(transaction_id) <= 256
            else "owned-" + hashlib.sha256(transaction_id.encode("utf-8")).hexdigest()
        )
        return self._send(
            "apply_batch",
            {
                "transactionId": transaction_id,
                "actions": actions,
            },
            request_id=request_id,
        )

    def apply_edit_batch(
        self,
        actions: list[dict[str, Any]],
        *,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        transaction_id = transaction_id or uuid.uuid4().hex
        return self._send(
            "apply_edit_batch",
            {
                "transactionId": transaction_id,
                "actions": actions,
            },
            request_id=transaction_id,
        )

    def transaction_status(self, transaction_id: str) -> dict[str, Any]:
        """Read a persisted bridge transaction and any reconciliation readback."""
        return self._send(
            "bridge_transaction_status",
            {"transactionId": transaction_id},
        )

    def cleanup_owned_job(self, job_id: str) -> dict[str, Any]:
        """Remove only nodes carrying this bridge's owner and job markers."""
        return self._send(
            "cleanup_owned_job",
            {"jobId": self._owned_job_id(job_id)},
        )

    def ownership_report(self, job_id: str) -> dict[str, Any]:
        """Read persisted owner/job markers without mutating the document."""
        return self._send(
            "ownership_report",
            {"jobId": self._owned_job_id(job_id)},
        )

    def create_clip_frame(
        self, rect: tuple[int, int, int, int], parent_id: str | None = None
    ) -> str | None:
        """建一个 clipsContent 的 FRAME：它自身不画底，只把子元素切到
        该矩形内（DesignSpec 的 clip 就是滚动容器的 padding box）。
        """
        x, y, w, h = rect
        return self._send(
            "create_frame",
            {
                "name": "Clip",
                "x": x,
                "y": y,
                "width": w,
                "height": h,
                "clipsContent": True,
                "transparent": True,
                "parentId": parent_id,
            },
        )

    def _owned_job_id(self, job_id: str) -> str:
        normalized = str(job_id or "").strip()
        if normalized.startswith(JOB_NAMESPACE_PREFIX):
            return validate_job_namespace(
                normalized,
                client_id=self.client_id,
            ).canonical
        if self.allow_legacy_job_ids and not normalized.startswith("r5job:"):
            if not normalized:
                raise JobNamespaceError("legacy job id is required")
            return normalized
        return validate_job_namespace(normalized, client_id=self.client_id).canonical

    def set_autolayout(self, node_id: str, payload: dict[str, Any]) -> Any:
        """见 `PrototypeAdapter.set_autolayout`：子元素全部挂完之后才调用一次。"""
        return self._send("set_autolayout", {"nodeId": node_id, **payload})

    def create_rectangle(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        params = _with_parent(spec, parent_id)
        node_id = self._send("create_rectangle", params)
        self._record_semantic_node(node_id, params, node_type="RECTANGLE")
        return node_id

    def create_ellipse(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        params = _with_parent(spec, parent_id)
        node_id = self._send("create_ellipse", params)
        self._record_semantic_node(node_id, params, node_type="ELLIPSE")
        return node_id

    def create_text(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        params = _with_parent(spec, parent_id)
        node_id = self._send("create_text", params)
        self._record_semantic_node(node_id, params, node_type="TEXT")
        return node_id

    def resolve_font(
        self,
        family: str,
        style: str,
        weight: str | int,
    ) -> dict[str, Any]:
        """Ask the bridge for one explicit, auditable Figma font choice."""
        return self._send(
            "resolve_font",
            {
                "family": str(family or ""),
                "style": str(style or "Regular"),
                "weight": weight,
            },
        )

    def _text_render_spec(
        self,
        spec: dict[str, Any],
        local_spec: dict[str, Any],
        origin: tuple[int, int],
    ) -> dict[str, Any]:
        """Use the browser-measured line box for single-line Figma text.

        Figma applies pixel line-height around its own font metrics. For one
        measured browser line, ``textEmBox`` already starts at the real line
        top, so applying both shifts glyphs by different amounts per font size.
        """
        browser_measured = (
            spec.get("baselineSource") == "browser-measured"
            or bool(spec.get("measuredLines"))
        )
        lines = spec.get("lines")
        if (
            not browser_measured
            and not _single_line_text(spec)
            and int(spec.get("textEmLines") or 0) != 1
        ):
            return local_spec
        if (
            isinstance(lines, list)
            and len(lines) > 1
            and not _single_line_text(spec)
            and not browser_measured
        ):
            return local_spec
        measured = _offset_box(spec.get("textEmBox"), origin)
        if measured is None:
            return local_spec
        rich_runs = spec.get("richRuns")
        rich_origin = isinstance(rich_runs, list) and len(rich_runs) > 1
        rendered = {
            **local_spec,
            "x": local_spec.get("x", 0) if rich_origin else measured[0],
            "y": measured[1],
        }
        if browser_measured:
            rendered["baselineSource"] = "browser-measured"
            if isinstance(spec.get("lineBoxes"), list):
                rendered["lineBoxes"] = [
                    list(box)
                    for box in spec["lineBoxes"]
                    if isinstance(box, (list, tuple)) and len(box) == 4
                ]
        if _single_line_text(spec):
            rendered.pop("lineHeight", None)
        return rendered

    def create_image(
        self, spec: dict[str, Any], parent_id: str | None = None
    ) -> str | None:
        params = _with_parent(spec, parent_id)
        node_id = self._send("create_image", params)
        self._record_semantic_node(node_id, params, node_type="RECTANGLE")
        return node_id

    def set_text(self, node_id: str, text: str) -> dict[str, Any]:
        """Replace native text characters on one explicit node."""
        return self._send("set_text", {"nodeId": node_id, "text": text})

    def set_name(self, node_id: str, name: str) -> dict[str, Any]:
        """Rename one explicit node without changing its identity."""
        return self._send("set_name", {"nodeId": node_id, "name": name})

    def set_visibility(self, node_id: str, visible: bool) -> dict[str, Any]:
        """Set one explicit node's visibility."""
        return self._send(
            "set_visibility",
            {"nodeId": node_id, "visible": visible},
        )

    def set_layout_flow(
        self,
        node_id: str,
        layout: dict[str, Any],
        *,
        children: list[dict[str, Any]] | None = None,
        width: float | None = None,
        height: float | None = None,
        depth: int = 2,
    ) -> dict[str, Any]:
        """Apply horizontal, vertical, wrap, or Grid flow to one frame."""
        params: dict[str, Any] = {
            "nodeId": node_id,
            "layout": layout,
            "children": children or [],
            "depth": depth,
        }
        if width is not None:
            params["width"] = width
        if height is not None:
            params["height"] = height
        return self._send("set_layout_flow", params)

    def set_grid_child_overrides(
        self,
        node_id: str,
        children: list[dict[str, Any]],
        *,
        depth: int = 2,
    ) -> dict[str, Any]:
        """Update Grid child placement without rewriting frame dimensions."""
        return self._send(
            "set_grid_child_overrides",
            {
                "nodeId": node_id,
                "children": children,
                "depth": depth,
            },
        )

    def replace_image_fill(
        self,
        node_id: str,
        image_base64: str,
        *,
        fill_index: int = 0,
    ) -> dict[str, Any]:
        """Replace one image paint while preserving the node and fill mode."""
        return self._send(
            "replace_image_fill",
            {
                "nodeId": node_id,
                "imageBase64": image_base64,
                "fillIndex": fill_index,
            },
        )

    def image_fill_report(self, node_id: str) -> dict[str, Any]:
        """Return image-fill payload bytes under one explicit root node."""
        return self._send("image_fill_report", {"nodeId": node_id})

    def capture_visual_quality(
        self,
        node_id: str,
        *,
        reference_png: str | Path,
        rendered_png: str | Path,
        design: dict[str, Any],
        output_dir: str | Path,
    ) -> dict[str, Any]:
        """Measure one real Figma export against its source screenshot."""
        from src.app.services.evidence.dom_visual_quality import (
            evaluate_dom_visual_quality,
        )

        readback = self._send(
            "get_node_tree",
            {"nodeId": node_id, "depth": 20},
        )
        image_report = self.image_fill_report(node_id)
        result = evaluate_dom_visual_quality(
            Path(reference_png),
            Path(rendered_png),
            design,
            {**readback, "imageFillReport": image_report},
        )
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "visual-quality.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return result

    def flush(self) -> None:
        if (
            Config().dom_semantic_component_instances
            and not self._semantic_componentization_attempted
        ):
            self._semantic_componentization_attempted = True
            groups = self._semantic_groups_for_componentization()
            if groups:
                try:
                    self.semantic_componentization_result = (
                        self.componentize_semantic_groups(groups)
                    )
                except Exception as exc:  # noqa: BLE001 - original render stays authoritative
                    logger.warning("semantic componentization failed safely: %s", exc)
        self.disconnect()


def _with_parent(
    spec: dict[str, Any],
    parent_id: str | None,
) -> dict[str, Any]:
    params = dict(spec)
    if parent_id is not None:
        params["parentId"] = parent_id
    return params


def persist_semantic_componentization_result(
    output: str | Path,
    result: Mapping[str, Any],
) -> Path:
    destination = Path(output)
    path = (
        destination
        if destination.suffix.lower() == ".json"
        else destination / SEMANTIC_FIGMA_COMPONENTS_FILENAME
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
