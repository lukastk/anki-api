"""Media [parity]."""

import base64


def test_upload_download_delete(api):
    payload = base64.b64encode(b"hello world").decode()
    up = api.post("/media/files", json={"filename": "greeting.txt", "data_base64": payload}).json()
    assert up["filename"] == "greeting.txt"

    resp = api.get("/media/files/greeting.txt")
    assert resp.status_code == 200
    assert resp.content == b"hello world"

    assert api.delete("/media/files/greeting.txt").status_code == 200
    assert api.get("/media/files/greeting.txt").status_code == 404


def test_download_missing_is_404(api):
    assert api.get("/media/files/nope.png").status_code == 404


def test_upload_invalid_base64_is_422(api):
    assert api.post("/media/files", json={"filename": "x.bin", "data_base64": "!!!notb64"}).status_code == 422


def test_path_traversal_blocked(api):
    # however the traversal is encoded, it must never resolve to a file (route
    # miss -> 404, or guard -> 400); it must not 200.
    assert api.get("/media/files/..%2F..%2Fsecret").status_code in (400, 404)


def test_media_check(api):
    out = api.get("/media/check").json()
    assert {"unused", "missing", "report", "have_trash"} <= set(out)
    assert isinstance(out["unused"], list)
