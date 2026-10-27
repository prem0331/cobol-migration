"""Batch pipeline orchestrator for multi-program COBOL migration."""

import os
import json
import time
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from .chain import build_simple_chain, build_batch_chain
from .models import FastAPIOutput, ServiceContract
from .planner import MigrationPlan, MigrationGroup
from ..cobol.extractor import extract_cobol_sections


console = Console()


@dataclass
class BatchResult:
    """Result of a batch migration run."""
    total_programs: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    results: Dict[str, Any] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)
    elapsed_time: float = 0.0


@dataclass
class ProgramMigrationTask:
    """A single program migration task."""
    program_name: str
    source_code: str
    output_dir: Path
    group_name: str
    config: Dict[str, Any] = field(default_factory=dict)


def migrate_single_program(task: ProgramMigrationTask) -> tuple[str, FastAPIOutput | None, str | None]:
    """
    Migrate a single COBOL program.

    Returns:
        Tuple of (program_name, FastAPIOutput or None, error_message or None)
    """
    try:
        # Get service contracts from config (passed from runner)
        service_contracts = task.config.get("service_contracts", [])

        # Use batch chain which knows about service contracts for cross-service calls
        pipeline = build_batch_chain(
            output_dir=str(task.output_dir / "intermediates"),
            model=task.config.get("model"),
            temperature=task.config.get("temperature"),
            max_tokens=task.config.get("max_tokens"),
            analyst_model=task.config.get("analyst_model"),
            analyst_temperature=task.config.get("analyst_temperature"),
            architect_model=task.config.get("architect_model"),
            architect_temperature=task.config.get("architect_temperature"),
            developer_model=task.config.get("developer_model"),
            developer_temperature=task.config.get("developer_temperature"),
            resume=task.config.get("resume", True),
            service_contracts=service_contracts,
        )

        output = pipeline({"cobol": task.source_code})

        # Write generated files
        write_output_files(task.output_dir, output)

        return task.program_name, output, None

    except Exception as e:
        return task.program_name, None, str(e)


