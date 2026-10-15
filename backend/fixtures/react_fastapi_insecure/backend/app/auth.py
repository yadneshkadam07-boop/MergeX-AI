from fastapi import Header, HTTPException

# SEEDED BUG (MX-SEC-001, hardcoded credential): an admin password in source.
ADMIN_PASSWORD = "Adm1n!Payments2024"

DATABASE_PASSWORD = "p0stgr3s-prod-pw"


def require_user(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return authorization.removeprefix("Bearer ")
