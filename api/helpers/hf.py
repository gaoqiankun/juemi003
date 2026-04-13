from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException, status

try:
    from huggingface_hub import (
        constants as _hf_constants,
    )
    from huggingface_hub import (
        get_token as _hf_get_token,
    )
    from huggingface_hub import (
        hf_api as _hf_api_module,
    )
    from huggingface_hub import (
        login as _hf_login,
    )
    from huggingface_hub import (
        logout as _hf_logout,
    )
    from huggingface_hub import (
        whoami as _hf_whoami,
    )
except Exception:
    _hf_constants = None
    _hf_api_module = None
    _hf_get_token = None
    _hf_login = None
    _hf_logout = None
    _hf_whoami = None

HF_ENDPOINT_ENV_KEY = "HF_ENDPOINT"
HF_DEFAULT_ENDPOINT = "https://huggingface.co"

def _ensure_hf_client_available() -> None:
    if not all(callable(item) for item in (_hf_get_token, _hf_login, _hf_logout, _hf_whoami)):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="huggingface_hub is not available",
        )

def _normalize_hf_endpoint(raw_value: Any, *, strict: bool) -> str:
    endpoint = str(raw_value or "").strip()
    if not endpoint:
        return HF_DEFAULT_ENDPOINT
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        if strict:
            raise ValueError("endpoint must be a valid http(s) URL")
        return HF_DEFAULT_ENDPOINT
    normalized_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, "", ""))

def _set_hf_endpoint(endpoint: str) -> str:
    normalized_endpoint = _normalize_hf_endpoint(endpoint, strict=False)
    os.environ[HF_ENDPOINT_ENV_KEY] = normalized_endpoint
    if _hf_constants is not None:
        try:
            _hf_constants.ENDPOINT = normalized_endpoint
        except Exception:
            pass
    if _hf_api_module is not None:
        try:
            _hf_api_module.ENDPOINT = normalized_endpoint
            api_client = getattr(_hf_api_module, "api", None)
            if api_client is not None:
                api_client.endpoint = normalized_endpoint
        except Exception:
            pass
    return normalized_endpoint

def _current_hf_endpoint() -> str:
    return _normalize_hf_endpoint(os.environ.get(HF_ENDPOINT_ENV_KEY, HF_DEFAULT_ENDPOINT), strict=False)

def _resolve_hf_status() -> tuple[bool, str | None]:
    _ensure_hf_client_available()
    token = _hf_get_token()
    if not token:
        return False, None
    try:
        profile = _hf_whoami(token=token)
    except Exception:
        return True, None
    profile_dict = profile if isinstance(profile, dict) else {}
    username = str(profile_dict.get("name") or "").strip()
    return True, username or None

def _is_hf_repo_id(value: str) -> bool:
    normalized = str(value or "").strip()
    parts = normalized.split("/")
    if len(parts) != 2:
        return False
    return all(part and part == part.strip() for part in parts)