def write_output_files(output_dir: Path, fastapi_output: FastAPIOutput) -> None:
    """Write generated FastAPI files to output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "main.py": fastapi_output.main_py,
        "models.py": fastapi_output.models_py,
        "services.py": fastapi_output.services_py,
        "routes.py": fastapi_output.routes_py,
        "requirements.txt": fastapi_output.requirements_txt,
        "README.md": fastapi_output.readme_md,
    }

    for filename, content in files.items():
        if content.strip():
            filepath = output_dir / filename
            filepath.write_text(content, encoding="utf-8")


def validate_generated_code(output_dir: Path) -> bool:
    """Validate generated Python code is syntactically correct."""
    import subprocess
    import sys

    python_files = ["main.py", "models.py", "services.py", "routes.py"]
    all_valid = True

    for filename in python_files:
        filepath = output_dir / filename
        if filepath.exists():
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", str(filepath)],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                all_valid = False

    return all_valid


def run_batch_migration(
    programs: Dict[str, str],
    plan: MigrationPlan,
    output_base: Path,
    config: Dict[str, Any] = None,
    max_workers: int = 3,
) -> BatchResult:
    """
    Run batch migration for all programs in the migration plan.

    Args:
        programs: Dict mapping program_name -> source code
        plan: MigrationPlan with groups
        output_base: Base output directory
        config: Pipeline configuration
        max_workers: Maximum parallel workers

    Returns:
        BatchResult with migration statistics
    """
    if config is None:
        config = {}

    start_time = time.time()
    result = BatchResult()
    result.total_programs = len(programs)

    # Create tasks for each group
    tasks = []
    for group in plan.groups:
        group_dir = output_base / group.name

        # Filter service contracts relevant to this group's programs
        group_programs = set(group.programs)
        group_contracts = [
            c for c in plan.service_contracts
            if c.source_service in group_programs or c.target_service in group_programs
        ]

        # Create config with service contracts for this group
        group_config = {**config, "service_contracts": group_contracts}

        for prog_name in group.programs:
            if prog_name in programs:
                tasks.append(ProgramMigrationTask(
                    program_name=prog_name,
                    source_code=programs[prog_name],
                    output_dir=group_dir,
                    group_name=group.name,
                    config=group_config,
                ))

    # Execute with progress tracking
    completed = 0
    lock = Lock()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task(f"Migrating {len(tasks)} programs...", total=len(tasks))

        # Run sequentially for now (better for LLM rate limits)
        # TODO: Add parallel execution with rate limiting
        for task in tasks:
            progress.update(task_id, description=f"Migrating {task.program_name} ({task.group_name})...")

            prog_name, output, error = migrate_single_program(task)

            with lock:
                if error:
                    result.failed += 1
                    result.errors[prog_name] = error
                    console.print(f"  [red]✗[/red] {prog_name}: {error}")
                else:
                    result.successful += 1
                    result.results[prog_name] = {
                        "group": task.group_name,
                        "output_dir": str(task.output_dir),
                        "validated": validate_generated_code(task.output_dir),
                    }
                    console.print(f"  [green]✓[/green] {prog_name} -> {task.group_name}")

                completed += 1
                progress.update(task_id, advance=1)

    result.elapsed_time = time.time() - start_time

    return result


def run_batch_migration_with_resume(
    programs: Dict[str, str],
    plan: MigrationPlan,
    output_base: Path,
    config: Dict[str, Any] = None,
) -> BatchResult:
    """
    Run batch migration with resume capability.

    Checks for existing output and skips already-migrated programs.
    """
    if config is None:
        config = {}

    start_time = time.time()
    result = BatchResult()
    result.total_programs = len(programs)

    # Check for existing migrations
    for group in plan.groups:
        group_dir = output_base / group.name
        for prog_name in group.programs:
            if prog_name not in programs:
                continue

            # Check if already migrated (has main.py)
            main_py = group_dir / "main.py"
            if main_py.exists():
                result.skipped += 1
                result.results[prog_name] = {
                    "group": group.name,
                    "output_dir": str(group_dir),
                    "skipped": True,
                }
                console.print(f"  [yellow]⊘[/yellow] {prog_name} (already migrated, use --fresh to re-run)")

    # Run migration for non-skipped programs
    remaining_programs = {
        name: code for name, code in programs.items()
        if name not in result.results
    }

    if remaining_programs:
        config["resume"] = True
        remaining_result = run_batch_migration(
            remaining_programs, plan, output_base, config
        )
        result.successful += remaining_result.successful
        result.failed += remaining_result.failed
        result.errors.update(remaining_result.errors)
        result.results.update(remaining_result.results)

    result.elapsed_time = time.time() - start_time
    return result


def generate_shared_models_code(
    plan: MigrationPlan,
    output_base: Path,
    copybook_sources: Dict[str, str],
) -> Dict[str, str]:
    """
    Generate shared Pydantic models from shared copybooks in migration plan.

    Args:
        plan: MigrationPlan with shared_models list
        output_base: Base output directory
        copybook_sources: Dict mapping copybook_name -> source code

    Returns:
        Dict mapping model_name -> model_code
    """
    shared_models = {}

    for shared_model in plan.shared_models:
        model_name = shared_model.name

        # Combine all source copybooks into one analysis input
        combined_copybook = ""
        for cb_name in shared_model.source_copybooks:
            if cb_name in copybook_sources:
                combined_copybook += f"\n* COPYBOOK: {cb_name}\n"
                combined_copybook += copybook_sources[cb_name]

        if not combined_copybook.strip():
            # Fallback placeholder
            model_code = f'''"""Shared model from copybooks: {', '.join(shared_model.source_copybooks)}"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date
from decimal import Decimal


class {model_name}(BaseModel):
    """Shared model generated from copybook(s): {', '.join(shared_model.source_copybooks)}"""
    # TODO: Generate fields from copybook analysis
    pass

