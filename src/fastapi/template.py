"""FastAPI code templates for the Developer agent reference."""

FASTAPI_MAIN_TEMPLATE = '''"""
FastAPI Application Entry Point

Generated from COBOL program: {program_name}
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router as api_router
from .services import get_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    service = get_service()
    await service.initialize()
    yield
    # Shutdown
    await service.cleanup()


app = FastAPI(
    title="{program_name} API",
    description="Migrated from COBOL {program_name} program",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {{"status": "healthy", "service": "{program_name}"}}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''

FASTAPI_MODELS_TEMPLATE = '''"""
Pydantic Models

Generated from COBOL program: {program_name}
"""
from pydantic import BaseModel, Field, ConfigDict
from decimal import Decimal
from typing import Optional, List
from enum import Enum
from datetime import date, datetime


{enums}

{models}

# Request/Response models
class BaseResponse(BaseModel):
    """Base response model."""
    success: bool = True
    message: Optional[str] = None


class ErrorResponse(BaseModel):
    """Error response model."""
    success: bool = False
    error: str
    detail: Optional[str] = None


class PaginatedResponse(BaseModel):
    """Paginated list response."""
    items: List[dict]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool
'''

FASTAPI_SERVICE_TEMPLATE = '''"""
Business Logic Service Layer

Generated from COBOL program: {program_name}
"""
from typing import Optional, List, Dict, Any
from decimal import Decimal
from contextlib import asynccontextmanager

from .models import *


class {service_name}:
    """Service implementing business logic from COBOL {program_name}."""

    def __init__(self):
        self._data_store: Dict[str, Any] = {{}}
        self._initialized = False

    async def initialize(self):
        """Initialize service (load data, connect to DB, etc.)."""
        if not self._initialized:
            # TODO: Replace with actual data source (database, file, etc.)
            self._load_sample_data()
            self._initialized = True

    async def cleanup(self):
        """Cleanup resources."""
        pass

    def _load_sample_data(self):
        """Load sample data for testing."""
        # This would be replaced with actual data loading logic
        pass

    # ---- CRUD Operations ----

    async def get_by_id(self, id: str) -> Optional[dict]:
        """Get record by ID (equivalent to COBOL lookup)."""
        return self._data_store.get(id)

    async def create(self, data: dict) -> dict:
        """Create new record."""
        id = data.get("id") or data.get("cust_id") or str(len(self._data_store) + 1)
        self._data_store[id] = data
        return data

    async def update(self, id: str, data: dict) -> Optional[dict]:
        """Update existing record."""
        if id in self._data_store:
            self._data_store[id].update(data)
            return self._data_store[id]
        return None

    async def delete(self, id: str) -> bool:
        """Delete record."""
        if id in self._data_store:
            del self._data_store[id]
            return True
        return False

    async def list_all(
        self,
        page: int = 1,
        page_size: int = 20,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """List records with pagination."""
        items = list(self._data_store.values())

        # Apply filters
        if filters:
            for key, value in filters.items():
                items = [item for item in items if item.get(key) == value]

        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size

        return {{
            "items": items[start:end],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_next": end < total,
            "has_prev": page > 1,
        }}

    # ---- Business Logic Methods (from COBOL paragraphs) ----

{business_methods}


# Dependency injection
_service_instance: Optional[{service_name}] = None


def get_service() -> {service_name}:
    """Get or create service instance (singleton)."""
    global _service_instance
    if _service_instance is None:
        _service_instance = {service_name}()
    return _service_instance
'''

FASTAPI_ROUTES_TEMPLATE = '''"""
API Routes

Generated from COBOL program: {program_name}
"""
from fastapi import APIRouter, HTTPException, Query, Depends, status
from typing import Optional, List, Dict, Any

from .models import *
from .services import get_service, {service_name}


router = APIRouter(prefix="/{resource_name}", tags=["{resource_name}"])


@router.get("/{{item_id}}", response_model=dict)
async def get_item(
    item_id: str,
    service: {service_name} = Depends(get_service)
):
    """Get item by ID."""
    item = await service.get_by_id(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_item(
    item: dict,
    service: {service_name} = Depends(get_service)
):
    """Create new item."""
    return await service.create(item)


@router.get("", response_model=dict)
async def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: {service_name} = Depends(get_service)
):
    """List items with pagination."""
    return await service.list_all(page=page, page_size=page_size)


@router.put("/{{item_id}}", response_model=dict)
async def update_item(
    item_id: str,
    item: dict,
    service: {service_name} = Depends(get_service)
):
    """Update item."""
    updated = await service.update(item_id, item)
    if not updated:
        raise HTTPException(status_code=404, detail="Item not found")
    return updated


@router.delete("/{{item_id}}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: str,
    service: {service_name} = Depends(get_service)
):
    """Delete item."""
    deleted = await service.delete(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found")


# Additional endpoints for specific business logic
{business_endpoints}
'''

REQUIREMENTS_TEMPLATE = '''fastapi>=0.109.0
uvicorn[standard]>=0.27.0
pydantic>=2.6.0
pydantic-settings>=2.2.0
python-dotenv>=1.0.0
python-multipart>=0.0.6
# Database (choose one)
# asyncpg>=0.29.0  # PostgreSQL
# aiomysql>=0.2.0  # MySQL
# aiosqlite>=0.19.0  # SQLite
'''

README_TEMPLATE = '''# {program_name} API

FastAPI microservice migrated from COBOL program `{program_name}`.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn main:app --reload

# Run production server
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

## API Documentation

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/v1/{resource_name}/{item_id} | Get item by ID |
| POST | /api/v1/{resource_name} | Create new item |
| GET | /api/v1/{resource_name} | List items (paginated) |
| PUT | /api/v1/{resource_name}/{item_id} | Update item |
| DELETE | /api/v1/{resource_name}/{item_id} | Delete item |

## Business Logic

This API implements the following COBOL paragraphs as service methods:

{business_logic_summary}

## Data Models

See `models.py` for Pydantic model definitions.

## Configuration

Environment variables (`.env`):

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/dbname

# Application
DEBUG=false
LOG_LEVEL=INFO
```

## Testing

```bash
pytest tests/
```
'''