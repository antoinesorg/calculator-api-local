#!/usr/bin/env python3
"""A very simple calculator REST API server."""

from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

import json
import logging
import os
import time
import uuid

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from sqlmodel import Field, Session, SQLModel, create_engine, select

from core import add, divide, multiply, subtract

# --- Database Setup ---

DATABASE_URL = "sqlite:///calculator.db"
engine = create_engine(DATABASE_URL, echo=False)


def get_session() -> Session:  # type: ignore[misc]
    """Yield a database session."""
    with Session(engine) as session:
        yield session


# --- Models ---


class CalculationBase(SQLModel):
    """Base model for calculations."""

    operation: str
    a: float
    b: float
    result: float


class Calculation(CalculationBase, table=True):
    """Database model for stored calculations."""

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CalculationCreate(BaseModel):
    """Request body for creating a calculation."""

    operation: str
    a: float
    b: float


class CalculationResponse(CalculationBase):
    """Response model for a calculation."""

    id: int
    created_at: datetime


class CalculationRequest(BaseModel):
    """Request body for calculation endpoints."""

    a: float
    b: float


class ResultResponse(BaseModel):
    """Response body for calculation endpoints."""

    result: float


# --- Request Logging ---

REQUEST_LOGGER_NAME = "calculator.access"
LOG_FIELDS = ("method", "path", "status", "duration_ms", "request_id")


class JsonFormatter(logging.Formatter):
    """Format request log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {"level": record.levelname, "logger": record.name}
        payload.update({k: getattr(record, k) for k in LOG_FIELDS if hasattr(record, k)})
        return json.dumps(payload)


def setup_logging() -> None:
    """Attach the JSON handler once. Propagation stays enabled so caplog can capture."""
    logger = logging.getLogger(REQUEST_LOGGER_NAME)
    logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    if not any(getattr(h, "_calculator_json", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler._calculator_json = True  # type: ignore[attr-defined]
        logger.addHandler(handler)


class RequestLoggingMiddleware:
    """Pure ASGI middleware: logs method, path, status, duration and request id.

    Request and response bodies are never read or logged.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = logging.getLogger(REQUEST_LOGGER_NAME)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        request_id = headers.get(b"x-request-id", b"").decode("latin-1") or str(uuid.uuid4())
        status = 500  # reported if the app raises before sending a response
        start = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = {
                    **message,
                    "headers": [*message.get("headers", []), (b"x-request-id", request_id.encode("latin-1"))],
                }
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            self.logger.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 3),
                    "request_id": request_id,
                },
            )


# --- App Setup ---


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create database tables on startup."""
    SQLModel.metadata.create_all(engine)
    yield


app = FastAPI(title="Calculator API", version="0.1.0", lifespan=lifespan)

setup_logging()
app.add_middleware(RequestLoggingMiddleware)

OPERATIONS: dict[str, callable] = {  # type: ignore[type-arg]
    "add": add,
    "sub": subtract,
    "mul": multiply,
    "div": divide,
}


# --- Health Endpoint ---


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check."""
    return {"status": "ok"}


# --- Calculator Endpoints ---


@app.post("/add", response_model=ResultResponse)
def api_add(req: CalculationRequest) -> ResultResponse:
    """Add two numbers."""
    return ResultResponse(result=add(req.a, req.b))


@app.post("/subtract", response_model=ResultResponse)
def api_subtract(req: CalculationRequest) -> ResultResponse:
    """Subtract b from a."""
    return ResultResponse(result=subtract(req.a, req.b))


@app.post("/multiply", response_model=ResultResponse)
def api_multiply(req: CalculationRequest) -> ResultResponse:
    """Multiply two numbers."""
    return ResultResponse(result=multiply(req.a, req.b))


@app.post("/divide", response_model=ResultResponse)
def api_divide(req: CalculationRequest) -> ResultResponse:
    """Divide a by b."""
    try:
        return ResultResponse(result=divide(req.a, req.b))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# --- CRUD Endpoints for Calculations ---


@app.post("/calculations", response_model=CalculationResponse, status_code=201)
def create_calculation(
    req: CalculationCreate, session: Session = Depends(get_session)
) -> Calculation:
    """Create and store a new calculation."""
    if req.operation not in OPERATIONS:
        raise HTTPException(
            status_code=400, detail=f"Unknown operation: {req.operation}. Use: {list(OPERATIONS)}"
        )

    try:
        result = OPERATIONS[req.operation](req.a, req.b)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    calculation = Calculation(operation=req.operation, a=req.a, b=req.b, result=result)
    session.add(calculation)
    session.commit()
    session.refresh(calculation)
    return calculation


@app.get("/calculations", response_model=list[CalculationResponse])
def list_calculations(session: Session = Depends(get_session)) -> list[Calculation]:
    """List all stored calculations."""
    return list(session.exec(select(Calculation).order_by(Calculation.created_at.desc())).all())


@app.get("/calculations/{calculation_id}", response_model=CalculationResponse)
def get_calculation(calculation_id: int, session: Session = Depends(get_session)) -> Calculation:
    """Get a specific calculation by ID."""
    calculation = session.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    return calculation


@app.delete("/calculations/{calculation_id}", status_code=204)
def delete_calculation(calculation_id: int, session: Session = Depends(get_session)) -> None:
    """Delete a calculation by ID."""
    calculation = session.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    session.delete(calculation)
    session.commit()


def main() -> None:
    """Run the server."""
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
