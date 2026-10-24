from datetime import datetime
from typing import Any, Optional
# pyrefly: ignore [missing-import]
from pydantic import BaseModel


class ApiResponse(BaseModel):
    status: int
    message: str
    data: Optional[Any] = None
    lastUpdated: Optional[datetime] = None
