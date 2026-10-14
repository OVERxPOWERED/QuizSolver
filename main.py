"""Universal AI Assessment & Coding Solver - FastAPI Application Entry Point."""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
import uvicorn

from config import config
from core.database import DatabaseManager
from core.browser import BrowserManager
from core.ai_solver import AISolver
from src.api.routes import router as api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown."""
    # Startup
    log.info("Starting application initialization...")
    
    # Initialize DatabaseManager
    db_manager = DatabaseManager()
    await db_manager.connect()
    app.state.db = db_manager
    log.info("Database connection established")
    
    # Initialize BrowserManager (verify playwright)
    browser_manager = BrowserManager(headless=config.HEADLESS)
    await browser_manager.start()
    app.state.browser = browser_manager
    log.info("Browser manager initialized")
    
    # Initialize AISolver (validate config)
    ai_solver = AISolver()
    ai_solver.validate_config()
    app.state.ai_solver = ai_solver
    log.info("AI solver validated and ready")
    
    log.info("Application startup complete")
    
    yield
    
    # Shutdown
    log.info("Starting application shutdown...")
    
    # Close database pool
    if hasattr(app.state, 'db') and app.state.db:
        await app.state.db.close()
        log.info("Database connection closed")
    
    # Stop playwright/browser
    if hasattr(app.state, 'browser') and app.state.browser:
        await app.state.browser.stop()
        log.info("Browser manager stopped")
    
    log.info("Application shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Universal AI Assessment & Coding Solver",
        description="API for autonomous quiz, form, and coding challenge solving",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    
    # Include API router
    app.include_router(api_router, prefix="/api/v1")
    
    # Root endpoint redirect to docs
    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/docs")
    
    # Health check endpoint
    @app.get("/health", include_in_schema=False)
    async def health_check():
        return {"status": "healthy", "service": "universal-ai-solver"}
    
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=config.API_RELOAD,
        workers=config.API_WORKERS,
        log_level=config.LOG_LEVEL.lower(),
    )