"""Browser cookie writes require a same-origin request or a custom header."""
from urllib.parse import urlsplit
from starlette.responses import JSONResponse


async def protect_cookie_write(request, call_next):
    from auth import SESSION_COOKIE
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.cookies.get(SESSION_COOKIE):
        origin = request.headers.get("origin")
        site = request.headers.get("sec-fetch-site")
        expected = (request.url.scheme, request.url.netloc)
        parsed = urlsplit(origin or "")
        valid_origin = bool(origin) and (parsed.scheme, parsed.netloc) == expected
        # Explicit CORS origins may send credentialed API calls, but must also
        # send the custom header (a preflight-protected, non-simple request).
        from main import CORS_ORIGINS
        trusted_cross_origin = origin in CORS_ORIGINS and request.headers.get("x-famledger-csrf") == "1"
        if (site == "cross-site" and not trusted_cross_origin) or (origin and not valid_origin and not trusted_cross_origin):
            return JSONResponse({"detail": "请求来源校验失败"}, status_code=403)
        if not valid_origin and request.headers.get("x-famledger-csrf") != "1":
            return JSONResponse({"detail": "缺少 CSRF 请求头"}, status_code=403)
    return await call_next(request)
