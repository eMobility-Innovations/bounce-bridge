import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import api, ui, auth
from . import database
from .config import BASE_DIR
from .auth import setup_oauth

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting Bounce Bridge...")
    await database.init_db()
    logger.info("Database initialized")
    yield
    # Shutdown
    logger.info("Shutting down Bounce Bridge...")


app = FastAPI(
    title="Bounce Bridge",
    description="Bounce notification bridge for AWS SES, Postal, and Postfix",
    version="1.0.0",
    lifespan=lifespan,
)

# Setup OAuth (must be before routes)
setup_oauth(app)

# Include routers
app.include_router(api.router)
app.include_router(auth.router)
app.include_router(ui.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
