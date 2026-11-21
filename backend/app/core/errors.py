import logging
from uuid import uuid4
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

logger = logging.getLogger("rag.errors")


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status


def ok(data=None):
    return {"code": "OK", "message": "成功", "data": data}


def install_handlers(app):
    async def handle(request: Request, exc: Exception):
        request_id = uuid4().hex
        if isinstance(exc, AppError):
            code, message, status = exc.code, exc.message, exc.status
        elif isinstance(exc, RequestValidationError):
            code, message, status = "VALIDATION_ERROR", "请求参数不合法", 422
        elif isinstance(exc, SQLAlchemyError):
            code, message, status = "DATABASE_ERROR", "数据库暂时不可用", 503
        elif isinstance(exc, HTTPException):
            code, message, status = "HTTP_ERROR", "请求无法处理", exc.status_code
        else:
            code, message, status = "INTERNAL_ERROR", "服务器内部错误", 500
        # Never log exception objects, request bodies, headers, URLs or SQL.
        logger.warning("event=%s request_id=%s", code, request_id)
        return JSONResponse(status_code=status, content={
            "code": code, "message": message, "data": None, "request_id": request_id})
    for cls in (AppError, RequestValidationError, SQLAlchemyError, HTTPException, Exception):
        app.add_exception_handler(cls, handle)

    return handle
