# -*- coding: utf-8 -*-
"""WMTS 访问票据签发与校验。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from app.config import settings

WMTS_PATH = "/csrap_geoserver/gwc/service/wmts"
TOKEN_PARAM = "wmts_token"


def _derive_secret() -> bytes:
    if settings.wmts_sign_secret:
        return settings.wmts_sign_secret.encode("utf-8")

    material = "|".join(
        [
            settings.geoserver_user,
            settings.geoserver_password,
            settings.geoserver_workspace,
            str(settings.work_dir),
            settings.geoserver_public_url or "",
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).digest()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _canonical_payload(resource: str, layer_name: str | None, ttl_seconds: int | None = None) -> dict[str, Any]:
    now = int(time.time())
    expires_in = settings.wmts_token_ttl_seconds if ttl_seconds is None else ttl_seconds
    payload: dict[str, Any] = {
        "v": 1,
        "resource": resource,
        "exp": now + max(1, int(expires_in)),
    }
    if layer_name:
        payload["layer"] = layer_name
    return payload


def build_wmts_token(resource: str, layer_name: str | None = None, ttl_seconds: int | None = None) -> str:
    """Build a signed WMTS access token for a specific resource and optional layer."""
    payload = _canonical_payload(resource, layer_name, ttl_seconds)
    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)
    signature = hmac.new(_derive_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url_encode(signature)}"


def _normalize_params(query: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for key, value in parse_qsl(query, keep_blank_values=True):
        lowered = key.lower()
        if lowered not in params:
            params[lowered] = value
    return params


def _infer_resource(params: dict[str, str]) -> str | None:
    request_name = params.get("request", "").strip().lower()
    if request_name == "getcapabilities":
        return "capabilities"

    format_name = params.get("format", "").strip().lower()
    if format_name == "application/vnd.mapbox-vector-tile":
        return "mvt"
    if format_name == "image/png":
        return "raster"
    return None


def verify_wmts_request_uri(original_uri: str | None) -> tuple[bool, str]:
    """Verify a WMTS request captured by nginx auth_request."""
    if not original_uri:
        return False, "Missing WMTS request URI"

    parsed = urlsplit(original_uri)
    if parsed.path != WMTS_PATH:
        return False, "Invalid WMTS path"

    params = _normalize_params(parsed.query)
    token = params.get(TOKEN_PARAM)
    if not token:
        return False, "Missing WMTS token"

    try:
        payload_b64, signature_b64 = token.split(".", 1)
        expected_signature = hmac.new(_derive_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
        actual_signature = _b64url_decode(signature_b64)
        if not hmac.compare_digest(expected_signature, actual_signature):
            return False, "Invalid WMTS token signature"

        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return False, "Invalid WMTS token payload"

    if int(payload.get("exp", 0)) < int(time.time()):
        return False, "WMTS token expired"

    expected_resource = _infer_resource(params)
    if expected_resource is None:
        return False, "Unsupported WMTS request"
    if payload.get("resource") != expected_resource:
        return False, "WMTS token resource mismatch"

    token_layer = str(payload.get("layer") or "")
    request_layer = str(params.get("layer") or "")
    if expected_resource != "capabilities":
        if not token_layer or not request_layer or token_layer != request_layer:
            return False, "WMTS layer mismatch"

    return True, ""
