"""Media [parity]."""

import base64
import os


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


def test_media_check_reports_unused_and_missing_files(api):
    api.post("/media/files", json={"filename": "orphan.png", "data_base64": base64.b64encode(b"x").decode()})
    api.make_note(deck="D", front='<img src="ghost.png">')
    out = api.get("/media/check").json()
    assert out["unused"] == ["orphan.png"]
    assert out["missing"] == ["ghost.png"]


def test_exists_reports_a_present_file_without_its_bytes(api):
    api.post("/media/files", json={"filename": "clip.mp3", "data_base64": base64.b64encode(b"SECRET-BYTES").decode()})
    resp = api.get("/media/files/clip.mp3/exists")
    assert resp.status_code == 200
    assert resp.json() == {"filename": "clip.mp3", "exists": True}
    assert b"SECRET-BYTES" not in resp.content


def test_exists_reports_an_absent_file_as_false_not_404(api):
    api.post("/media/files", json={"filename": "other.mp3", "data_base64": base64.b64encode(b"x").decode()})
    resp = api.get("/media/files/clip.mp3/exists")
    assert resp.status_code == 200
    assert resp.json() == {"filename": "clip.mp3", "exists": False}


def test_exists_does_not_create_touch_or_move_the_file(api, settings):
    api.post("/media/files", json={"filename": "keep.png", "data_base64": base64.b64encode(b"img").decode()})
    # Anki keeps media in `<collection stem>.media` beside the collection file
    media_dir = os.path.splitext(settings.collection_path)[0] + ".media"
    assert os.listdir(media_dir) == ["keep.png"]
    before = {n: os.stat(os.path.join(media_dir, n)).st_mtime_ns for n in os.listdir(media_dir)}
    assert api.get("/media/files/keep.png/exists").json()["exists"] is True
    assert api.get("/media/files/absent.png/exists").json()["exists"] is False
    after = {n: os.stat(os.path.join(media_dir, n)).st_mtime_ns for n in os.listdir(media_dir)}
    assert after == before


def test_exists_refuses_traversal_loudly(api, settings):
    # the collection file DOES exist one level above the media folder: a traversal
    # must be a 400, never an answer about it (and never a 404 that reads as "absent")
    collection = os.path.basename(settings.collection_path)
    for path in (
        f"/media/files/..%2F{collection}/exists",
        "/media/files/..%2F..%2Fsecret/exists",
        "/media/files/sub%2Fname.png/exists",
        f"/media/files/..%5C{collection}/exists",
        "/media/files/%2E%2E/exists",
        "/media/files/%2E/exists",
    ):
        resp = api.get(path)
        assert resp.status_code == 400, (path, resp.status_code, resp.text)