'''
        else:
            # Run Architect agent on combined copybook content
            try:
                from .chain import build_simple_chain

                # Create a mini pipeline just for Architect (Analyst + Architect)
                # We need to extract sections from copybook first
                from ..cobol.extractor import extract_cobol_sections
                sections = extract_cobol_sections(combined_copybook)

                # Create input for Analyst
                analyst_input = {
                    "program_id": shared_model.name,
                    "working_storage": sections.working_storage or "(empty)",
                    "procedure_division": "(shared copybook - no procedure division)",
                    "file_section": sections.file_section or "(empty)",
                    "linkage_section": sections.linkage_section or "(empty)",
                }

                # For now, generate a proper model based on copybook analysis
                # In production, this would call the full Analyst+Architect chain
                model_code = _generate_model_from_copybook_sections(shared_model.name, sections)
            except Exception as e:
                console.print(f"[yellow]Warning: Could not generate shared model for {model_name}: {e}[/yellow]")
                model_code = f'''"""Shared model from copybooks: {', '.join(shared_model.source_copybooks)}"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date
from decimal import Decimal


class {model_name}(BaseModel):
    """Shared model generated from copybook(s): {', '.join(shared_model.source_copybooks)}"""
    # Generated from copybook analysis
    pass

'''

        shared_models[model_name] = model_code

    return shared_models


def _generate_model_from_copybook_sections(model_name: str, sections) -> str:
    """Generate a Pydantic model from extracted copybook sections."""
    from ..cobol.parser import parse_working_storage

    fields = []
    if sections.working_storage:
        ws_fields = parse_working_storage(sections.working_storage)
        for field in ws_fields:
            if field.level == 1:  # 01-level group
                # Create model for this group
                field_code = _generate_field_code(field)
                fields.append(field_code)

    if not fields:
        # Fallback
        return f'''"""Shared model from copybook analysis"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date
from decimal import Decimal


class {model_name}(BaseModel):
    """Shared model generated from copybook analysis"""
    pass

'''

    field_str = "\n    ".join(fields)
    return f'''"""Shared model from copybook analysis"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date
from decimal import Decimal


class {model_name}(BaseModel):
    """Shared model generated from copybook analysis"""
    {field_str}

'''


def _generate_field_code(field) -> str:
    """Generate Pydantic field code from a parsed COBOL field."""
    from ..cobol.parser import DataField

    if isinstance(field, DataField):
        if field.children:
            # Group field - create nested model or inline
            child_fields = []
            for child in field.children:
                child_code = _generate_field_code(child)
                child_fields.append(f"    {child_code}")

            if child_fields:
                return f"{field.name}: Optional[Dict] = Field(default=None, description=\"{field.picture or 'Group field'}\")"

    # Elementary field
    py_type = _cobol_type_to_python(field.picture, field.usage)
    default = "None" if field.value is None else f'"{field.value}"'
    occurs = f"List[{py_type}]" if field.occurs and field.occurs > 1 else py_type

    return f"{field.name}: Optional[{occurs}] = Field(default={default}, description=\"{field.picture or ''} {field.usage or ''}\".strip())"


def _cobol_type_to_python(picture: str, usage: str) -> str:
    """Convert COBOL PICTURE/USAGE to Python type."""
    if not picture:
        return "str"

    pic = picture.upper()
    if "COMP-3" in usage.upper() or "PACKED" in usage.upper():
        return "Decimal"
    if "COMP" in usage.upper() or "BINARY" in usage.upper():
        return "int"
    if "V" in pic or "." in pic:
        return "Decimal"
    if pic.startswith("9"):
        return "int"
    return "str"


def write_shared_models(shared_models: Dict[str, str], output_base: Path) -> None:
    """Write shared models to a shared directory."""
    shared_dir = output_base / "shared"
    shared_dir.mkdir(parents=True, exist_ok=True)

    for model_name, code in shared_models.items():
        (shared_dir / f"{model_name.lower()}.py").write_text(code, encoding="utf-8")

    # Create __init__.py
    init_content = '"""Shared models for migrated services."""\n'
    for model_name in shared_models:
        init_content += f"from .{model_name.lower()} import {model_name}\n"
    (shared_dir / "__init__.py").write_text(init_content, encoding="utf-8")


def generate_service_contracts_code(
    plan: MigrationPlan,
    output_base: Path,
) -> None:
    """Generate service contract documentation and OpenAPI specs."""
    contracts_dir = output_base / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)

    # Generate OpenAPI specs and client stubs for each contract
    for contract in plan.service_contracts:
        # Markdown documentation
        contract_doc = f"""# Service Contract: {contract.source_service} -> {contract.target_service}

