"""CLI entry point for the COBOL to FastAPI migration pipeline."""

import os
import sys
import json
from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.table import Table
from dotenv import load_dotenv

from .chain import build_simple_chain
from .models import FastAPIOutput
from .frontend_chain import run_frontend_generation, write_frontend_files
from ..cobol.extractor import extract_cobol_sections
from ..cobol.discovery import discover_all, filter_cobol_programs
from .system_graph import build_system_graph, DependencyGraph
from .planner import (
    create_migration_plan,
    save_migration_plan,
    load_migration_plan,
    MigrationStrategy,
)
from .batch_runner import (
    run_batch_migration_with_resume,
    print_batch_summary,
    save_batch_report,
)

app = typer.Typer(
    name="cobol2fastapi",
    help="COBOL to FastAPI Migration Pipeline",
    add_completion=False,
)
console = Console()


def run_pipeline(cobol_source: str, output_dir: Optional[str] = None, **kwargs) -> FastAPIOutput:
    """
    Run the migration pipeline on COBOL source.

    Args:
        cobol_source: COBOL source code string
        output_dir: Optional directory to save intermediate outputs
        **kwargs: Additional arguments passed to build_simple_chain

    Returns:
        FastAPIOutput with generated application code
    """
    pipeline = build_simple_chain(output_dir=output_dir, **kwargs)
    return pipeline({"cobol": cobol_source})


def load_environment(env_file: Optional[str] = None) -> None:
    """Load environment variables from .env file."""
    if env_file:
        load_dotenv(env_file)
    else:
        # Try default locations
        for env_path in [".env", ".env.local", "../.env"]:
            if Path(env_path).exists():
                load_dotenv(env_path)
                break


def read_cobol_file(filepath: str) -> str:
    """Read COBOL source file."""
    path = Path(filepath)
    if not path.exists():
        console.print(f"[red]Error: File not found: {filepath}[/red]")
        sys.exit(1)

    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Try other encodings common in legacy systems
        for encoding in ["cp1252", "latin-1", "iso-8859-1"]:
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        console.print(f"[red]Error: Could not decode file: {filepath}[/red]")
        sys.exit(1)


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
            console.print(f"  [green]✓[/green] Written: {filepath}")


def validate_generated_code(output_dir: Path) -> bool:
    """Validate generated Python code is syntactically correct."""
    import subprocess

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
            if result.returncode == 0:
                console.print(f"  [green]✓[/green] Syntax OK: {filename}")
            else:
                console.print(f"  [red]✗[/red] Syntax error in {filename}:")
                console.print(f"    {result.stderr.strip()}")
                all_valid = False

    return all_valid


