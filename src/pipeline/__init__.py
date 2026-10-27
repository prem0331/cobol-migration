"""Pipeline package for COBOL to FastAPI migration."""

from .models import BusinessRules, PydanticSchema, FastAPIOutput, DataField, BusinessRule, IOOperation
from .prompts import ANALYST_PROMPT, ARCHITECT_PROMPT, DEVELOPER_PROMPT
from .parsers import parse_business_rules, parse_pydantic_schema, parse_fastapi_output
from .chain import build_pipeline_chain
from .runner import run_pipeline
from .system_graph import (
    DependencyGraph,
    ProgramNode,
    CopybookNode,
    FileNode,
    DependencyEdge,
    EdgeType,
    build_system_graph,
)
from .planner import (
    MigrationPlan,
    MigrationGroup,
    MigrationStrategy,
    ServiceBoundary,
    SharedModel,
    ServiceContract,
    create_migration_plan,
    save_migration_plan,
    load_migration_plan,
    analyze_coupling,
    recommend_groups,
)
from .batch_runner import (
    run_batch_migration,
    run_batch_migration_with_resume,
    BatchResult,
    generate_shared_models_code,
    generate_service_contracts_code,
    print_batch_summary,
    save_batch_report,
)

__all__ = [
    "BusinessRules",
    "PydanticSchema",
    "FastAPIOutput",
    "DataField",
    "BusinessRule",
    "IOOperation",
    "ANALYST_PROMPT",
    "ARCHITECT_PROMPT",
    "DEVELOPER_PROMPT",
    "parse_business_rules",
    "parse_pydantic_schema",
    "parse_fastapi_output",
    "build_pipeline_chain",
    "run_pipeline",
    "DependencyGraph",
    "ProgramNode",
    "CopybookNode",
    "FileNode",
    "DependencyEdge",
    "EdgeType",
    "build_system_graph",
    "MigrationPlan",
    "MigrationGroup",
    "MigrationStrategy",
    "ServiceBoundary",
    "SharedModel",
    "ServiceContract",
    "create_migration_plan",
    "save_migration_plan",
    "load_migration_plan",
    "analyze_coupling",
    "recommend_groups",
    "run_batch_migration",
    "run_batch_migration_with_resume",
    "BatchResult",
    "generate_shared_models_code",
    "generate_service_contracts_code",
    "print_batch_summary",
    "save_batch_report",
]