from __future__ import annotations

from src.app.services.evidence.dom_route_quality import (
    evaluate_dom_route_quality,
)


def test_requested_xiaomi_but_final_support_url_is_fail():
    result = evaluate_dom_route_quality(
        bundle={
            "requested_url": "https://www.mi.com/",
            "final_url": "https://www.mi.com/global/support/",
        },
        dom_nodes=[{"tag": "body", "x": 0, "y": 0, "w": 1440, "h": 1321}],
        graph={"containers": [], "elements": []},
        design={"canvas": {"width": 1440, "height": 1321}, "elements": []},
        asset_ledger={"reference_count": 0},
    )
    assert result["status"] == "fail"
    assert result["checks"]["redirect"]["status"] == "fail"


def test_dom_image_refs_without_design_images_is_fail():
    result = evaluate_dom_route_quality(
        bundle={
            "requested_url": "https://data.stats.gov.cn/",
            "final_url": "https://data.stats.gov.cn/",
        },
        dom_nodes=[
            {
                "tag": "img",
                "assetSrc": "https://img/hero.png",
                "x": 0,
                "y": 0,
                "w": 800,
                "h": 485,
            }
        ],
        graph={"containers": [], "elements": []},
        design={"canvas": {"width": 1440, "height": 800}, "elements": []},
        asset_ledger={"reference_count": 1, "verified_count": 0},
    )
    assert result["checks"]["image_coverage"]["status"] == "fail"


def test_same_origin_spa_navigation_does_not_fail_without_content_mismatch():
    result = evaluate_dom_route_quality(
        bundle={
            "requested_url": "https://data.stats.gov.cn/",
            "final_url": (
                "https://data.stats.gov.cn/dg/website/page.html"
                "#/pc/national/home"
            ),
        },
        dom_nodes=[
            {"tag": "body", "x": 0, "y": 0, "w": 1440, "h": 900}
        ],
        graph={"containers": [], "elements": []},
        design={"canvas": {"width": 1440, "height": 900}, "elements": []},
        asset_ledger={"reference_count": 0},
    )
    assert result["checks"]["redirect"]["status"] == "warn"
    assert result["status"] != "fail"


def test_valid_same_path_query_normalization_passes():
    result = evaluate_dom_route_quality(
        bundle={
            "requested_url": "https://example.test/article?utm_source=test",
            "final_url": "https://example.test/article#section",
        },
        dom_nodes=[
            {"tag": "article", "x": 0, "y": 0, "w": 900, "h": 500}
        ],
        graph={"containers": [], "elements": []},
        design={"canvas": {"width": 900, "height": 500}, "elements": []},
        asset_ledger={"reference_count": 0},
    )
    assert result["checks"]["redirect"]["status"] == "pass"
    assert result["status"] == "pass"


def test_clipped_descendants_missing_from_graph_warn():
    result = evaluate_dom_route_quality(
        bundle={
            "requested_url": "https://example.test/",
            "final_url": "https://example.test/",
        },
        dom_nodes=[
            {
                "tag": "div",
                "x": 0,
                "y": 0,
                "w": 200,
                "h": 100,
                "clipToBounds": True,
            },
            {
                "tag": "div",
                "pIdx": 0,
                "x": 0,
                "y": 120,
                "w": 200,
                "h": 80,
            },
        ],
        graph={"containers": [], "elements": []},
        design={"canvas": {"width": 200, "height": 100}, "elements": []},
        asset_ledger={"reference_count": 0},
    )
    assert result["checks"]["clipping"]["status"] == "warn"
