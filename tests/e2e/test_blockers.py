"""The two reviewer parity blockers."""


def test_compare_answer_returns_diff_html(api):
    out = api.post("/scheduler/compare-answer", json={"expected": "Paris", "provided": "Pari"}).json()
    assert "comparison_html" in out
    assert "<" in out["comparison_html"]  # rendered colored diff markup


def test_compare_answer_exact_match(api):
    out = api.post("/scheduler/compare-answer", json={"expected": "Paris", "provided": "Paris"}).json()
    assert "Paris" in out["comparison_html"]


def test_extract_cloze_for_typing(api):
    text = "The {{c1::quick}} brown {{c2::fox}}"
    assert api.post("/notes/extract-cloze-for-typing", json={"text": text, "ordinal": 1}).json()["text"] == "quick"
    assert api.post("/notes/extract-cloze-for-typing", json={"text": text, "ordinal": 2}).json()["text"] == "fox"


def test_tts_voices_endpoint(api):
    # TTS is OS/engine-dependent: a box with TTS returns a voice list (200); a
    # headless box without it surfaces the backend's "not implemented" as 400.
    resp = api.get("/media/tts/voices")
    assert resp.status_code in (200, 400)
    if resp.status_code == 200:
        voices = resp.json()
        assert isinstance(voices, list)
        for v in voices:
            assert isinstance(v, dict) and v
    else:
        assert resp.json()["error"] == "invalid_input"
