"""Domain errors mapped to stable API error codes."""
from __future__ import annotations


class DomainError(Exception):
    code = "internal_error"
    status_code = 400
    message = "Request failed"

    def __init__(self, message: str | None = None, **extra):
        super().__init__(message or self.message)
        self.message = message or self.message
        self.extra = extra


class QuotaExceeded(DomainError):
    code = "quota_exceeded"
    status_code = 429
    message = "今天的免费次数已经用完"


class ActiveJobExists(DomainError):
    code = "active_job_exists"
    status_code = 409
    message = "已有一个识别任务正在进行，请等它完成"


class QueueFull(DomainError):
    code = "queue_full"
    status_code = 503
    message = "当前排队任务较多，请稍后再试"


class NotFound(DomainError):
    code = "not_found"
    status_code = 404
    message = "未找到"


class Unauthorized(DomainError):
    code = "unauthorized"
    status_code = 401
    message = "请先登录"


class Forbidden(DomainError):
    code = "forbidden"
    status_code = 403
    message = "没有权限"


class Conflict(DomainError):
    code = "conflict"
    status_code = 409
    message = "请求冲突"


class ValidationFailed(DomainError):
    code = "validation_error"
    status_code = 400
    message = "输入不合法"




class RateLimited(DomainError):
    code = "rate_limited"
    status_code = 429
    message = "操作过于频繁，请稍后再试"


class FileTooLarge(DomainError):
    code = "file_too_large"
    status_code = 413
    message = "文件超过大小限制"


class UnsupportedFile(DomainError):
    code = "unsupported_file"
    status_code = 415
    message = "不支持的文件格式"