@app.command()
def migrate(
    input_file: str = typer.Argument(..., help="Path to COBOL source file (.cbl, .cob, .cobol)"),
    output_dir: str = typer.Option("./output", "-o", "--output", help="Output directory for generated FastAPI app"),
    env_file: Optional[str] = typer.Option(None, "-e", "--env", help="Path to .env file with GEMINI_API_KEY"),
    # Global defaults
    model: Optional[str] = typer.Option(None, "-m", "--model", help="Default Gemini model for all agents (overrides .env)"),
    temperature: Optional[float] = typer.Option(None, "-t", "--temperature", help="Default temperature for all agents (0.0-1.0)"),
    max_tokens: Optional[int] = typer.Option(None, "--max-tokens", help="Default max tokens per response"),
    # Agent-specific overrides (multi-provider support)
    analyst_model: Optional[str] = typer.Option(None, "--analyst-model", help="Model for Agent 1 (Analyst) - fast extraction"),
    analyst_temperature: Optional[float] = typer.Option(None, "--analyst-temp", help="Temperature for Analyst"),
    architect_model: Optional[str] = typer.Option(None, "--architect-model", help="Model for Agent 2 (Architect) - schema design"),
    architect_temperature: Optional[float] = typer.Option(None, "--architect-temp", help="Temperature for Architect"),
    developer_model: Optional[str] = typer.Option(None, "--developer-model", help="Model for Agent 3 (Developer) - code gen"),
    developer_temperature: Optional[float] = typer.Option(None, "--developer-temp", help="Temperature for Developer"),
    save_intermediates: bool = typer.Option(True, "--save-intermediates/--no-save-intermediates", help="Save intermediate JSON outputs"),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate generated Python syntax"),
    resume: bool = typer.Option(True, "--resume/--fresh", help="Resume from intermediates or start fresh"),
):
    """
    Migrate a COBOL file to a FastAPI microservice using the 3-agent pipeline.

    Example:
        cobol2fastapi migrate examples/sample.cbl -o ./my-api
        cobol2fastapi migrate examples/sample.cbl -o ./my-api --fresh  # Force fresh run
        cobol2fastapi migrate examples/sample.cbl -o ./my-api \
            --analyst-model gemini-2.5-flash \
            --architect-model gemini-2.5-pro \
            --developer-model gemini-2.5-pro
    """
    # Load environment
    load_environment(env_file)

    # Check API key
    if not os.getenv("GEMINI_API_KEY"):
        console.print("[red]Error: GEMINI_API_KEY not found in environment[/red]")
        console.print("Create a .env file with your Gemini API key (see .env.example)")
        sys.exit(1)

    # Read COBOL source
    console.print(Panel.fit(
        f"[bold]COBOL to FastAPI Migration Pipeline[/bold]\n"
        f"Input: {input_file}\n"
        f"Output: {output_dir}",
        border_style="blue"
    ))

    with console.status("[bold green]Reading COBOL source..."):
        cobol_source = read_cobol_file(input_file)

    # Show extracted sections preview
    sections = extract_cobol_sections(cobol_source)
    console.print(f"\n[bold]Extracted Sections:[/bold]")
    console.print(f"  Program ID: [cyan]{sections.program_id}[/cyan]")
    console.print(f"  Working-Storage: [cyan]{len(sections.working_storage)}[/cyan] chars")
    console.print(f"  Procedure Division: [cyan]{len(sections.procedure_division)}[/cyan] chars")

    # Build and run pipeline
    output_path = Path(output_dir)
    intermediates_dir = output_path / "intermediates" if save_intermediates else None

    pipeline = build_simple_chain(
        output_dir=str(intermediates_dir) if intermediates_dir else None,
        # Global defaults
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        # Agent-specific overrides
        analyst_model=analyst_model,
        analyst_temperature=analyst_temperature,
        architect_model=architect_model,
        architect_temperature=architect_temperature,
        developer_model=developer_model,
        developer_temperature=developer_temperature,
        resume=resume,
    )

    console.print("\n[bold]Running 3-Agent Pipeline...[/bold]\n")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Executing pipeline...", total=None)
            fastapi_output = pipeline({"cobol": cobol_source})
            progress.update(task, completed=True)

    except Exception as e:
        console.print(f"\n[red]Pipeline failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Write output files
    console.print("\n[bold]Writing generated files...[/bold]")
    write_output_files(output_path, fastapi_output)

    # Validate syntax
    if validate:
        console.print("\n[bold]Validating generated code...[/bold]")
        if validate_generated_code(output_path):
            console.print("[green]All files passed syntax validation![/green]")
        else:
            console.print("[yellow]Some files have syntax errors - check output[/yellow]")

    # Summary
    console.print(Panel.fit(
        f"[bold green]Migration Complete![/bold green]\n\n"
        f"Generated FastAPI application in: [cyan]{output_path}[/cyan]\n\n"
        f"To run the service:\n"
        f"  cd {output_path}\n"
        f"  pip install -r requirements.txt\n"
        f"  uvicorn main:app --reload\n\n"
        f"API docs will be at: http://localhost:8000/docs",
        border_style="green"
    ))


@app.command()
def preview(
    input_file: str = typer.Argument(..., help="Path to COBOL source file"),
    env_file: Optional[str] = typer.Option(None, "-e", "--env", help="Path to .env file"),
):
    """Preview extracted COBOL sections without running the full pipeline."""
    load_environment(env_file)

    cobol_source = read_cobol_file(input_file)
    sections = extract_cobol_sections(cobol_source)

    console.print(Panel.fit(
        f"[bold]COBOL Preview: {sections.program_id}[/bold]",
        border_style="blue"
    ))

    for section_name, content in [
        ("WORKING-STORAGE", sections.working_storage),
        ("PROCEDURE DIVISION", sections.procedure_division),
        ("FILE SECTION", sections.file_section),
        ("LINKAGE SECTION", sections.linkage_section),
    ]:
        if content.strip():
            console.print(f"\n[bold]{section_name}:[/bold]")
            syntax = Syntax(content[:2000], "cobol", theme="monokai", line_numbers=True)
            console.print(syntax)
            if len(content) > 2000:
                console.print(f"  ... ({len(content) - 2000} more characters)")
        else:
            console.print(f"\n[bold]{section_name}:[/bold] [dim](empty)[/dim]")


@app.command()
def test_gemini(
    model: Optional[str] = typer.Option(None, "-m", "--model", help="Model to test"),
    prompt: str = typer.Option("Hello, respond with 'OK' only.", "-p", "--prompt", help="Test prompt"),
):
    """Test Gemini API connectivity."""
    load_environment()

    if not os.getenv("GEMINI_API_KEY"):
        console.print("[red]Error: GEMINI_API_KEY not found[/red]")
        sys.exit(1)

    from langchain_google_genai import ChatGoogleGenerativeAI

    llm = ChatGoogleGenerativeAI(
        model=model or os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
        google_api_key=os.getenv("GEMINI_API_KEY"),
    )

    console.print(f"Testing Gemini API with model: {llm.model}")

    try:
        response = llm.invoke(prompt)
        console.print(f"[green]Success![/green] Response: {response.content[:200]}")
    except Exception as e:
        console.print(f"[red]Failed: {e}[/red]")
        sys.exit(1)


@app.command()
def status(
    output_dir: str = typer.Argument("./output", help="Output directory to check"),
):
    """Check pipeline state from intermediate files."""
    from pathlib import Path
    import json
    from datetime import datetime

    intermediates_dir = Path(output_dir) / "intermediates"
    if not intermediates_dir.exists():
        console.print(f"[yellow]No intermediates directory found at {intermediates_dir}[/yellow]")
        return

    console.print(Panel.fit(
        f"[bold]Pipeline Status: {output_dir}[/bold]",
        border_style="blue"
    ))

    stages = [
        ("01_extracted_sections", "Section Extraction"),
        ("02_business_rules", "Agent 1: Analyst (Business Rules)"),
        ("03_pydantic_schema", "Agent 2: Architect (Pydantic Schema)"),
        ("04_fastapi_output", "Agent 3: Developer (FastAPI App)"),
    ]

    for prefix, label in stages:
        pattern = str(intermediates_dir / f"{prefix}_*.json")
        files = list(Path(intermediates_dir).glob(f"{prefix}_*.json"))
        if files:
            latest = max(files, key=lambda f: f.stat().st_mtime)
            mtime = datetime.fromtimestamp(latest.stat().st_mtime)
            size = latest.stat().st_size
            console.print(f"  [green]✓[/green] {label}: {latest.name} ({size} bytes, {mtime.strftime('%Y-%m-%d %H:%M:%S')})")
        else:
            console.print(f"  [red]✗[/red] {label}: Not found")


@app.command()
def clear_intermediates(
    output_dir: str = typer.Argument("./output", help="Output directory"),
    confirm: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation"),
):
    """Delete all intermediate files to force fresh pipeline run."""
    from pathlib import Path

    intermediates_dir = Path(output_dir) / "intermediates"
    if not intermediates_dir.exists():
        console.print(f"[yellow]No intermediates directory found at {intermediates_dir}[/yellow]")
        return

    files = list(intermediates_dir.glob("*.json"))
    if not files:
        console.print("[yellow]No intermediate files to clear[/yellow]")
        return

    if not confirm:
        console.print(f"Found {len(files)} intermediate files in {intermediates_dir}")
        if not typer.confirm("Delete all intermediate files?"):
            console.print("Cancelled")
            return

    for f in files:
        f.unlink()
        console.print(f"  [red]Deleted[/red] {f.name}")

    console.print("[green]All intermediate files cleared[/green]")


@app.command()
def discover(
    source_dir: str = typer.Argument(".", help="Directory to scan for COBOL files"),
    copybook_dirs: Optional[str] = typer.Option(None, "--copybook-dirs", "-c", help="Comma-separated copybook directories"),
):
    """Discover COBOL files and copybooks in a directory."""
    load_environment()

    copybook_paths = []
    if copybook_dirs:
        copybook_paths = [p.strip() for p in copybook_dirs.split(",")]

    console.print(Panel.fit(
        f"[bold]COBOL Discovery[/bold]\n"
        f"Source: {source_dir}\n"
        f"Copybook dirs: {copybook_paths or 'auto'}",
        border_style="blue"
    ))

    with console.status("Scanning..."):
        inventory = discover_all(source_dir, copybook_paths)

    files = inventory.get('files', [])
    copybooks = inventory.get('copybooks', {})

    console.print(f"\n[bold]Found {len(files)} COBOL programs:[/bold]")
    table = Table()
    table.add_column("Program ID", style="cyan")
    table.add_column("File", style="green")

    for prog in files:
        table.add_row(prog.program_id or "UNKNOWN", prog.path)

    console.print(table)

    console.print(f"\n[bold]Found {len(copybooks)} copybooks:[/bold]")
    for cb in copybooks.values():
        console.print(f"  [cyan]{cb.name}[/cyan] -> {cb.path}")


@app.command()
def graph(
    source_dir: str = typer.Argument(".", help="Directory with COBOL files"),
    output: str = typer.Option("./dependency-graph.json", "-o", "--output", help="Output JSON file"),
    copybook_dirs: Optional[str] = typer.Option(None, "--copybook-dirs", "-c", help="Comma-separated copybook directories"),
    format: str = typer.Option("json", "--format", "-f", help="Output format: json, summary, mermaid, neo4j"),
):
    """Build and display system dependency graph."""
    load_environment()

    copybook_paths = []
    if copybook_dirs:
        copybook_paths = [p.strip() for p in copybook_dirs.split(",")]

    # Discover programs
    inventory = discover_all(source_dir, copybook_paths)
    programs = filter_cobol_programs(inventory['files'])

    # Read source code
    program_sources = {}
    for prog in programs:
        program_sources[prog.program_id] = Path(prog.path).read_text(encoding="utf-8")

    # Build graph
    console.print(f"Building dependency graph for {len(program_sources)} programs...")
    graph = build_system_graph(program_sources, copybook_paths)

    if format == "summary":
        # Print summary
        console.print(Panel.fit(
            f"[bold]Dependency Graph Summary[/bold]\n"
            f"Programs: {len(graph.programs)}\n"
            f"Copybooks: {len(graph.copybooks)}\n"
            f"Files: {len(graph.files)}\n"
            f"Edges: {len(graph.edges)}",
            border_style="green"
        ))

        console.print("\n[bold]Entry Points:[/bold]")
        for ep in graph.get_entry_points():
            console.print(f"  {ep}")

        console.print("\n[bold]Leaf Programs:[/bold]")
        for lp in graph.get_leaf_programs():
            console.print(f"  {lp}")

        cycles = graph.find_circular_calls()
        if cycles:
            console.print("\n[red]Circular Dependencies:[/red]")
            for cycle in cycles:
                console.print(f"  {' -> '.join(cycle)}")

        # Unresolved dynamic calls
        unresolved = []
        for prog_node in graph.programs.values():
            for dyn in prog_node.unresolved_dynamic_calls:
                unresolved.append(f"{prog_node.name}: {dyn['variable']} at {dyn['paragraph']}:{dyn['line_number']}")
        if unresolved:
            console.print("\n[yellow]Unresolved Dynamic CALLs:[/yellow]")
            for u in unresolved:
                console.print(f"  {u}")
    elif format == "mermaid":
        # Output Mermaid diagram
        mermaid = graph.to_mermaid()
        if output.endswith(".mmd") or output.endswith(".mermaid"):
            Path(output).write_text(mermaid, encoding="utf-8")
            console.print(f"[green]Mermaid diagram saved to {output}[/green]")
        else:
            console.print(mermaid)
    elif format == "neo4j":
        # Output Neo4j Cypher
        cypher = graph.to_neo4j_cypher()
        if output.endswith(".cypher") or output.endswith(".cql"):
            Path(output).write_text(cypher, encoding="utf-8")
            console.print(f"[green]Neo4j Cypher saved to {output}[/green]")
        else:
            console.print(cypher)
    else:
        # Save full JSON
        graph.serialize(output)
        console.print(f"[green]Graph saved to {output}[/green]")


@app.command()
def plan(
    source_dir: str = typer.Argument(".", help="Directory with COBOL files"),
    output: str = typer.Option("./migration-plan.json", "-o", "--output", help="Output JSON file"),
    copybook_dirs: Optional[str] = typer.Option(None, "--copybook-dirs", "-c", help="Comma-separated copybook directories"),
    strategy: str = typer.Option("grouped", "--strategy", "-s", help="Migration strategy: independent, grouped, hybrid"),
    max_group_size: int = typer.Option(5, "--max-group-size", help="Maximum programs per group"),
):
    """Generate migration plan from COBOL codebase."""
    load_environment()

    copybook_paths = []
    if copybook_dirs:
        copybook_paths = [p.strip() for p in copybook_dirs.split(",")]

    # Discover programs
    inventory = discover_all(source_dir, copybook_paths)
    programs = filter_cobol_programs(inventory['files'])

    # Read source code
    program_sources = {}
    for prog in programs:
        program_sources[prog.program_id] = Path(prog.path).read_text(encoding="utf-8")

    # Build graph and plan
    console.print(f"Analyzing {len(program_sources)} programs...")
    graph = build_system_graph(program_sources, copybook_paths)

    mig_strategy = MigrationStrategy(strategy)
    plan = create_migration_plan(graph, mig_strategy, max_group_size)

    # Save plan
    save_migration_plan(plan, output)
    console.print(f"[green]Migration plan saved to {output}[/green]")

    # Print summary
    console.print(Panel.fit(
        f"[bold]Migration Plan[/bold]\n"
        f"Strategy: {plan.strategy.value}\n"
        f"Groups: {len(plan.groups)}\n"
        f"Shared Models: {len(plan.shared_models)}\n"
        f"Service Contracts: {len(plan.service_contracts)}\n"
        f"Unresolved: {len(plan.unresolved)}",
        border_style="green"
    ))

    console.print("\n[bold]Groups:[/bold]")
    for group in plan.groups:
        console.print(f"  [cyan]{group.name}[/cyan]: {', '.join(group.programs)}")
        if group.shared_copybooks:
            console.print(f"    Shared copybooks: {', '.join(group.shared_copybooks)}")
        if group.shared_files:
            console.print(f"    Shared files: {', '.join(group.shared_files)}")

    if plan.unresolved:
        console.print("\n[yellow]Unresolved Items:[/yellow]")
        for u in plan.unresolved:
            console.print(f"  - {u}")


@app.command()
def batch(
    source_dir: str = typer.Argument(".", help="Directory with COBOL files"),
    output: str = typer.Option("./batch-output", "-o", "--output", help="Output base directory"),
    copybook_dirs: Optional[str] = typer.Option(None, "--copybook-dirs", "-c", help="Comma-separated copybook directories"),
    strategy: str = typer.Option("grouped", "--strategy", "-s", help="Migration strategy: independent, grouped, hybrid"),
    max_group_size: int = typer.Option(5, "--max-group-size", help="Maximum programs per group"),
    plan_file: Optional[str] = typer.Option(None, "--plan", "-p", help="Use existing migration plan file"),
    fresh: bool = typer.Option(False, "--fresh", help="Force fresh migration (ignore existing)"),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate generated code"),
    # Global defaults
    model: Optional[str] = typer.Option(None, "-m", "--model", help="Default Gemini model for all agents"),
    temperature: Optional[float] = typer.Option(None, "-t", "--temperature", help="Default temperature for all agents"),
    max_tokens: Optional[int] = typer.Option(None, "--max-tokens", help="Default max tokens per response"),
    # Agent-specific overrides
    analyst_model: Optional[str] = typer.Option(None, "--analyst-model", help="Model for Agent 1 (Analyst)"),
    analyst_temperature: Optional[float] = typer.Option(None, "--analyst-temp", help="Temperature for Analyst"),
    architect_model: Optional[str] = typer.Option(None, "--architect-model", help="Model for Agent 2 (Architect)"),
    architect_temperature: Optional[float] = typer.Option(None, "--architect-temp", help="Temperature for Architect"),
    developer_model: Optional[str] = typer.Option(None, "--developer-model", help="Model for Agent 3 (Developer)"),
    developer_temperature: Optional[float] = typer.Option(None, "--developer-temp", help="Temperature for Developer"),
):
    """Run batch migration for multiple COBOL programs."""
    load_environment()

    if not os.getenv("GEMINI_API_KEY"):
        console.print("[red]Error: GEMINI_API_KEY not found in environment[/red]")
        sys.exit(1)

    copybook_paths = []
    if copybook_dirs:
        copybook_paths = [p.strip() for p in copybook_dirs.split(",")]

    # Discover programs
    inventory = discover_all(source_dir, copybook_paths)
    programs = filter_cobol_programs(inventory['files'])

    # Read source code
    program_sources = {}
    for prog in programs:
        program_sources[prog.program_id] = Path(prog.path).read_text(encoding="utf-8")

    console.print(Panel.fit(
        f"[bold]Batch Migration[/bold]\n"
        f"Programs: {len(program_sources)}\n"
        f"Output: {output}\n"
        f"Strategy: {strategy}",
        border_style="blue"
    ))

    # Load or create plan
    output_path = Path(output)
    if plan_file and Path(plan_file).exists():
        plan = load_migration_plan(plan_file)
        console.print(f"[green]Loaded plan from {plan_file}[/green]")
    else:
        console.print("Building dependency graph and creating plan...")
        graph = build_system_graph(program_sources, copybook_paths)
        mig_strategy = MigrationStrategy(strategy)
        plan = create_migration_plan(graph, mig_strategy, max_group_size)

        # Ensure output directory exists
        output_path.mkdir(parents=True, exist_ok=True)

        # Save plan for reference
        plan_path = output_path / "migration-plan.json"
        save_migration_plan(plan, str(plan_path))
        console.print(f"[green]Plan saved to {plan_path}[/green]")

    # Configure pipeline
    config = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "analyst_model": analyst_model,
        "analyst_temperature": analyst_temperature,
        "architect_model": architect_model,
        "architect_temperature": architect_temperature,
        "developer_model": developer_model,
        "developer_temperature": developer_temperature,
        "resume": not fresh,
    }

    # Load copybook sources for shared model generation
    copybook_sources = {}
    for cb_path in copybook_paths:
        cb_dir = Path(cb_path)
        if cb_dir.exists():
            for cb_file in cb_dir.glob("*.cpy"):
                copybook_sources[cb_file.stem] = cb_file.read_text(encoding="utf-8")
            for cb_file in cb_dir.glob("*.copy"):
                copybook_sources[cb_file.stem] = cb_file.read_text(encoding="utf-8")
            for cb_file in cb_dir.glob("*.cbl"):
                copybook_sources[cb_file.stem] = cb_file.read_text(encoding="utf-8")

    # Run batch migration
    console.print(f"\n[bold]Starting batch migration ({'fresh' if fresh else 'resume'} mode)...[/bold]\n")
    result = run_batch_migration_with_resume(program_sources, plan, output_path, config)

    # Generate shared models
    from .batch_runner import generate_shared_models_code, write_shared_models, generate_service_contracts_code
    shared_models = generate_shared_models_code(plan, output_path, copybook_sources)
    if shared_models:
        write_shared_models(shared_models, output_path)
        console.print(f"[green]Generated {len(shared_models)} shared models[/green]")

    # Generate service contracts
    generate_service_contracts_code(plan, output_path)
    console.print(f"[green]Generated service contracts[/green]")

    # Print summary
    print_batch_summary(result, plan)

    # Save report
    save_batch_report(result, plan, output_path)

    # Validate if requested
    if validate:
        console.print("\n[bold]Validating generated code...[/bold]")
        all_valid = True
        for group in plan.groups:
            group_dir = output_path / group.name
            if not validate_generated_code(group_dir):
                all_valid = False
                console.print(f"  [red]✗[/red] {group.name} has syntax errors")
            else:
                console.print(f"  [green]✓[/green] {group.name} syntax OK")

        if all_valid:
            console.print("[green]All services passed syntax validation![/green]")
        else:
            console.print("[yellow]Some services have syntax errors[/yellow]")


