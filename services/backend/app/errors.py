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


class ValidationFailed(DomainError):
    code = "validation_error"
    status_code = 400
    message = "输入不合法"


class FileTooLarge(DomainError):
    code = "file_too_large"
    status_code = 413
    message = "文件超过大小限制"


class UnsupportedFile(DomainError):
    code = "unsupported_file"
    status_code = 415
    message = "不支持的文件格式"