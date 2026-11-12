"""Explicit business filters; upload timestamps never stand in for effective dates."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DocumentSearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engineering_model: str | None = Field(default=None, min_length=1, max_length=128)
    applicable_revision: str | None = Field(default=None, min_length=1, max_length=128)
    upload_version: int | None = Field(default=None, ge=1)
    effective_on: date | None = None
    document_type: Literal["design", "material", "price", "other"] | None = None

    @field_validator("engineering_model", "applicable_revision")
    @classmethod
    def normalize_key(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip().upper()
            if not value:
                raise ValueError("business key cannot be blank")
        return value


class DocumentBusinessMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engineering_model: str = Field(min_length=1, max_length=128)
    applicable_revision: str = Field(min_length=1, max_length=128)
    document_type: Literal["design", "material", "price", "other"]
    effective_from: date | None = None
    effective_to: date | None = None
    source_note: str = Field(min_length=1, max_length=1000, description="声明依据，如文件页码；不是模型确认事实")
    expected_lock_version: int = Field(ge=1)

    @field_validator("engineering_model", "applicable_revision")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        return DocumentSearchFilters.normalize_key(value)

    @model_validator(mode="after")
    def dates_ordered(self):
        if self.effective_to and not self.effective_from:
            raise ValueError("effective_to requires effective_from")
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to precedes effective_from")
        if not self.source_note.strip():
            raise ValueError("source_note cannot be blank")
        return self


class DocumentSearchRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=128)
    query: str = Field(default="", max_length=4000)
    filters: DocumentSearchFilters = Field(default_factory=DocumentSearchFilters)
    limit: int = Field(default=8, ge=1, le=10)