**Endpoint:** `{contract.method} {contract.endpoint}`

**Request Model:** `{contract.request_model}`

**Response Model:** `{contract.response_model}`

**Description:** {contract.description}

**Generated from CALL:** {contract.source_service} CALLs {contract.target_service}
"""
        (contracts_dir / f"{contract.source_service}_to_{contract.target_service}.md").write_text(
            contract_doc, encoding="utf-8"
        )

        # OpenAPI spec JSON
        openapi_spec = _generate_openapi_for_contract(contract)
        (contracts_dir / f"{contract.source_service}_to_{contract.target_service}_openapi.json").write_text(
            json.dumps(openapi_spec, indent=2), encoding="utf-8"
        )

        # Python client stub
        client_stub = _generate_client_stub(contract)
        (contracts_dir / f"{contract.source_service}_to_{contract.target_service}_client.py").write_text(
            client_stub, encoding="utf-8"
        )

    # Summary
    summary = f"""# Service Contracts Summary

Total contracts: {len(plan.service_contracts)}

## Contracts
"""
    for contract in plan.service_contracts:
        summary += f"- `{contract.source_service}` -> `{contract.target_service}` via `{contract.method} {contract.endpoint}`\n"

    (contracts_dir / "SUMMARY.md").write_text(summary, encoding="utf-8")

    # Combined OpenAPI for all contracts
    combined_openapi = _generate_combined_openapi(plan)
    (contracts_dir / "combined_openapi.json").write_text(
        json.dumps(combined_openapi, indent=2), encoding="utf-8"
    )


def _generate_openapi_for_contract(contract: ServiceContract) -> dict:
    """Generate OpenAPI 3.0 spec for a service contract."""
    return {
        "openapi": "3.0.3",
        "info": {
            "title": f"{contract.source_service} to {contract.target_service} API",
            "version": "1.0.0",
            "description": contract.description,
        },
        "paths": {
            contract.endpoint: {
                contract.method.lower(): {
                    "summary": contract.description,
                    "operationId": f"{contract.source_service.lower()}_to_{contract.target_service.lower()}",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"#/components/schemas/{contract.request_model}"}
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Successful response",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": f"#/components/schemas/{contract.response_model}"}
                                }
                            }
                        },
                        "400": {"description": "Bad Request"},
                        "404": {"description": "Not Found"},
                        "500": {"description": "Internal Server Error"}
                    }
                }
            }
        },
        "components": {
            "schemas": {
                contract.request_model: {
                    "type": "object",
                    "description": f"Request model for {contract.source_service} -> {contract.target_service}"
                },
                contract.response_model: {
                    "type": "object",
                    "description": f"Response model for {contract.source_service} -> {contract.target_service}"
                }
            }
        }
    }


def _generate_client_stub(contract: ServiceContract) -> str:
    """Generate Python client stub for a service contract."""
    method_lower = contract.method.lower()
    client_name = f"{contract.target_service}Client"
    method_name = contract.endpoint.strip("/").replace("/", "_").replace("{", "").replace("}", "")

    return f'''"""
