"""CLI entry point for the COBOL to FastAPI migration pipeline."""

import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from dotenv import load_dotenv

from .chain import build_simple_chain
from .models import FastAPIOutput
from ..cobol.extractor import extract_cobol_sections

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


if __name__ == "__main__":
    app()