@app.command()
def status(
    output_dir: str = typer.Argument("./output", help="Output directory to check"),
):
    """Check pipeline state from intermediate files."""
    from pathlib import Path
    import json
    from datetime import datetime

    intermediates_dir = Path(output_dir) / "intermediates"
    if not intermediates_dir.exists():
        console.print(f"[yellow]No intermediates directory found at {intermediates_dir}[/yellow]")
        return

    console.print(Panel.fit(
        f"[bold]Pipeline Status: {output_dir}[/bold]",
        border_style="blue"
    ))

    stages = [
        ("01_extracted_sections", "Section Extraction"),
        ("02_business_rules", "Agent 1: Analyst (Business Rules)"),
        ("03_pydantic_schema", "Agent 2: Architect (Pydantic Schema)"),
        ("04_fastapi_output", "Agent 3: Developer (FastAPI App)"),
    ]

    for prefix, label in stages:
        pattern = str(intermediates_dir / f"{prefix}_*.json")
        files = list(Path(intermediates_dir).glob(f"{prefix}_*.json"))
        if files:
            latest = max(files, key=lambda f: f.stat().st_mtime)
            mtime = datetime.fromtimestamp(latest.stat().st_mtime)
            size = latest.stat().st_size
            console.print(f"  [green]✓[/green] {label}: {latest.name} ({size} bytes, {mtime.strftime('%Y-%m-%d %H:%M:%S')})")
        else:
            console.print(f"  [red]✗[/red] {label}: Not found")


