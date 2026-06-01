"""FastAPI routers grouped by domain.

Each module exposes an ``APIRouter`` named ``router`` that app.py mounts via
``include_router``. Routers import their dependencies from the real source
modules so behaviour and patch points live next to the code that uses them.
"""
