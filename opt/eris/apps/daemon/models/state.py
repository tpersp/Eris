from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ServiceStatus(BaseModel):
    status: str = "unknown"
    detail: Optional[str] = None


class ErisState(BaseModel):
    mode: str = "web"
    url: str = ""
    uptime: float = 0.0
    services: Dict[str, ServiceStatus] = Field(default_factory=dict)
    media: Optional[Dict[str, Any]] = None
    paused: bool = False
