"""Tests du garde de jeton des routes mutantes du moteur."""

import pytest
from fastapi import HTTPException

from app import main


def test_allows_all_when_token_not_configured(monkeypatch):
    monkeypatch.setattr(main.settings, "engine_api_token", "")
    # Ne doit pas lever : mode local non protégé (écoute 127.0.0.1).
    main.require_api_token(None)
    main.require_api_token("nimporte-quoi")


def test_rejects_missing_or_wrong_token(monkeypatch):
    monkeypatch.setattr(main.settings, "engine_api_token", "jeton-secret")
    with pytest.raises(HTTPException) as exc:
        main.require_api_token(None)
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException):
        main.require_api_token("mauvais-jeton")


def test_accepts_valid_token(monkeypatch):
    monkeypatch.setattr(main.settings, "engine_api_token", "jeton-secret")
    main.require_api_token("jeton-secret")  # ne lève pas


def test_all_post_routes_are_protected():
    """Chaque route POST du moteur doit porter la dépendance de jeton."""
    from fastapi.routing import APIRoute

    unprotected = []
    for route in main.app.routes:
        if not isinstance(route, APIRoute) or "POST" not in route.methods:
            continue
        depends_fns = {d.call for d in route.dependant.dependencies if d.call}
        if main.require_api_token not in depends_fns:
            unprotected.append(route.path)
    assert not unprotected, f"Routes POST sans jeton: {unprotected}"
