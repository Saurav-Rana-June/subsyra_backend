from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict


class ApiResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: int
    message: str
    data: Optional[Any] = None
    lastUpdated: Optional[datetime] = None
    cached: Optional[bool] = None
    ttl_remaining: Optional[int] = None
