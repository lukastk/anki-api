"""Image Occlusion authoring [parity]."""

# a minimal valid 1x1 PNG
PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC"

RECT = {"shape": "rect", "properties": {"left": 10, "top": 20, "width": 100, "height": 50}}


def test_ensure_notetype(api):
    out = api.post("/notetypes/image-occlusion").json()
    assert out["id"]
    assert any(n["name"] == "Image Occlusion" for n in api.get("/notetypes").json())


def test_create_io_note_inline_image(api):
    created = api.post("/notes/image-occlusion", json={
        "occlusions": [RECT, {"shape": "rect", "properties": {"left": 5, "top": 5, "width": 10, "height": 10}}],
        "header": "Where?", "back_extra": "extra", "tags": ["anatomy"],
        "image_data_base64": PNG_B64, "image_upload_name": "diagram.png",
    }).json()
    assert created["id"]

    note = api.get(f"/notes/{created['id']}/image-occlusion").json()
    # two occlusions were stored, parsed back into shapes
    assert len(note["occlusions"]) == 2
    assert note["occlusions"][0]["shapes"][0]["shape"] == "rect"
    assert note["header"] == "Where?"


def test_create_requires_occlusions(api):
    resp = api.post("/notes/image-occlusion", json={
        "occlusions": [], "image_data_base64": PNG_B64,
    })
    assert resp.status_code == 422


def test_create_requires_image(api):
    resp = api.post("/notes/image-occlusion", json={"occlusions": [RECT]})
    assert resp.status_code == 422


def test_update_io_note(api):
    created = api.post("/notes/image-occlusion", json={
        "occlusions": [RECT], "header": "old", "image_data_base64": PNG_B64,
    }).json()
    out = api.put(f"/notes/{created['id']}/image-occlusion", json={"header": "new"}).json()
    assert "changes" in out
    assert api.get(f"/notes/{created['id']}/image-occlusion").json()["header"] == "new"


def test_get_non_io_note_is_404(api):
    nid = api.make_note(deck="D", front="plain")["id"]
    assert api.get(f"/notes/{nid}/image-occlusion").status_code == 404