Auto-generated client stub for {contract.source_service} -> {contract.target_service}
Generated from CALL relationship: {contract.source_service} CALLs {contract.target_service}
"""

import httpx
from typing import Dict, Any, Optional
from pydantic import BaseModel


class {contract.request_model}(BaseModel):
    """Request model for {contract.source_service} -> {contract.target_service}"""
    pass


class {contract.response_model}(BaseModel):
    """Response model for {contract.source_service} -> {contract.target_service}"""
    pass


class {client_name}:
    """Client for calling {contract.target_service} from {contract.source_service}"""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def {method_name}(self, request: {contract.request_model}) -> {contract.response_model}:
        """Call {contract.method} {contract.endpoint}"""
        url = f"{{self.base_url}}{contract.endpoint}"
        response = await self._client.{method_lower}(url, json=request.model_dump())
        response.raise_for_status()
        return {contract.response_model}(**response.json())

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


# Sync version for simplicity
class {client_name}Sync:
    """Synchronous client for calling {contract.target_service} from {contract.source_service}"""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def {method_name}(self, request: {contract.request_model}) -> {contract.response_model}:
        """Call {contract.method} {contract.endpoint}"""
        url = f"{{self.base_url}}{contract.endpoint}"
        response = self._client.{method_lower}(url, json=request.model_dump())
        response.raise_for_status()
        return {contract.response_model}(**response.json())

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
'''


def _generate_combined_openapi(plan: MigrationPlan) -> dict:
    """Generate combined OpenAPI spec for all service contracts."""
    paths = {}
    schemas = {}

    for contract in plan.service_contracts:
        paths[contract.endpoint] = {
            contract.method.lower(): {
                "summary": contract.description,
                "operationId": f"{contract.source_service.lower()}_to_{contract.target_service.lower()}",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{contract.request_model}"}
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Successful response",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"#/components/schemas/{contract.response_model}"}
                            }
                        }
                    },
                    "400": {"description": "Bad Request"},
                    "404": {"description": "Not Found"},
                    "500": {"description": "Internal Server Error"}
                }
            }
        }
        schemas[contract.request_model] = {"type": "object", "description": f"Request for {contract.source_service}->{contract.target_service}"}
        schemas[contract.response_model] = {"type": "object", "description": f"Response for {contract.source_service}->{contract.target_service}"}

    return {
        "openapi": "3.0.3",
        "info": {"title": "Migrated COBOL Services API", "version": "1.0.0"},
        "paths": paths,
        "components": {"schemas": schemas}
    }


def print_batch_summary(result: BatchResult, plan: MigrationPlan) -> None:
    """Print a summary of the batch migration results."""
    table = Table(title="Batch Migration Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total Programs", str(result.total_programs))
    table.add_row("Successful", str(result.successful))
    table.add_row("Failed", str(result.failed))
    table.add_row("Skipped", str(result.skipped))
    table.add_row("Elapsed Time", f"{result.elapsed_time:.1f}s")

    console.print(table)

    if result.errors:
        console.print("\n[red]Errors:[/red]")
        for prog, error in result.errors.items():
            console.print(f"  {prog}: {error}")

    if result.results:
        console.print("\n[green]Generated Services:[/green]")
        for prog, info in result.results.items():
            skipped = " (skipped)" if info.get("skipped") else ""
            validated = " ✓" if info.get("validated") else ""
            console.print(f"  {prog} -> {info['group']}{skipped}{validated}")


def save_batch_report(result: BatchResult, plan: MigrationPlan, output_base: Path) -> None:
    """Save batch migration report to JSON."""
    report = {
        "summary": {
            "total_programs": result.total_programs,
            "successful": result.successful,
            "failed": result.failed,
            "skipped": result.skipped,
            "elapsed_time": result.elapsed_time,
        },
        "plan": plan.model_dump(),
        "results": result.results,
        "errors": result.errors,
    }

    report_path = output_base / "migration_report.json"
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    console.print(f"\n[green]Report saved to {report_path}[/green]")