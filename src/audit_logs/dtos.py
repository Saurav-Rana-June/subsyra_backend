from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime


class AuditLogReadSchema(BaseModel):
    """
    Schema for serializing audit log entries returned via API.
    """
    id: int
    user_id: Optional[int] = None
    action: str
    target_type: str
    target_id: Optional[int] = None
    details: Optional[Dict[str, Any]] = None
    created_at: datetime

    model_config = {"from_attributes": True}
