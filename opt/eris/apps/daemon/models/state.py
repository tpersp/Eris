from pydantic import BaseModel


class ErisState(BaseModel):
    mode: str = "web"
    url: str = ""
    uptime: float = 0.0

