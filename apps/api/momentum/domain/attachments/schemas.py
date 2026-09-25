from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ExtractStatus = Literal["pending", "done", "skipped", "failed"]


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    task_id: uuid.UUID | None
    comment_id: uuid.UUID | None
    filename: str
    mime: str
    size_bytes: int
    sha256: str
    extract_status: ExtractStatus
    uploaded_by: uuid.UUID
    created_at: datetime
