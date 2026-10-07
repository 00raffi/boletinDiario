import hashlib
import re

from fastapi.testclient import TestClient

from radar.app import STATIC, create_app


def test_both_local_hosts_serve_identical_versioned_frontend_with_cache_policy(tmp_path):
    app = create_app(tmp_path, start_engine=False)
    pages = []
    for host in ("localhost", "127.0.0.1"):
        with TestClient(app, base_url=f"http://{host}") as client:
            response = client.get("/")
            assert response.status_code == 200
            assert response.headers["Cache-Control"] == "no-store"
            pages.append(response.text)
            for name in ("app.js", "style.css"):
                version = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:12]
                path = f"/static/{name}?v={version}"
                assert path in response.text
                asset = client.get(path)
                assert asset.status_code == 200
                assert asset.headers["Cache-Control"] == "no-cache"
                assert asset.content == (STATIC / name).read_bytes()
                conditional = client.get(path, headers={"If-None-Match": asset.headers["ETag"]})
                assert conditional.status_code == 304
                assert conditional.headers["Cache-Control"] == "no-cache"
    assert pages[0] == pages[1]


def test_asset_version_changes_with_contents_without_application_restart(tmp_path, monkeypatch):
    static = tmp_path / "static"
    static.mkdir()
    for name in ("index.html", "app.js", "style.css"):
        (static / name).write_bytes((STATIC / name).read_bytes())
    monkeypatch.setattr("radar.app.STATIC", static)
    app = create_app(tmp_path / "database", start_engine=False)
    with TestClient(app, base_url="http://localhost") as client:
        before = client.get("/").text
        script = static / "app.js"
        script.write_text(script.read_text() + "\n// Changed version\n")
        after = client.get("/").text
        before_js = re.search(r'/static/app\.js\?v=[a-f0-9]+', before).group()
        after_js = re.search(r'/static/app\.js\?v=[a-f0-9]+', after).group()
        before_css = re.search(r'/static/style\.css\?v=[a-f0-9]+', before).group()
        after_css = re.search(r'/static/style\.css\?v=[a-f0-9]+', after).group()
        assert before_js != after_js
        assert before_css == after_css
        assert client.get(after_js).content == script.read_bytes()
