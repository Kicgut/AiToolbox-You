import re

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
HTML_HEADERS = {"Accept": "text/html"}


def test_workbench_root_and_history_routes_serve_same_spa_shell():
    root = client.get("/", headers=HTML_HEADERS)
    sessions = client.get("/sessions", headers=HTML_HEADERS)

    assert root.status_code == 200
    assert sessions.status_code == 200
    assert root.text == sessions.text
    assert "AI 编程工作台" in root.text


def test_workbench_spa_references_built_assets_that_are_served():
    root = client.get("/", headers=HTML_HEADERS)
    asset_paths = re.findall(r'(?:src|href)="(/static/workbench/assets/[^"]+)"', root.text)

    assert len(asset_paths) == 2
    assert all(client.get(path).status_code == 200 for path in asset_paths)


def test_head_history_route_matches_get_headers_without_a_body():
    get_response = client.get("/sessions", headers=HTML_HEADERS)
    head_response = client.head("/sessions", headers=HTML_HEADERS)

    assert head_response.status_code == get_response.status_code
    assert head_response.headers["content-type"] == get_response.headers["content-type"]
    assert head_response.headers["content-length"] == get_response.headers["content-length"]
    assert head_response.content == b""


def test_legacy_workbench_route_redirects_to_sessions():
    response = client.get("/workbench", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/sessions"


def test_proxy_traffic_page_is_served_by_the_workbench_spa_shell():
    root = client.get("/", headers=HTML_HEADERS)
    response = client.get("/traffic", headers=HTML_HEADERS)

    assert response.status_code == 200
    assert response.text == root.text
    assert "/static/workbench/assets/" in response.text


def test_reserved_segments_never_enter_spa_fallback():
    for path in (
        "/api/unknown",
        "/static/unknown.js",
        "/ws/unknown",
        "/features/proxy-traffic-monitor/static/unknown.js",
    ):
        response = client.get(path, headers=HTML_HEADERS)
        assert response.status_code == 404, path
        assert response.headers["content-type"].startswith("application/json"), path


def test_traffic_history_subpaths_are_left_to_the_spa_router():
    response = client.get("/traffic/unknown", headers=HTML_HEADERS)

    assert response.status_code == 200
    assert "/static/workbench/assets/" in response.text


def test_reserved_segment_matching_is_exact():
    apiary = client.get("/apiary", headers=HTML_HEADERS)
    traffic_report = client.get("/traffic-report", headers=HTML_HEADERS)

    assert apiary.status_code == 200
    assert traffic_report.status_code == 200
    assert apiary.text == traffic_report.text


def test_unknown_file_paths_remain_real_404s():
    for path in ("/favicon.ico", "/assets/x.js", "/sessions/export.csv"):
        response = client.get(path, headers=HTML_HEADERS)
        assert response.status_code == 404, path
        assert response.headers["content-type"].startswith("application/json"), path


def test_unknown_extensionless_path_requires_html_accept():
    response = client.get("/unknown-route", headers={"Accept": "application/json"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_html_accept_parsing_is_exact_and_case_insensitive():
    accepted = client.get(
        "/history-route",
        headers={"Accept": "application/json, Text/HTML; charset=utf-8"},
    )
    rejected = client.get(
        "/other-history-route",
        headers={"Accept": "application/text/html-ish"},
    )

    assert accepted.status_code == 200
    assert rejected.status_code == 404
