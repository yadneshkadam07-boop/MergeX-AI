from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.schemas import UserCreate, UserOut

router = APIRouter(tags=["users"])

_USERS: dict[int, dict] = {}


@router.get("/users", response_model=list[UserOut])
def list_users():
    return list(_USERS.values())


# The frontend requests "/api/user/{id}" (singular) -- MX-API-002.
@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: int):
    user = _USERS.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate):
    user_id = len(_USERS) + 1
    user = {
        "id": user_id,
        "email": payload.email,
        "full_name": payload.full_name,
        "created_at": datetime.utcnow(),
    }
    _USERS[user_id] = user
    return user


# The frontend calls this with POST -- MX-API-003.
@router.delete("/users/{user_id}/deactivate", status_code=204)
def deactivate_user(user_id: int):
    _USERS.pop(user_id, None)


# NOTE: there is deliberately no "/users/export" route -- MX-API-001.
