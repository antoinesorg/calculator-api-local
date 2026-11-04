#!/usr/bin/env python3
"""A very simple calculator REST API server."""

from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

import os

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Path, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic import Field as PydanticField
from starlette.exceptions import HTTPException as StarletteHTTPException
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
    a: float = PydanticField(allow_inf_nan=False)
    b: float = PydanticField(allow_inf_nan=False)


class CalculationResponse(CalculationBase):
    """Response model for a calculation."""

    id: int
    created_at: datetime


class CalculationRequest(BaseModel):
    """Request body for calculation endpoints."""

    a: float = PydanticField(allow_inf_nan=False)
    b: float = PydanticField(allow_inf_nan=False)


class ResultResponse(BaseModel):
    """Response body for calculation endpoints."""

    result: float


# --- App Setup ---


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create database tables on startup."""
    SQLModel.metadata.create_all(engine)
    yield


app = FastAPI(title="Calculator API", version="0.1.0", lifespan=lifespan)

OPERATIONS: dict[str, callable] = {  # type: ignore[type-arg]
    "add": add,
    "sub": subtract,
    "mul": multiply,
    "div": divide,
}


# --- Error Handlers ---
# Every error response has the shape {"error": {"code", "message", "details"}}.
# `code` is derived from the HTTP status; unknown operations stay 400 via a
# route-level check, validation failures stay 422.

ERROR_CODES: dict[int, str] = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    422: "validation_error",
}


def error_response(
    status_code: int,
    message: str,
    details: object = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the uniform error body."""
    code = ERROR_CODES.get(status_code, "server_error" if status_code >= 500 else "http_error")
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return 422 with the validation errors in `details`."""
    # `input` and `ctx` are dropped: the input may be NaN/inf (not JSON serializable)
    # and ctx may hold exception objects.
    details = [
        {key: err[key] for key in ("type", "loc", "msg") if key in err} for err in exc.errors()
    ]
    return error_response(422, "Request validation failed", jsonable_encoder(details))


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Wrap HTTPException (including routing 404/405) in the uniform body."""
    return error_response(exc.status_code, str(exc.detail), headers=getattr(exc, "headers", None))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return 500 in the uniform body without leaking internal messages."""
    return error_response(500, "Internal server error")


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
def get_calculation(calculation_id: int = Path(gt=0), session: Session = Depends(get_session)) -> Calculation:
    """Get a specific calculation by ID."""
    calculation = session.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    return calculation


@app.delete("/calculations/{calculation_id}", status_code=204)
def delete_calculation(calculation_id: int = Path(gt=0), session: Session = Depends(get_session)) -> None:
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
