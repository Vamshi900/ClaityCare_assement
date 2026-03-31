import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, BigInteger, Boolean, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import DeclarativeBase, relationship

class Base(DeclarativeBase):
    pass

class Policy(Base):
    __tablename__ = "policies"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(Text, nullable=False)
    guideline_code = Column(Text)
    version = Column(Text)
    pdf_url = Column(Text, nullable=False, unique=True)
    source_page_url = Column(Text, nullable=False)
    discovered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    status = Column(Text, nullable=False, default="discovered")
    downloads = relationship("Download", back_populates="policy")
    structured = relationship("StructuredPolicy", back_populates="policy")

class Download(Base):
    __tablename__ = "downloads"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_id = Column(UUID(as_uuid=True), ForeignKey("policies.id", ondelete="CASCADE"), nullable=False)
    stored_location = Column(Text)
    downloaded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    http_status = Column(Integer)
    file_size_bytes = Column(BigInteger)
    content_hash = Column(Text)
    error = Column(Text)
    attempt_number = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    policy = relationship("Policy", back_populates="downloads")

class StructuredPolicy(Base):
    __tablename__ = "structured_policies"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_id = Column(UUID(as_uuid=True), ForeignKey("policies.id", ondelete="CASCADE"), nullable=False)
    extracted_text_ref = Column(Text)
    structured_json = Column(JSONB, nullable=False)
    structured_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    llm_metadata = Column(JSONB, nullable=False)
    validation_error = Column(Text)
    initial_only_method = Column(Text)
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    policy = relationship("Policy", back_populates="structured")

class Job(Base):
    __tablename__ = "jobs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="queued")
    source_url = Column(Text)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    metadata_ = Column("metadata", JSONB)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
