"""Probe whether a stable cross-engine difference follows engine or UA condition."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.structure.capture_state import classify_capture_navigation


TARGETS = {
    "passkey": "Sign in with a passkey",
    "apple": "Continue with Apple",
    "google": "Continue with Google",
    "divider": "or",
}

ENVIRONMENT_JS = r"""
() => {
  const uaData = navigator.userAgentData;
  return {
    userAgent: String(navigator.userAgent || ''),
    platform: String(navigator.platform || ''),
    languages: Array.from(navigator.languages || []),
    language: String(navigator.language || ''),
    timezone: String(Intl.DateTimeFormat().resolvedOptions().timeZone || ''),
    hardwareConcurrency: Number(navigator.hardwareConcurrency || 0),
    deviceMemory: Number(navigator.deviceMemory || 0),
    cookieEnabled: Boolean(navigator.cookieEnabled),
    userAgentData: uaData ? {
      brands: Array.from(uaData.brands || []).map((item) => ({
        brand: String(item.brand || ''),
        version: String(item.version || ''),
      })),
      mobile: Boolean(uaData.mobile),
      platform: String(uaData.platform || ''),
    } : null,
    features: {
      publicKeyCredential: typeof PublicKeyCredential !== 'undefined',
      conditionalMediation: Boolean(
        typeof PublicKeyCredential !== 'undefined'
        && typeof PublicKeyCredential.isConditionalMediationAvailable === 'function'
      ),
      passwordCredential: typeof PasswordCredential !== 'undefined',
      cssHas: Boolean(
        typeof CSS !== 'undefined'
        && typeof CSS.supports === 'function'
        && CSS.supports('selector(:has(*))')
      ),
      webShare: typeof navigator.share === 'function',
      clipboard: Boolean(navigator.clipboard),
    },
  };
}
"""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded S07 engine/UA condition probe without login."
    )
    parser.add_argument("--url", default="https://github.com/login")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--timeout-ms", type=int, default=15000)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--worker-engine",
        choices=("chromium", "webkit"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--condition", help=argparse.SUPPRESS)
    parser.add_argument("--ua-mode", default="native", help=argparse.SUPPRESS)
    parser.add_argument(
        "--feature-mode",
        default="none",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--repeat", type=int, default=1, help=argparse.SUPPRESS)
    parser.add_argument(
        "--out",
        type=Path,
        default=(
            _ROOT
            / "output"
            / "_p1_engine_conditions"
            / "s07_condition_probe.json"
        ),
    )
    args = parser.parse_args(argv)
    repeats = max(1, int(args.repeats))
    if args.worker:
        if not args.worker_engine or not args.result or not args.condition:
            raise SystemExit("worker mode requires engine, result and condition")
        _worker_main(args)
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".p1-condition-probe-",
        dir=args.out.parent,
    ) as tmp:
        temp = Path(tmp)
        native_tasks = [
            {
                "engine": engine,
                "user_agent": None,
                "ua_mode": "native",
                "feature_mode": "none",
                "condition": f"{engine}-native",
                "repeat": repeat,
            }
            for engine in ("chromium", "webkit")
            for repeat in range(1, repeats + 1)
        ]
        native = _run_worker_batch(native_tasks, args, temp)
        native_by_engine = {
            engine: [item for item in native if item.get("engine") == engine]
            for engine in ("chromium", "webkit")
        }
        ua_templates = {
            engine: next(
                (
                    str(item.get("environment", {}).get("userAgent") or "")
                    for item in native_by_engine[engine]
                    if item.get("valid")
                ),
                "",
            )
            for engine in ("chromium", "webkit")
        }
        cross_tasks = [
            {
                "engine": engine,
                "user_agent": ua_templates[ua_source] or None,
                "ua_mode": ua_mode,
                "feature_mode": "none",
                "condition": f"{engine}-with-{ua_mode}",
                "repeat": repeat,
            }
            for engine, ua_source, ua_mode in (
                ("chromium", "webkit", "webkit-ua"),
                ("webkit", "chromium", "chromium-ua"),
            )
            for repeat in range(1, repeats + 1)
        ]
        cross = _run_worker_batch(cross_tasks, args, temp)
        feature_tasks = [
            {
                "engine": engine,
                "user_agent": None,
                "ua_mode": "native",
                "feature_mode": feature_mode,
                "condition": condition,
                "repeat": repeat,
            }
            for engine, feature_mode, condition in (
                (
                    "chromium",
                    "password-credential-off",
                    "chromium-password-credential-off",
                ),
                (
                    "webkit",
                    "password-credential-on",
                    "webkit-password-credential-on",
                ),
                (
                    "chromium",
                    "conditional-mediation-off",
                    "chromium-conditional-mediation-off",
                ),
            )
            for repeat in range(1, repeats + 1)
        ]
        features = _run_worker_batch(feature_tasks, args, temp)
        observations = native + cross + features

    summary = summarize_condition_probe(observations)
    result = {
        "schema_version": "p1-engine-condition-probe/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "url": args.url,
        "repeats": repeats,
        "ua_templates": ua_templates,
        "observations": observations,
        "summary": summary,
        "note": (
            "Candidate-only. Multiple sessions and UA swaps can support attribution "
            "candidates but do not independently prove a server-side cause."
        ),
    }
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "confirmed_root_cause": summary["confirmed_root_cause"],
        "attribution_candidates": summary["attribution_candidates"],
        "output": str(args.out),
    }, ensure_ascii=False))
    return 0


def _run_worker_batch(
    tasks: Sequence[dict[str, Any]],
    args: argparse.Namespace,
    temp: Path,
) -> list[dict[str, Any]]:
    def run(index: int, task: dict[str, Any]) -> dict[str, Any]:
        result_path = temp / f"observation-{index:03d}.json"
        env = os.environ.copy()
        if task.get("user_agent"):
            env["P1_PROBE_UA"] = str(task["user_agent"])
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--worker-engine",
            str(task["engine"]),
            "--url",
            args.url,
            "--timeout-ms",
            str(args.timeout_ms),
            "--result",
            str(result_path),
            "--condition",
            str(task["condition"]),
            "--ua-mode",
            str(task["ua_mode"]),
            "--feature-mode",
            str(task.get("feature_mode") or "none"),
            "--repeat",
            str(task["repeat"]),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(_ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=max(5, int(args.timeout_ms) / 1000 + 20),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return _failure_observation(task, "worker-timeout")
        if completed.returncode != 0 or not result_path.is_file():
            detail = (completed.stderr or completed.stdout or "").strip()[-800:]
            return _failure_observation(task, detail or "worker-failed")
        try:
            value = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return _failure_observation(task, f"{type(exc).__name__}: {exc}")
        return value if isinstance(value, dict) else _failure_observation(
            task,
            "invalid-worker-result",
        )

    with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as pool:
        futures = [
            pool.submit(run, index, task)
            for index, task in enumerate(tasks)
        ]
        return [future.result() for future in futures]


def _worker_main(args: argparse.Namespace) -> None:
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as playwright:
            observation = _probe_session(
                playwright,
                str(args.worker_engine),
                args.url,
                user_agent=os.environ.get("P1_PROBE_UA") or None,
                ua_mode=args.ua_mode,
                feature_mode=args.feature_mode,
                condition=args.condition,
                repeat=args.repeat,
                timeout_ms=args.timeout_ms,
            )
    except Exception as exc:  # noqa: BLE001 - worker failure stays evidence
        observation = _failure_observation(
            {
                "engine": args.worker_engine,
                "ua_mode": args.ua_mode,
                "feature_mode": args.feature_mode,
                "condition": args.condition,
                "repeat": args.repeat,
            },
            f"{type(exc).__name__}: {exc}",
        )
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(
        json.dumps(observation, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _failure_observation(task: dict[str, Any], error: str) -> dict[str, Any]:
    return {
        "condition": task.get("condition"),
        "engine": task.get("engine"),
        "ua_mode": task.get("ua_mode"),
        "feature_mode": task.get("feature_mode"),
        "repeat": task.get("repeat"),
        "valid": False,
        "navigation": {
            "status": "capture-failed",
            "error": error,
        },
        "http_status": None,
        "title": "",
        "body_sha256": None,
        "targets": {},
        "environment": {},
        "error": error,
    }


def _feature_shim_script(feature_mode: str) -> str:
    if feature_mode == "password-credential-off":
        return r"""
        try {
          Object.defineProperty(window, 'PasswordCredential', {
            value: undefined,
            writable: true,
            configurable: true
          });
        } catch (error) {}
        """
    if feature_mode == "password-credential-on":
        return r"""
        try {
          function PasswordCredential() {}
          Object.defineProperty(window, 'PasswordCredential', {
            value: PasswordCredential,
            writable: true,
            configurable: true
          });
        } catch (error) {}
        """
    if feature_mode == "conditional-mediation-off":
        return r"""
        try {
          if (window.PublicKeyCredential) {
            Object.defineProperty(
              window.PublicKeyCredential,
              'isConditionalMediationAvailable',
              {
                value: function () { return Promise.resolve(false); },
                writable: true,
                configurable: true
              }
            );
          }
        } catch (error) {}
        """
    return ""


def summarize_condition_probe(
    observations: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    raw_records = [item for item in observations if isinstance(item, dict)]
    target_names = sorted({
        key
        for item in raw_records
        for key in (item.get("targets") or {})
    } | set(TARGETS))
    conditions: dict[str, list[dict[str, Any]]] = {}
    for item in raw_records:
        conditions.setdefault(str(item.get("condition") or ""), []).append(item)

    target_results: dict[str, dict[str, Any]] = {}
    candidate_union: list[str] = []
    for target in target_names:
        condition_values: dict[str, dict[str, Any]] = {}
        for condition, items in sorted(conditions.items()):
            values = [
                bool((item.get("targets") or {}).get(target))
                for item in items
                if item.get("valid") is not False
            ]
            stable = bool(values) and len(set(values)) == 1
            condition_values[condition] = {
                "count": len(values),
                "present": values[0] if stable else None,
                "stable": stable,
            }

        session_variation = any(
            not item["stable"] for item in condition_values.values()
        )
        metadata = {
            condition: {
                "engine": str(items[0].get("engine") or ""),
                "ua_mode": str(items[0].get("ua_mode") or "native"),
                "feature_mode": str(items[0].get("feature_mode") or "none"),
            }
            for condition, items in conditions.items()
            if items
        }
        engine_candidate = _dimension_changed(
            condition_values,
            metadata,
            group_keys=("engine",),
            fixed={"ua_mode": "native", "feature_mode": "none"},
            across_groups=True,
        )
        ua_changed = _dimension_changed(
            condition_values,
            metadata,
            group_keys=("engine", "feature_mode"),
            varying="ua_mode",
        )
        feature_changed = _dimension_changed(
            condition_values,
            metadata,
            group_keys=("engine", "ua_mode"),
            varying="feature_mode",
        )
        candidates: list[str] = []
        if session_variation:
            candidates.append("session-variation")
        if engine_candidate:
            candidates.append("engine-conditioned-candidate")
        if ua_changed:
            candidates.append("ua-conditioned-candidate")
        if feature_changed:
            candidates.append("feature-conditioned-candidate")
        if not candidates:
            candidates.append("unresolved")
        for candidate in candidates:
            if candidate not in candidate_union:
                candidate_union.append(candidate)
        target_results[target] = {
            "conditions": condition_values,
            "session_variation": session_variation,
            "engine_correlated_candidate": engine_candidate,
            "ua_dependency_candidate": ua_changed,
            "feature_dependency_candidate": feature_changed,
            "candidates": candidates,
        }

    return {
        "targets": target_results,
        "attribution_candidates": candidate_union,
        "confirmed_root_cause": False,
        "note": (
            "Candidate-only; engine, UA, feature shim, platform and session effects "
            "are not separated causally."
        ),
    }


def _dimension_changed(
    values: dict[str, dict[str, Any]],
    metadata: dict[str, dict[str, str]],
    *,
    group_keys: tuple[str, ...],
    varying: str | None = None,
    fixed: dict[str, str] | None = None,
    across_groups: bool = False,
) -> bool:
    grouped: dict[tuple[str, ...], dict[str, bool]] = {}
    for condition, value in values.items():
        if not value.get("stable") or value.get("present") is None:
            continue
        meta = metadata.get(condition) or {}
        if fixed and any(meta.get(key) != expected for key, expected in fixed.items()):
            continue
        group = tuple(str(meta.get(key) or "") for key in group_keys)
        varying_value = str(meta.get(varying) or "") if varying else "value"
        grouped.setdefault(group, {})[varying_value] = bool(value["present"])
    if varying is not None:
        return any(
            len(items) > 1 and len(set(items.values())) > 1
            for items in grouped.values()
        )
    if across_groups:
        return len({
            present
            for items in grouped.values()
            for present in items.values()
        }) > 1
    return any(len(set(items.values())) > 1 for items in grouped.values())


def _probe_session(
    playwright: Any,
    engine: str,
    url: str,
    *,
    user_agent: str | None,
    ua_mode: str,
    feature_mode: str,
    condition: str,
    repeat: int,
    timeout_ms: int,
) -> dict[str, Any]:
    browser = getattr(playwright, engine).launch(headless=True)
    error = None
    response_status = None
    final_url = "about:blank"
    title = ""
    body_text = ""
    environment: dict[str, Any] = {}
    try:
        context_options: dict[str, Any] = {
            "viewport": {"width": 1440, "height": 900},
            "locale": "zh-CN",
        }
        if user_agent:
            context_options["user_agent"] = user_agent
        context = browser.new_context(**context_options)
        try:
            shim_script = _feature_shim_script(feature_mode)
            if shim_script:
                context.add_init_script(shim_script)
            page = context.new_page()
            try:
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=max(1000, int(timeout_ms)),
                )
                if response is not None:
                    response_status = response.status
            except Exception as exc:  # noqa: BLE001 - record navigation failure
                error = f"{type(exc).__name__}: {exc}"
            page.wait_for_timeout(800)
            final_url = page.url
            title = page.title()
            body_text = _evaluate_with_navigation_retry(
                page,
                "() => String((document.body && document.body.innerText) || '')"
            )
            environment = _evaluate_with_navigation_retry(page, ENVIRONMENT_JS)
        finally:
            context.close()
    finally:
        browser.close()
    navigation = classify_capture_navigation(
        url,
        final_url,
        error=error,
        navigation_budget_exhausted=True,
    )
    return {
        "condition": condition,
        "engine": engine,
        "ua_mode": ua_mode,
        "feature_mode": feature_mode,
        "repeat": repeat,
        "navigation": navigation,
        "http_status": response_status,
        "title": title,
        "body_sha256": hashlib.sha256(body_text.encode("utf-8")).hexdigest(),
        "targets": _target_presence(body_text),
        "environment": environment,
        "valid": bool(environment) and navigation["status"] in {"ok", "redirected"},
    }


def _target_presence(body_text: str) -> dict[str, bool]:
    lines = {line.strip() for line in str(body_text or "").splitlines() if line.strip()}
    return {
        key: (
            needle in lines
            if key == "divider"
            else needle in str(body_text or "")
        )
        for key, needle in TARGETS.items()
    }


def _evaluate_with_navigation_retry(
    page: Any,
    script: str,
    *,
    attempts: int = 3,
    wait_ms: int = 150,
) -> Any:
    total = max(1, int(attempts))
    for attempt in range(1, total + 1):
        try:
            return page.evaluate(script)
        except Exception as exc:  # noqa: BLE001 - navigation can replace the context
            message = str(exc).lower()
            transient = (
                "execution context was destroyed" in message
                or "most likely because of a navigation" in message
            )
            if not transient or attempt >= total:
                raise
            try:
                page.wait_for_timeout(max(1, int(wait_ms)))
            except Exception:
                pass
    raise RuntimeError("probe retry loop exhausted")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
