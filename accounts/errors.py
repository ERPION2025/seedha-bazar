from rest_framework import status
from rest_framework.exceptions import APIException, Throttled
from rest_framework.response import Response


class ApiError(APIException):
    """An error with a stable machine-readable code the app can translate."""

    def __init__(self, code: str, message: str, http_status: int = status.HTTP_400_BAD_REQUEST, **extra):
        self.status_code = http_status
        self.code = code
        self.message = message
        self.extra = extra
        super().__init__(detail=message, code=code)


def api_exception_handler(exc, context):
    from rest_framework.views import exception_handler  # lazy: avoids a circular import at startup

    if isinstance(exc, ApiError):
        body = {"error": {"code": exc.code, "message": exc.message, **exc.extra}}
        resp = Response(body, status=exc.status_code)
        retry = exc.extra.get("retry_after")
        if retry:
            resp["Retry-After"] = str(retry)
        return resp
    resp = exception_handler(exc, context)
    if resp is None:
        return None
    if isinstance(exc, Throttled):
        code = "throttled"
    elif resp.status_code == 401:
        code = "not_authenticated"
    elif resp.status_code == 403:
        code = "forbidden"
    elif resp.status_code == 404:
        code = "not_found"
    elif resp.status_code == 400:
        code = "validation_error"
    else:
        code = "error"
    detail = resp.data
    message = detail.get("detail") if isinstance(detail, dict) and "detail" in detail else None
    resp.data = {"error": {"code": code, "message": str(message) if message else "Request failed", "fields": detail if code == "validation_error" else None}}
    return resp
