from pydantic import BaseModel
from typing import Optional, Dict, List, Any


class HealthResponse(BaseModel):
    status: str
    last_updated: Optional[str] = None
    sources: Dict[str, int]
    freshness: Dict[str, str]
    uptime_seconds: int
    # Short id of the serving instance. On multi-instance hosts every request may
    # reach a different copy; this lets monitoring tell them apart.
    instance: str = ""


class RefreshResponse(BaseModel):
    status: str


class AisFeedResponse(BaseModel):
    status: str
    ingested: int = 0


class RouteResponse(BaseModel):
    orig_loc: Optional[list] = None
    dest_loc: Optional[list] = None
    origin_name: Optional[str] = None
    dest_name: Optional[str] = None
