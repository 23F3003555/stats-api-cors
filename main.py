
import os
from time import perf_counter
from uuid import uuid4

import jwt
import yaml
from dotenv import dotenv_values
from jwt.exceptions import InvalidTokenError
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI()

# Assignment portal origin
ALLOWED_ORIGIN = "https://exam.sanand.workers.dev"
EMAIL = "23f3003555@ds.study.iitm.ac.in"

ISSUER = "https://idp.exam.local"
AUDIENCE = "tds-3z4gzmm8.apps.exam.local"

PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA2okOHspNjgA+2rTLbeuY
cxiP/hG8C6Sb9iwg3yiLAA4HCnpITcbWCSelbvbYGuc3EbNy4xFyf5Cbj5DHJMID
EkryOgyd2giIIIBOUBj8S63uGcnRpOBh9NFatfNwheKuzsPuVNldu6A9cNteNpXc
WyJjG2axVfmq7i6SuKr1JoWYG7xTTAvKPujSl4OtsQfO3h5NepzdfXpr28oNnzfW
ed+zclR6BcmNNo/WVfJ4xyCLSf0BCOgdTgW6PdaChd1l9VDetJZVEgC5tkyvXsfI
SI6iyrYbKR0NEBSqq4XkadEjsCs4F1RncsS4LlgniT7GlkL9Mce3b0wGLs9/7ZIX
dQIDAQAB
-----END PUBLIC KEY-----"""

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# Request ID and process time middleware
@app.middleware("http")
async def add_request_headers(request: Request, call_next):
    start_time = perf_counter()
    request_id = str(uuid4())

    try:
        response = await call_next(request)
    except Exception:
        response = JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
        )

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = (
        f"{max(0.0, perf_counter() - start_time):.6f}"
    )
    return response


# Stats endpoint
@app.get("/stats")
async def get_stats(values: str = Query(...)):
    try:
        parts = values.split(",")
        if any(not part.strip() for part in parts):
            raise ValueError("Empty value")

        numbers = [int(part.strip()) for part in parts]
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="values must be comma-separated integers",
        )

    total = sum(numbers)
    count = len(numbers)

    return {
        "email": EMAIL,
        "count": count,
        "sum": total,
        "min": min(numbers),
        "max": max(numbers),
        "mean": round(total / count, 6),
    }


# JWT verification endpoint
class VerifyRequest(BaseModel):
    token: str


@app.post("/verify")
async def verify_token(body: VerifyRequest):
    try:
        claims = jwt.decode(
            body.token,
            PUBLIC_KEY,
            algorithms=["RS256"],
            issuer=ISSUER,
            audience=AUDIENCE,
            options={
                "require": ["exp", "iss", "aud", "email", "sub"]
            },
        )

        return {
            "valid": True,
            "email": claims["email"],
            "sub": claims["sub"],
            "aud": claims["aud"],
        }

    except (InvalidTokenError, KeyError, TypeError, ValueError):
        return JSONResponse(
            status_code=401,
            content={"valid": False},
        )


# Default configuration
DEFAULT_CONFIG = {
    "port": 8000,
    "workers": 1,
    "debug": False,
    "log_level": "info",
    "api_key": "default-secret-000",
}


def coerce_value(key: str, value):
    if key in ("port", "workers"):
        return int(value)

    if key == "debug":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in (
            "true", "1", "yes", "on"
        )

    if value is None:
        return ""

    return str(value)


# Effective configuration endpoint
@app.get("/effective-config")
async def effective_config(set: list[str] | None = Query(default=None)):
    config = DEFAULT_CONFIG.copy()

    # Layer 2: environment-specific YAML
    environment = os.getenv("APP_ENV", "development")
    yaml_path = f"config.{environment}.yaml"

    if os.path.exists(yaml_path):
        with open(yaml_path, "r", encoding="utf-8") as file:
            yaml_config = yaml.safe_load(file) or {}

        for key, value in yaml_config.items():
            key = key.lower()
            config[key] = coerce_value(key, value)

    # Layer 3: .env file
    env_file = dotenv_values(".env")

    # NUM_WORKERS alias
    if env_file.get("NUM_WORKERS") is not None:
        config["workers"] = coerce_value(
            "workers", env_file["NUM_WORKERS"]
        )

    env_mapping = {
        "APP_PORT": "port",
        "APP_WORKERS": "workers",
        "APP_DEBUG": "debug",
        "APP_LOG_LEVEL": "log_level",
        "APP_API_KEY": "api_key",
    }

    for env_name, config_key in env_mapping.items():
        if env_file.get(env_name) is not None:
            config[config_key] = coerce_value(
                config_key, env_file[env_name]
            )

    # Layer 4: actual OS environment variables
    for env_name, config_key in env_mapping.items():
        if env_name in os.environ:
            config[config_key] = coerce_value(
                config_key, os.environ[env_name]
            )

    # Layer 5: query-string overrides
    if set:
        for item in set:
            if "=" not in item:
                continue

            key, value = item.split("=", 1)
            key = key.strip().lower()

            if key in config:
                config[key] = coerce_value(key, value)

    # Always mask the API key
    config["api_key"] = "****"

    return config
