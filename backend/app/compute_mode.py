"""Deployment compute boundary. Legacy mode is explicit, never a fallback."""
import os


def browser_compute_enabled() -> bool:
    mode = os.environ.get("ATLAS_COMPUTE_MODE", "browser")
    if mode not in {"browser", "legacy"}:
        raise ValueError("ATLAS_COMPUTE_MODE 必须是 browser 或显式 legacy")
    return mode == "browser"


def cloud_generation_enabled() -> bool:
    return not browser_compute_enabled() and os.environ.get("ATLAS_CLOUD_PROOF_GENERATION", "false").lower() == "true"
