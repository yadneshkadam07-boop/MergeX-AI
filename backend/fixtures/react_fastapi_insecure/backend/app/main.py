import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import router

app = FastAPI(title="Payments API", debug=True)

# SEEDED BUG (MX-SEC-003, permissive CORS): a wildcard origin combined with
# allow_credentials=True lets any site make authenticated cross-origin calls.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SEEDED BUG (MX-SEC-001, hardcoded secret): a signing key with a committed
# default. Anyone with the source can mint valid tokens.
JWT_SIGNING_KEY = os.getenv("JWT_SIGNING_KEY", "super-secret-dev-key-do-not-ship")

app.include_router(router, prefix="/api")
