from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID

class JobCreate(BaseModel):
    type: str  # discovery, download, structure
    source_url: Optional[str] = None
    policy_ids: Optional[list[str]] = None

class JobResponse(BaseModel):
    id: UUID
    type: str
    status: str
    source_url: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    metadata_: Optional[dict] = None
    error: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

class PolicyResponse(BaseModel):
    id: UUID
    title: str
    guideline_code: Optional[str]
    version: Optional[str]
    pdf_url: str
    source_page_url: str
    discovered_at: datetime
    status: str
    has_download: bool = False
    has_structured_tree: bool = False

    class Config:
        from_attributes = True

class PolicyDetailResponse(PolicyResponse):
    download_status: Optional[str] = None
    structured_json: Optional[dict] = None

class RuleNode(BaseModel):
    rule_id: str
    rule_text: str
    operator: Optional[str] = None
    rules: Optional[list["RuleNode"]] = None

class CriteriaTree(BaseModel):
    title: str
    insurance_name: str
    rules: RuleNode

class VersionResponse(BaseModel):
    version: int
    is_current: bool
    structured_at: Optional[datetime]
    llm_metadata: Optional[dict]
    validation_error: Optional[str]
    class Config:
        from_attributes = True


class StatsResponse(BaseModel):
    total_policies: int
    total_downloaded: int
    total_structured: int
    total_failed_downloads: int
    total_validation_errors: int
