"""凭据与供应商发现路由（Q1：自 api.py register_api 逐字迁移）。"""
from wuxing.credentials import (
    CredentialError,
    CredentialShadowed,
)
from wuxing.credentials import (
    derive_ref as credential_derive_ref,
)
from wuxing.credentials import (
    describe as credential_describe,
)
from wuxing.credentials import (
    resolve as credential_resolve,
)
from wuxing.credentials import (
    set as credential_set,
)
from wuxing.credentials import (
    unset as credential_unset,
)
from wuxing.providers_catalog import catalog_entries
from wuxing.shell.web.provider_probe import ProbeError, discover_models
from wuxing.shell.web.server import error_response, json_response

from .base import _guard


def register(server, ctx) -> None:
    @_guard
    def h_credential_get(req):
        """凭据状态（configured/source/writable/shadowed）——永不含值。"""
        try:
            return json_response(credential_describe(req.params["ref"]))
        except CredentialError as exc:
            return error_response(422, "invalid", str(exc))

    @_guard
    def h_credential_set(req):
        body = req.json() or {}
        value = body.get("value")
        try:
            out = credential_set(req.params["ref"],
                                 value if isinstance(value, str) else "")
        except CredentialShadowed as exc:
            return error_response(409, "credential/shadowed", str(exc))
        except CredentialError as exc:
            return error_response(422, "invalid", str(exc))
        return json_response({"ok": True, **out})

    @_guard
    def h_credential_delete(req):
        try:
            out = credential_unset(req.params["ref"])
        except CredentialError as exc:
            return error_response(422, "invalid", str(exc))
        return json_response({"ok": True, **out})

    @_guard
    def h_providers_catalog(req):
        """供应商目录（R5-1）——官方约定：名称/base_url/协议/环境变量/文档。"""
        return json_response({"providers": catalog_entries()})

    @_guard
    def h_providers_discover(req):
        body = req.json() or {}
        base_url = body.get("base_url")
        ptype = body.get("type")
        if not isinstance(base_url, str) or not isinstance(ptype, str):
            return error_response(422, "invalid", "base_url/type 必填")
        if not base_url.startswith(("http://", "https://")):
            return error_response(422, "invalid", "base_url 需为 http(s) URL")
        draft = body.get("key")
        api_key = draft if isinstance(draft, str) and draft else None
        if not api_key:
            ref = body.get("credential_ref")
            if ref is None:
                ref = credential_derive_ref(ptype)
            if isinstance(ref, str) and ref:
                api_key = credential_resolve(ref)
        try:
            models = discover_models(base_url, ptype, api_key)
        except ProbeError as exc:
            return error_response(502, "provider/discovery-failed", str(exc))
        return json_response({"models": models})

    server.add_route("GET", r"^/api/v1/credentials/(?P<ref>[^/]+)$", h_credential_get)
    server.add_route("PUT", r"^/api/v1/credentials/(?P<ref>[^/]+)$", h_credential_set)
    server.add_route("DELETE", r"^/api/v1/credentials/(?P<ref>[^/]+)$", h_credential_delete)
    server.add_route("GET", r"^/api/v1/providers/catalog$", h_providers_catalog)
    server.add_route("POST", r"^/api/v1/providers/discover$", h_providers_discover)
