from fastapi import Header, HTTPException


def require_admin(authorization: str = Header(default="")):
    """Reject anything without a bearer token."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Admin token required")
    return authorization.removeprefix("Bearer ")
