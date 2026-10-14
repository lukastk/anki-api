"""CORS is explicit browser permission, not server authentication."""
import json

import pytest
from fastapi.testclient import TestClient

from anki_api.app import create_app
from anki_api.config import Settings


@pytest.mark.parametrize('origin', [
    '*', 'null', '', 'https://*.example.test', 'https://user:pass@example.test',
    'https://example.test/', 'https://example.test/path', 'https://example.test?q=1',
    'https://example.test#fragment', 'https://example.test:443', 'https://example.test:',
    'https://example.test:99999', 'https://example.test:0', ' https://example.test',
    'https://example.test\n', 'https://example.test\\x', 'https://example%2etest',
    'HTTPS://EXAMPLE.TEST', 'file://localhost', 'data:text/html,x', '//example.test',
    'https://bad..host', 'https://999.999.999.999', 'https://-bad.example',
])
def test_invalid_or_broad_origin_refuses_at_configuration(origin, tmp_path):
    with pytest.raises(ValueError, match='CORS origin'):
        Settings(collection_path=str(tmp_path / 'never-opened.anki2'), cors_origins=(origin,))


@pytest.mark.parametrize('origins', [(), ('https://trusted.example',),
    ('http://localhost:5173', 'app://observed-desktop.test', 'custom-app://observed-mobile.test'),
    ('http://[::1]:8000',)])
def test_exact_origins_are_accepted_without_inventing_a_mobile_default(origins, tmp_path):
    assert Settings(collection_path=str(tmp_path / 'never-opened.anki2'), cors_origins=origins).cors_origins == origins


def test_environment_requires_json_array_and_preserves_default(monkeypatch, tmp_path):
    monkeypatch.setenv('ANKI_API_COLLECTION', str(tmp_path / 'never-opened.anki2'))
    monkeypatch.delenv('ANKI_API_CORS_ORIGINS', raising=False)
    assert Settings.from_env().cors_origins == ()
    monkeypatch.setenv('ANKI_API_CORS_ORIGINS', json.dumps(['https://trusted.example']))
    assert Settings.from_env().cors_origins == ('https://trusted.example',)
    for value in ('', 'null', '"https://trusted.example"', '{}', '[123]', '["*"]', '["https://trusted.example", "https://trusted.example"]'):
        monkeypatch.setenv('ANKI_API_CORS_ORIGINS', value)
        with pytest.raises(ValueError):
            Settings.from_env()


def test_default_behavior_keeps_http_clients_and_grants_no_cross_origin_permission(tmp_path):
    collection = tmp_path / 'never-opened.anki2'
    # No lifespan: these public API schema/preflight checks must not open a collection.
    client = TestClient(create_app(Settings(collection_path=str(collection))))
    assert client.get('/openapi.json').status_code == 200
    response = client.get('/openapi.json', headers={'Origin': 'https://untrusted.example'})
    assert response.status_code == 200
    assert 'access-control-allow-origin' not in response.headers
    assert client.options('/v1/decks', headers={'Origin': 'https://untrusted.example', 'Access-Control-Request-Method': 'POST'}).status_code == 405
    assert not collection.exists()


def test_explicit_origin_preflight_actual_read_and_write_use_exact_noncredentialed_policy(tmp_path):
    trusted = 'https://trusted.example'
    with TestClient(create_app(Settings(collection_path=str(tmp_path / 'fresh.anki2'), cors_origins=(trusted,)))) as client:
        response = client.options('/v1/decks', headers={'Origin': trusted, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type'})
        assert response.status_code == 200
        assert response.headers['access-control-allow-origin'] == trusted
        assert set(response.headers['access-control-allow-methods'].split(', ')) == {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}
        assert '*' not in response.headers['access-control-allow-headers']
        assert 'access-control-allow-credentials' not in response.headers
        assert 'Origin' in response.headers['vary']
        response = client.post('/v1/decks', json={'name': 'CORS scratch'}, headers={'Origin': trusted})
        assert response.status_code == 200
        assert response.headers['access-control-allow-origin'] == trusted
        assert 'access-control-allow-credentials' not in response.headers
        assert any(d['name'] == 'CORS scratch' for d in client.get('/v1/decks').json())
        assert client.get('/v1/decks', headers={'Origin': trusted}).headers['access-control-allow-origin'] == trusted


@pytest.mark.parametrize('origin,method,headers', [
    ('https://untrusted.example', 'POST', 'content-type'),
    ('https://trusted.example.evil.test', 'POST', 'content-type'),
    ('null', 'POST', 'content-type'),
    ('https://trusted.example', 'TRACE', 'content-type'),
    ('https://trusted.example', 'POST', 'authorization'),
    ('https://trusted.example', 'POST', 'x-unapproved-header'),
])
def test_disallowed_preflight_never_reaches_a_collection(origin, method, headers, tmp_path):
    collection = tmp_path / 'never-opened.anki2'
    client = TestClient(create_app(Settings(collection_path=str(collection), cors_origins=('https://trusted.example',))))
    response = client.options('/v1/decks', headers={'Origin': origin, 'Access-Control-Request-Method': method, 'Access-Control-Request-Headers': headers})
    assert response.status_code == 400
    if origin != 'https://trusted.example':
        assert 'access-control-allow-origin' not in response.headers
    assert 'access-control-allow-credentials' not in response.headers
    assert not collection.exists()


def test_denied_actual_origin_does_not_gain_browser_read_access(tmp_path):
    client = TestClient(create_app(Settings(collection_path=str(tmp_path / 'never-opened.anki2'), cors_origins=('https://trusted.example',))))
    response = client.get('/openapi.json', headers={'Origin': 'https://untrusted.example'})
    assert response.status_code == 200  # CORS is not authentication or a request firewall.
    assert 'access-control-allow-origin' not in response.headers
