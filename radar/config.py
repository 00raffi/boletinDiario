import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from .catalog import clean_terms, valid_categories
from .colibri_catalog import FING, INCO

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("RADAR_DATA_DIR", str(ROOT / "data"))).resolve()


class Settings(BaseModel):
    model: str = Field(default="qwen3.5:4b", min_length=1, max_length=100)
    timezone: str = "America/Montevideo"
    daily_time: str = "07:00"
    schedule_enabled: bool = True
    categories: list[str] = Field(default=["cs.AI"], min_length=1)
    keywords: list[str] = Field(default=[])
    excluded_keywords: list[str] = Field(default=[])
    interests_text: str = Field(default="", max_length=4000)
    keyword_filter: bool = False
    arxiv_enabled: bool = True
    colibri_enabled: bool = False
    colibri_scopes: list[str] = Field(default=[FING, INCO], min_length=1, max_length=24)
    colibri_keywords: list[str] = Field(default=[])
    colibri_excluded_keywords: list[str] = Field(default=[])
    colibri_keyword_filter: bool = False
    colibri_interests_text: str = Field(default="", max_length=4000)
    colibri_types: list[str] = Field(default=[], max_length=30)
    colibri_bulletin_limit: int = Field(default=8, ge=0, le=30)
    initial_days: int = Field(default=7, ge=1, le=30)
    metadata_overlap_days: int = Field(default=7, ge=3, le=30)
    bulletin_limit: int = Field(default=10, ge=1, le=30)
    pause_summaries: bool = False
    desktop_notifications: bool = True
    max_chunks: int = Field(default=24, ge=1, le=40)
    max_pdf_mb: int = Field(default=100, ge=1, le=250)
    unload_after_paper: bool = True
    recycle_every_chunks: int = Field(default=4, ge=0, le=40)

    @field_validator("model")
    @classmethod
    def local_model(cls, value):
        value = value.strip()
        if not value or "cloud" in value.lower() or any(c.isspace() for c in value):
            raise ValueError("Selecciona una etiqueta de modelo local, sin espacios ni 'cloud'.")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError("Zona horaria IANA desconocida.")
        return value

    @field_validator("daily_time")
    @classmethod
    def valid_time(cls, value):
        import re
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("Usa HH:MM, entre 00:00 y 23:59.")
        return value

    @field_validator("categories")
    @classmethod
    def valid_categories(cls, value):
        return valid_categories(value)

    @field_validator("keywords", "excluded_keywords", "colibri_keywords", "colibri_excluded_keywords", "colibri_types")
    @classmethod
    def clean_keywords(cls, value):
        return [term.lower() for term in clean_terms(value)]

    @field_validator("colibri_scopes")
    @classmethod
    def public_scope_ids(cls, value):
        return list(dict.fromkeys(str(UUID(scope)) for scope in value))

    def quotas(self, kind="brief"):
        if kind == "analysis":
            return {"arxiv": 0, "colibri": 0}
        total = self.bulletin_limit
        colibri = self.colibri_bulletin_limit
        if not self.colibri_enabled:
            return {"arxiv": total if self.arxiv_enabled else 0, "colibri": 0}
        return {"colibri": min(total, colibri), "arxiv": max(0, total - colibri) if self.arxiv_enabled else 0}

    def filters(self, source):
        if source == "arxiv":
            return self.categories, self.keywords, self.excluded_keywords, self.keyword_filter
        return self.colibri_scopes, self.colibri_keywords, self.colibri_excluded_keywords, self.colibri_keyword_filter

    @model_validator(mode="after")
    def meaningful_filter(self):
        if self.keyword_filter and not self.keywords:
            raise ValueError("El filtro obligatorio necesita al menos un término.")
        if self.colibri_keyword_filter and not self.colibri_keywords:
            raise ValueError("El filtro obligatorio de Colibrí necesita al menos un término.")
        if self.colibri_enabled and self.colibri_bulletin_limit > self.bulletin_limit:
            raise ValueError("Los cupos de Colibrí no pueden superar los totales diarios.")
        return self


def daily_slot(now: datetime, settings: Settings) -> datetime:
    local = now.astimezone(ZoneInfo(settings.timezone))
    hour, minute = map(int, settings.daily_time.split(":"))
    slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return slot if local >= slot else slot - timedelta(days=1)


def next_slot(now: datetime, settings: Settings) -> datetime:
    return daily_slot(now, settings) + timedelta(days=1)
