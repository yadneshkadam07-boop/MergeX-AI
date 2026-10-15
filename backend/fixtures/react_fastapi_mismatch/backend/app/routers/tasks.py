from fastapi import APIRouter, Depends

from app.deps import require_admin
from app.schemas import TaskCreate, TaskOut

router = APIRouter(tags=["tasks"])

_TASKS: dict[int, dict] = {}


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks():
    return list(_TASKS.values())


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(payload: TaskCreate):
    task_id = len(_TASKS) + 1
    task = {
        "id": task_id,
        "title": payload.title,
        "completed": False,
        "owner_id": payload.owner_id,
    }
    _TASKS[task_id] = task
    return task


# Protected by require_admin, but the frontend sends no Authorization
# header -- MX-API-005.
@router.delete("/tasks/all", status_code=204)
def delete_all_tasks(_token: str = Depends(require_admin)):
    _TASKS.clear()
