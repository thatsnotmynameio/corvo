from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from corvo.config import get_settings
from corvo.db import create_engine, create_sessionmaker
from corvo.exceptions import ConflictError, CorvoError, NotFoundError

# The HTTP status of each business error, the most specific class first. Any
# other CorvoError is a bad request.
ERROR_STATUS: dict[type[CorvoError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
}


async def corvo_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, CorvoError)
    status_code = next(
        (code for cls, code in ERROR_STATUS.items() if isinstance(exc, cls)),
        status.HTTP_400_BAD_REQUEST,
    )
    return JSONResponse(
        status_code=status_code,
        content={"error": type(exc).__name__, "detail": str(exc)},
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # The connection pool lives as long as the app.
    engine = create_engine(str(get_settings().database_url))
    app.state.sessionmaker = create_sessionmaker(engine)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="corvo", debug=get_settings().debug, lifespan=lifespan)
    app.add_exception_handler(CorvoError, corvo_error_handler)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
