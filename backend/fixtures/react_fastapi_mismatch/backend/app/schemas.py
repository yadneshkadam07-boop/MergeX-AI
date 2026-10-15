from datetime import datetime

from pydantic import BaseModel


class UserCreate(BaseModel):
    email: str
    # The frontend sends "fullName"; this expects "full_name" (MX-API-004).
    full_name: str


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    created_at: datetime


class TaskCreate(BaseModel):
    title: str
    owner_id: int


class TaskOut(BaseModel):
    id: int
    title: str
    completed: bool
    owner_id: int
