from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        codes = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 501: "NOT_IMPLEMENTED", 503: "UNAVAILABLE"}
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": codes.get(exc.status_code, "REQUEST_ERROR"), "message": str(exc.detail), "data": None},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError):
        # 不回显输入值，避免密码和令牌出现在错误响应中。
        return JSONResponse(status_code=422, content={"code": "VALIDATION_ERROR", "message": "请求参数不符合接口契约，请查看 /docs。", "data": None})

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, _exc: Exception):
        return JSONResponse(status_code=500, content={"code": "INTERNAL_ERROR", "message": "服务内部错误。", "data": None})
