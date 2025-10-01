"""Plugin management commands."""

from __future__ import annotations

from typing import Optional

from ..config.plugin_policy import (
    PluginPolicy,
    load_allowlist_document,
    write_allowlist_document,
)


def trust_plugin(module: str, *, entry_point: Optional[str], label: Optional[str]) -> int:
    """Compute digest for a module and add it to the plugin allowlist."""
    policy = PluginPolicy.from_env()

    metadata = policy.resolve_metadata(module)
    if metadata.origin is None:
        print(f"❌ Could not locate module '{module}'. Ensure it is installed and importable.")
        return 1

    if metadata.sha256 is None:
        print(
            f"❌ Unable to compute digest for '{module}' (origin: {metadata.origin})."
            " Package may be namespace-only or non-file based."
        )
        return 1

    allowlist_doc = load_allowlist_document(policy.allowlist_path)
    modules = allowlist_doc.setdefault("modules", {})
    entry_points = allowlist_doc.setdefault("entry_points", {})

    record = {"sha256": metadata.sha256}
    if label:
        record["label"] = label
    modules[module] = record

    if entry_point:
        ep_record = {"module": module, "sha256": metadata.sha256}
        if label:
            ep_record["label"] = label
        entry_points[entry_point] = ep_record

    try:
        write_allowlist_document(policy.allowlist_path, allowlist_doc)
    except Exception as exc:  # pragma: no cover - OS errors rare
        print(f"❌ Failed to update allowlist {policy.allowlist_path}: {exc}")
        return 1

    print("✅ Plugin allowlist updated")
    print(f"   Module: {module}")
    print(f"   Digest: {metadata.sha256}")
    if entry_point:
        print(f"   Entry point: {entry_point}")
    if label:
        print(f"   Label: {label}")
    print()
    if not policy.enabled:
        print(
            "ℹ️  Plugins remain disabled. Set SAM_ENABLE_PLUGINS=true and restart to load trusted plugins."
        )
    elif policy.allow_unverified:
        print(
            "⚠️  SAM_PLUGIN_ALLOW_UNVERIFIED is enabled; consider disabling for strict enforcement."
        )

    return 0


def run_plugins_command(args) -> int:  # type: ignore[no-untyped-def]
    action = getattr(args, "plugins_action", None)
    if action == "trust":
        return trust_plugin(
            args.module,
            entry_point=getattr(args, "entry_point", None),
            label=getattr(args, "label", None),
        )

    print("Usage: sam plugins trust <module> [--entry-point name] [--label text]")
    return 1
