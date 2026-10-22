"""P1 evidence adapter contracts and shadow-mode helpers."""
from __future__ import annotations

from src.app.services.evidence.sample_scope import (
    DEFAULT_SAMPLE_SCOPE,
    SampleScenario,
    SampleScope,
    validate_sample_scope,
)
from src.app.services.evidence.retention import EvidenceStorePolicy
from src.app.services.evidence.asset_download import (
    AssetDownloadError,
    AssetDownloadPolicy,
    download_asset,
    inspect_asset_payload,
    validate_remote_asset_url,
)
from src.app.services.evidence.asset_materialize import (
    AssetMaterializeError,
    MaterializedAssetSidecar,
    materialize_downloaded_assets,
)
from src.app.services.evidence.ocr_probe import (
    calibrate_glyph_boxes,
    compare_glyph_boxes,
    compare_glyph_boxes_trusted,
    compare_ocr_text,
    compare_glyph_text,
    normalize_ocr_text,
    parse_tesseract_boxes,
    summarize_ocr_observations,
)
from src.app.services.evidence.sample_registry import (
    SampleRegistry,
    SampleSpec,
    evaluate_sample_markers,
    load_sample_registry,
    marker_counts,
    locate_sample,
    validate_sample_registry,
)
from src.app.services.evidence.adapter import (
    EvidenceAdapterError,
    EvidenceSidecar,
    adapt_capture,
    resolve_capture_fields,
    write_evidence_sidecar,
)

__all__ = [
    "DEFAULT_SAMPLE_SCOPE",
    "AssetDownloadError",
    "AssetDownloadPolicy",
    "AssetMaterializeError",
    "EvidenceAdapterError",
    "EvidenceStorePolicy",
    "EvidenceSidecar",
    "MaterializedAssetSidecar",
    "SampleRegistry",
    "SampleScenario",
    "SampleScope",
    "SampleSpec",
    "adapt_capture",
    "resolve_capture_fields",
    "compare_ocr_text",
    "compare_glyph_text",
    "compare_glyph_boxes",
    "compare_glyph_boxes_trusted",
    "calibrate_glyph_boxes",
    "download_asset",
    "evaluate_sample_markers",
    "load_sample_registry",
    "marker_counts",
    "materialize_downloaded_assets",
    "normalize_ocr_text",
    "parse_tesseract_boxes",
    "inspect_asset_payload",
    "summarize_ocr_observations",
    "validate_remote_asset_url",
    "locate_sample",
    "validate_sample_scope",
    "validate_sample_registry",
    "write_evidence_sidecar",
]
