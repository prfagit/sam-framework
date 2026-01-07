"""API route registration helpers."""

from fastapi import FastAPI

from . import agents, auth, health, onboarding, public_agents, secrets, sessions, users


def register_routes(app: FastAPI) -> None:
    """Attach all API routers to the provided FastAPI instance."""

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(onboarding.router)
    # IMPORTANT: public_agents must come BEFORE agents to avoid /{name} matching /public
    app.include_router(public_agents.router)
    app.include_router(agents.router)
    app.include_router(sessions.router)
    app.include_router(users.router)
    app.include_router(secrets.router)


__all__ = ["register_routes"]