@app.command()
def clear_intermediates(
    output_dir: str = typer.Argument("./output", help="Output directory"),
    confirm: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation"),
):
    """Delete all intermediate files to force fresh pipeline run."""
    from pathlib import Path

    intermediates_dir = Path(output_dir) / "intermediates"
    if not intermediates_dir.exists():
        console.print(f"[yellow]No intermediates directory found at {intermediates_dir}[/yellow]")
        return

    files = list(intermediates_dir.glob("*.json"))
    if not files:
        console.print("[yellow]No intermediate files to clear[/yellow]")
        return

    if not confirm:
        console.print(f"Found {len(files)} intermediate files in {intermediates_dir}")
        if not typer.confirm("Delete all intermediate files?"):
            console.print("Cancelled")
            return

    for f in files:
        f.unlink()
        console.print(f"  [red]Deleted[/red] {f.name}")

    console.print("[green]All intermediate files cleared[/green]")


@app.command()
def frontend(
    service_dirs: List[str] = typer.Argument(..., help="Paths to generated FastAPI service directories"),
    output_dir: str = typer.Option("./frontend-output", "-o", "--output", help="Output directory for generated frontend"),
    contracts_dir: Optional[str] = typer.Option(None, "-c", "--contracts", help="Path to contracts directory"),
    plan_file: Optional[str] = typer.Option(None, "-p", "--plan", help="Path to migration plan file"),
    env_file: Optional[str] = typer.Option(None, "-e", "--env", help="Path to .env file with GEMINI_API_KEY"),
    model: Optional[str] = typer.Option(None, "-m", "--model", help="Gemini model for frontend generation"),
    temperature: Optional[float] = typer.Option(None, "-t", "--temperature", help="Temperature (0.0-1.0)"),
    max_tokens: Optional[int] = typer.Option(None, "--max-tokens", help="Max tokens per response"),
):
    """
    Generate vanilla HTML/CSS/JS frontend from FastAPI service OpenAPI specs.

    Example:
        cobol2fastapi frontend ./migration-output/group-0 ./migration-output/group-1 -o ./frontend-output
        cobol2fastapi frontend ./migration-output/group-0 -o ./frontend-output --contracts ./migration-output/contracts --plan ./migration-output/migration-plan.json
    """
    # Load environment
    load_environment(env_file)

    # Check API key
    if not os.getenv("GEMINI_API_KEY"):
        console.print("[red]Error: GEMINI_API_KEY not found in environment[/red]")
        console.print("Create a .env file with your Gemini API key (see .env.example)")
        sys.exit(1)

    # Validate service directories
    valid_dirs = []
    for d in service_dirs:
        path = Path(d)
        if path.exists() and (path / "main.py").exists():
            valid_dirs.append(str(path))
        else:
            console.print(f"[yellow]Warning: Service directory not found or missing main.py: {d}[/yellow]")

    if not valid_dirs:
        console.print("[red]Error: No valid service directories found[/red]")
        sys.exit(1)

    console.print(Panel.fit(
        f"[bold]Frontend Generator (Agent 4)[/bold]\n"
        f"Services: {len(valid_dirs)}\n"
        f"Output: {output_dir}",
        border_style="blue"
    ))

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Generating vanilla HTML/CSS/JS frontend...", total=None)
            frontend_output = run_frontend_generation(
                service_dirs=valid_dirs,
                output_dir=output_dir,
                contracts_dir=contracts_dir,
                plan_file=plan_file,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            progress.update(task, completed=True)

    except Exception as e:
        console.print(f"\n[red]Frontend generation failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Write output files
    console.print("\n[bold]Writing generated frontend files...[/bold]")
    write_frontend_files(output_dir, frontend_output)

    # Summary
    console.print(Panel.fit(
        f"[bold green]Frontend Generation Complete![/bold green]\n\n"
        f"Generated vanilla HTML/CSS/JS application in: [cyan]{output_dir}[/cyan]\n\n"
        f"To run the frontend:\n"
        f"  cd {output_dir}\n"
        f"  python3 -m http.server 3000\n\n"
        f"Frontend will be at: http://localhost:3000\n"
        f"Ensure FastAPI backend services are running on their respective ports",
        border_style="green"
    ))


if __name__ == "__main__":
    app()