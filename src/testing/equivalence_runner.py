"""
Golden-File Equivalence Test Runner

Compares COBOL Simulator output against generated FastAPI service output.
Uses committed golden files as the source of truth.

Usage:
    python -m src.testing.equivalence_runner --service-dir ./migration-output/group-0 --program CUSTOMER-MAIN
"""

import json
import subprocess
import time
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum

import requests
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from .cobol_simulator import CobolSimulator, load_business_rules

console = Console()


class TestStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


@dataclass
class TestCase:
    name: str
    description: str
    inputs: Dict[str, Any]
    expected_outputs: Dict[str, Any]
    endpoint: str = ""
    method: str = "POST"


@dataclass
class TestResult:
    test_case: TestCase
    status: TestStatus
    simulator_output: Dict[str, Any]
    fastapi_output: Dict[str, Any]
    differences: List[str]
    error_message: str = ""
    execution_time_ms: float = 0.0


@dataclass
class GoldenFile:
    """Golden file structure for equivalence testing."""
    program_name: str
    test_cases: List[Dict[str, Any]]
    metadata: Dict[str, Any]


class GoldenFileManager:
    """Manages golden files for equivalence testing."""

    def __init__(self, golden_dir: Path):
        self.golden_dir = golden_dir
        self.golden_dir.mkdir(parents=True, exist_ok=True)

    def get_golden_path(self, program_name: str) -> Path:
        return self.golden_dir / f"{program_name.lower()}.json"

    def load_golden(self, program_name: str) -> Optional[GoldenFile]:
        path = self.get_golden_path(program_name)
        if not path.exists():
            return None
        with open(path, 'r') as f:
            data = json.load(f)
        return GoldenFile(**data)

    def save_golden(self, program_name: str, test_cases: List[TestCase], metadata: Dict = None):
        path = self.get_golden_path(program_name)
        data = {
            "program_name": program_name,
            "test_cases": [asdict(tc) for tc in test_cases],
            "metadata": metadata or {}
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        console.print(f"[green]Saved golden file: {path}[/green]")

    def list_goldens(self) -> List[str]:
        return [f.stem for f in self.golden_dir.glob("*.json")]


class FastAPIClient:
    """Client for calling generated FastAPI service."""

    def __init__(self, service_dir: Path, port: int = 8000):
        self.service_dir = service_dir
        self.port = port
        self.base_url = f"http://localhost:{port}"
        self.process: Optional[subprocess.Popen] = None

    def start(self) -> bool:
        """Start the FastAPI server."""
        try:
            # Install requirements
            req_file = self.service_dir / "requirements.txt"
            if req_file.exists():
                console.print(f"[dim]Installing requirements from {req_file}[/dim]")
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-q", "-r", str(req_file)],
                    cwd=self.service_dir,
                    capture_output=True,
                    timeout=120
                )
                if result.returncode != 0:
                    console.print(f"[yellow]Warning: pip install failed: {result.stderr.decode()}[/yellow]")

            # Start uvicorn
            self.process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(self.port)],
                cwd=self.service_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            # Wait for server to start
            for _ in range(30):
                try:
                    resp = requests.get(f"{self.base_url}/docs", timeout=1)
                    if resp.status_code == 200:
                        console.print(f"[green]FastAPI server started on port {self.port}[/green]")
                        return True
                except:
                    time.sleep(0.5)

            console.print(f"[red]FastAPI server failed to start on port {self.port}[/red]")
            return False

        except Exception as e:
            console.print(f"[red]Failed to start FastAPI server: {e}[/red]")
            return False

    def stop(self):
        """Stop the FastAPI server."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            console.print(f"[dim]FastAPI server stopped[/dim]")

    def call(self, method: str, endpoint: str, data: Dict = None) -> Dict[str, Any]:
        """Call a FastAPI endpoint."""
        url = f"{self.base_url}{endpoint}"
        try:
            if method.upper() == "GET":
                resp = requests.get(url, params=data, timeout=10)
            else:
                # Always send JSON body for POST, even if endpoint has query parameters
                # data will be {} if not provided
                resp = requests.post(url, json=data or {}, timeout=10)
            return {
                "status_code": resp.status_code,
                "data": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
            }
        except Exception as e:
            return {"status_code": 500, "error": str(e)}


class EquivalenceRunner:
    """Runs equivalence tests between COBOL simulator and FastAPI service."""

    def __init__(self, golden_dir: Path = Path("tests/equivalence/golden")):
        self.golden_manager = GoldenFileManager(golden_dir)

    def _create_simulator(self, simulator: CobolSimulator) -> CobolSimulator:
        """Create a fresh simulator instance from an existing one."""
        return CobolSimulator({
            "program_name": simulator.program_name,
            "data_definitions": [
                {"name": n, "level": f.level, "picture": f.picture, "usage": f.usage,
                 "value": f.value, "occurs": f.occurs, "redefines": f.redefines,
                 "parent": f.parent, "children": [], "condition_names": f.condition_names}
                for n, f in simulator.fields.items()
            ],
            "business_logic": [
                {"name": r.name, "rule_type": r.rule_type, "source_paragraph": r.source_paragraph,
                 "description": r.description, "conditions": r.conditions, "actions": r.actions,
                 "variables_used": r.variables_used}
                for r in simulator.rules
            ],
            "condition_names": simulator.condition_names,
            "paragraphs": simulator.paragraphs
        })

    def generate_test_cases_from_simulator(self, simulator: CobolSimulator) -> List[TestCase]:
        """Generate test cases by running simulator with various inputs."""
        test_cases = []

        # Get default inputs from VALUE clauses
        default_inputs = {}
        for name, field in simulator.fields.items():
            if field.value is not None and field.is_elementary():
                default_inputs[name] = field.default_value()

        # Test Case 1: Default values (from VALUE clauses) OR sensible defaults for fields without VALUE
        # If no VALUE clauses, generate sensible defaults for all elementary fields
        if not default_inputs:
            # Generate sensible defaults for all elementary fields
            for name, field in simulator.fields.items():
                if field.is_elementary():
                    if field.picture and '9' in field.picture:
                        default_inputs[name] = 0
                    elif field.picture and ('X' in field.picture or 'A' in field.picture):
                        default_inputs[name] = ""
                    else:
                        default_inputs[name] = field._default_for_type()

        # Run with default inputs
        sim = self._create_simulator(simulator)
        sim.set_inputs(default_inputs)
        sim.run_all()
        expected = sim.memory

        test_cases.append(TestCase(
            name="default_values",
            description="Execute with WORKING-STORAGE defaults",
            inputs=default_inputs,
            expected_outputs=expected
        ))

        # Test Case 2: Each 88-level condition
        for name, field in simulator.fields.items():
            for cond_name, cond_value in field.condition_names.items():
                test_inputs = default_inputs.copy()
                test_inputs[name] = cond_value

                sim = self._create_simulator(simulator)
                sim.set_inputs(test_inputs)
                sim.run_all()
                expected = sim.memory

                test_cases.append(TestCase(
                    name=f"condition_{cond_name.lower()}",
                    description=f"Test {cond_name} condition on {name}",
                    inputs=test_inputs,
                    expected_outputs=expected
                ))

        # Test Case 3: Boundary values for numeric fields
        for name, field in simulator.fields.items():
            if field.picture and '9' in field.picture and field.is_elementary():
                # Test zero (if not already default)
                if default_inputs.get(name) != 0:
                    test_inputs = default_inputs.copy()
                    test_inputs[name] = 0
                    sim = self._create_simulator(simulator)
                    sim.set_inputs(test_inputs)
                    sim.run_all()
                    expected = sim.memory

                    test_cases.append(TestCase(
                        name=f"boundary_{name.lower()}_zero",
                        description=f"Test zero value for {name}",
                        inputs=test_inputs,
                        expected_outputs=expected
                    ))

                # Test max value based on picture (e.g., 9(6) -> 999999)
                max_val = self._get_max_value_from_picture(field.picture)
                if max_val and default_inputs.get(name) != max_val:
                    test_inputs = default_inputs.copy()
                    test_inputs[name] = max_val
                    sim = self._create_simulator(simulator)
                    sim.set_inputs(test_inputs)
                    sim.run_all()
                    expected = sim.memory

                    test_cases.append(TestCase(
                        name=f"boundary_{name.lower()}_max",
                        description=f"Test max value for {name}",
                        inputs=test_inputs,
                        expected_outputs=expected
                    ))

        # Test Case 4: Empty/blank values for alphanumeric fields
        for name, field in simulator.fields.items():
            if field.picture and ('X' in field.picture or 'A' in field.picture) and field.is_elementary():
                if default_inputs.get(name) != "":
                    test_inputs = default_inputs.copy()
                    test_inputs[name] = ""
                    sim = self._create_simulator(simulator)
                    sim.set_inputs(test_inputs)
                    sim.run_all()
                    expected = sim.memory

                    test_cases.append(TestCase(
                        name=f"empty_{name.lower()}",
                        description=f"Test empty value for {name}",
                        inputs=test_inputs,
                        expected_outputs=expected
                    ))

        return test_cases

    def _get_max_value_from_picture(self, picture: str) -> Optional[int]:
        """Extract max value from COBOL picture clause (e.g., 9(6) -> 999999)."""
        import re
        match = re.search(r'9\((\d+)\)', picture)
        if match:
            return int('9' * int(match.group(1)))
        match = re.search(r'9+', picture)
        if match:
            return int('9' * len(match.group(0)))
        return None

    def run_test_case(self, simulator: CobolSimulator, client: FastAPIClient, test_case: TestCase) -> TestResult:
        """Run a single test case."""
        start = time.time()

        # Run simulator
        sim = CobolSimulator({
            "program_name": simulator.program_name,
            "data_definitions": [
                {"name": n, "level": f.level, "picture": f.picture, "usage": f.usage,
                 "value": f.value, "occurs": f.occurs, "redefines": f.redefines,
                 "parent": f.parent, "children": [], "condition_names": f.condition_names}
                for n, f in simulator.fields.items()
            ],
            "business_logic": [
                {"name": r.name, "rule_type": r.rule_type, "source_paragraph": r.source_paragraph,
                 "description": r.description, "conditions": r.conditions, "actions": r.actions,
                 "variables_used": r.variables_used}
                for r in simulator.rules
            ],
            "condition_names": simulator.condition_names,
            "paragraphs": simulator.paragraphs
        })
        sim.set_inputs(test_case.inputs)
        sim.run_all()
        simulator_output = sim.memory

        # Call FastAPI
        fastapi_result = client.call(test_case.method, test_case.endpoint, test_case.inputs)

        # Extract comparable outputs
        fastapi_output = fastapi_result.get("data", {})
        fastapi_status = fastapi_result.get("status_code", 200)
        if isinstance(fastapi_output, dict) and "data" in fastapi_output:
            fastapi_output = fastapi_output["data"]

        console.print(f"[dim]DEBUG FastAPI: endpoint={test_case.endpoint} status={fastapi_status} output={fastapi_output}[/dim]")

        # Compare
        differences = []
        for key, expected in test_case.expected_outputs.items():
            # Handle validation errors - check status_code
            if key == "status_code":
                if fastapi_status != expected:
                    differences.append(f"{key}: expected {expected}, got {fastapi_status}")
            else:
                actual = fastapi_output.get(key)
                if actual != expected:
                    differences.append(f"{key}: simulator={expected}, fastapi={actual}")

        exec_time = (time.time() - start) * 1000

        if differences:
            return TestResult(
                test_case=test_case,
                status=TestStatus.FAIL,
                simulator_output=simulator_output,
                fastapi_output=fastapi_output,
                differences=differences,
                execution_time_ms=exec_time
            )
        else:
            return TestResult(
                test_case=test_case,
                status=TestStatus.PASS,
                simulator_output=simulator_output,
                fastapi_output=fastapi_output,
                differences=[],
                execution_time_ms=exec_time
            )

    def run_equivalence(
        self,
        service_dir: Path,
        program_name: str,
        test_cases: Optional[List[TestCase]] = None,
        create_golden: bool = False,
        port: int = 8000
    ) -> Dict[str, Any]:
        """Run full equivalence test suite."""
        console.print(Panel.fit(
            f"[bold]Equivalence Test: {program_name}[/bold]\n"
            f"Service: {service_dir}",
            border_style="blue"
        ))

        # Load business rules from migration intermediates
        intermediates_dir = service_dir / "intermediates"
        business_rules_path = None

        # Try multiple patterns
        patterns = [
            f"02_business_rules_{program_name}_*.json",
            f"analyst_{program_name}_*.json",
            f"02_business_rules_*.json"
        ]

        for pattern in patterns:
            matches = list(intermediates_dir.glob(pattern))
            if matches:
                # Pick the one with the program name in it if possible
                for m in matches:
                    if program_name in m.name:
                        business_rules_path = m
                        break
                if not business_rules_path:
                    business_rules_path = matches[0]
                break

        if not business_rules_path or not business_rules_path.exists():
            console.print(f"[red]No business rules found in {intermediates_dir}[/red]")
            console.print(f"[dim]Searched for patterns: {patterns}[/dim]")
            return {"error": "Business rules not found"}

        console.print(f"[dim]Loading business rules from {business_rules_path}[/dim]")
        business_rules = load_business_rules(business_rules_path)
        simulator = CobolSimulator(business_rules)

        # Generate or load test cases
        if test_cases is None:
            test_cases = self.generate_test_cases_from_simulator(simulator)

        # Create golden file if requested
        if create_golden:
            self.golden_manager.save_golden(program_name, test_cases, {
                "source": "simulator_generated",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
            })
            console.print(f"[green]Created golden file for {program_name}[/green]")
            return {"created_golden": True, "test_cases": len(test_cases)}

        # Load golden file for comparison
        golden = self.golden_manager.load_golden(program_name)
        if golden:
            # Use golden test cases
            test_cases = [TestCase(**tc) for tc in golden.test_cases]

        # Start FastAPI server
        client = FastAPIClient(service_dir, port)
        if not client.start():
            return {"error": "Failed to start FastAPI server"}

        try:
            # Map test cases to endpoints - only infer for test cases without explicit endpoints
            endpoint_map = self._infer_endpoints(service_dir, program_name, test_cases)
            for tc in test_cases:
                # Only override if endpoint is empty or not set (from golden file)
                if tc.name in endpoint_map and not tc.endpoint:
                    tc.endpoint = endpoint_map[tc.name]["path"]
                    tc.method = endpoint_map[tc.name].get("method", "POST")

            # Run tests
            results = []
            passed = 0
            failed = 0

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task(f"Running {len(test_cases)} tests...", total=len(test_cases))

                for tc in test_cases:
                    progress.update(task, description=f"Testing {tc.name}...")
                    console.print(f"[dim]DEBUG: Test {tc.name} endpoint={tc.endpoint} method={tc.method} inputs={tc.inputs}[/dim]")
                    result = self.run_test_case(simulator, client, tc)
                    results.append(result)
                    if result.status == TestStatus.PASS:
                        passed += 1
                    else:
                        failed += 1
                    progress.advance(task)

            # Print results
            self._print_results(program_name, results)

            return {
                "program": program_name,
                "total": len(results),
                "passed": passed,
                "failed": failed,
                "results": [asdict(r) for r in results]
            }

        finally:
            client.stop()

    def _infer_endpoints(self, service_dir: Path, program_name: str, test_cases: List[TestCase] = None) -> Dict[str, Dict]:
        """Dynamically infer API endpoints from generated routes.py and service contracts."""
        endpoints = {}
        routes_file = service_dir / "routes.py"
        if not routes_file.exists():
            return endpoints

        content = routes_file.read_text()

        # Extract all endpoints with their metadata
        import re
        # Pattern: @router.method("/path", ..., summary="...", description="...")
        # Returns 5 groups: method, path, summary_raw, summary_val, description
        pattern = r'@router\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']([^)]*?summary=["\']([^"\']*)["\'])?(?:[^)]*?description=["\']([^"\']*)["\'])?'
        matches = re.findall(pattern, content, re.DOTALL)

        # Build list of all endpoints with metadata
        all_endpoints = []
        for match in matches:
            method, path, summary_raw, summary_val, description = match
            summary_clean = summary_val if summary_val else ""
            description_clean = description if description else ""
            all_endpoints.append({
                "method": method.upper(),
                "path": path,
                "summary": summary_clean,
                "description": description_clean,
                "full_text": f"{method.upper()} {path} - {summary_clean} - {description_clean}"
            })

        # Load service contracts for cross-service call information
        contracts_file = service_dir.parent / "contracts" / "service_contracts.json"
        service_contracts = []
        if contracts_file.exists():
            try:
                with open(contracts_file) as f:
                    service_contracts = json.load(f)
            except Exception:
                pass

        # Use provided test cases or generate signatures from golden file
        test_case_names = []
        if test_cases:
            test_case_names = [tc.name for tc in test_cases]
        else:
            # Fallback to golden file
            golden = self.golden_manager.load_golden(program_name)
            if golden:
                test_case_names = [tc.get("name", "") for tc in golden.test_cases]

        # Dynamically match test cases to endpoints
        for tc_name in test_case_names:
            best_match = self._find_best_endpoint_match(
                tc_name, all_endpoints, program_name, service_contracts
            )
            if best_match:
                endpoints[tc_name] = best_match

        return endpoints

    def _get_test_case_signatures(self) -> Dict[str, Dict]:
        """Return expected test case names and their input signatures for matching."""
        # This will be populated dynamically based on the actual test cases generated
        return {}

    def _find_best_endpoint_match(
        self,
        test_case_name: str,
        all_endpoints: List[Dict],
        program_name: str,
        service_contracts: List[Dict]
    ) -> Optional[Dict]:
        """Find the best matching endpoint for a test case."""
        tc_lower = test_case_name.lower()
        prog_lower = program_name.lower()

        # Score each endpoint
        scored = []
        for ep in all_endpoints:
            score = 0
            ep_text = f"{ep['path']} {ep['summary']} {ep['description']}".lower()

            # Strong signals
            if prog_lower in ep_text:
                score += 10
            if "validate" in tc_lower and "validate" in ep_text:
                score += 8
            if "create" in tc_lower and "create" in ep_text:
                score += 8
            if "run-main" in tc_lower and "run-main" in ep_text:
                score += 8
            if "write-summary" in tc_lower and "write-summary" in ep_text:
                score += 8
            if "write-detail" in tc_lower and "write-detail" in ep_text:
                score += 8

            # Moderate signals
            if "customer" in tc_lower and "customer" in ep_text:
                score += 5
            if "report" in tc_lower and "report" in ep_text:
                score += 5
            if "boundary" in tc_lower or "zero" in tc_lower or "max" in tc_lower:
                if ep['method'] == 'POST':
                    score += 3
            if "condition" in tc_lower:
                if ep['method'] == 'POST':
                    score += 3
            if "empty" in tc_lower:
                if ep['method'] == 'POST':
                    score += 3
            if "default" in tc_lower or "valid" in tc_lower:
                if ep['method'] == 'POST':
                    score += 3

            # Check service contracts
            for contract in service_contracts:
                if contract.get("source_service", "").lower() == prog_lower:
                    if contract.get("endpoint", "").lower() in ep_text:
                        score += 5

            scored.append((score, ep))

        # Return highest scoring endpoint
        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            best = scored[0]
            if best[0] > 0:
                return {"path": best[1]["path"], "method": best[1]["method"]}

        # Fallback: return first POST endpoint for test cases that need POST
        post_endpoints = [ep for ep in all_endpoints if ep['method'] == 'POST']
        if post_endpoints and ("boundary" in tc_lower or "condition" in tc_lower or "empty" in tc_lower or "default" in tc_lower):
            return {"path": post_endpoints[0]["path"], "method": "POST"}

        return None

    def _print_results(self, program_name: str, results: List[TestResult]):
        """Print test results table."""
        table = Table(title=f"Equivalence Results: {program_name}")
        table.add_column("Test Case", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Description")
        table.add_column("Differences", style="red")
        table.add_column("Time (ms)")

        for r in results:
            status_color = {
                TestStatus.PASS: "green",
                TestStatus.FAIL: "red",
                TestStatus.ERROR: "yellow"
            }.get(r.status, "white")

            table.add_row(
                r.test_case.name,
                f"[{status_color}]{r.status.value}[/{status_color}]",
                r.test_case.description,
                "; ".join(r.differences) if r.differences else "—",
                f"{r.execution_time_ms:.1f}"
            )

        console.print(table)

        # Summary
        passed = sum(1 for r in results if r.status == TestStatus.PASS)
        failed = sum(1 for r in results if r.status == TestStatus.FAIL)
        console.print(Panel.fit(
            f"[bold]Summary: {program_name}[/bold]\n"
            f"Total: {len(results)}, Passed: {passed}, Failed: {failed}",
            border_style="green" if failed == 0 else "red"
        ))


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Run semantic equivalence tests")
    parser.add_argument("--service-dir", required=True, help="Path to generated FastAPI service directory")
    parser.add_argument("--program", required=True, help="Program name (e.g., CUSTOMER-MAIN)")
    parser.add_argument("--golden-dir", default="tests/equivalence/golden", help="Golden files directory")
    parser.add_argument("--create-golden", action="store_true", help="Create golden file from simulator")
    parser.add_argument("--port", type=int, default=8000, help="FastAPI server port")

    args = parser.parse_args()

    runner = EquivalenceRunner(Path(args.golden_dir))
    result = runner.run_equivalence(
        service_dir=Path(args.service_dir),
        program_name=args.program,
        create_golden=args.create_golden,
        port=args.port
    )

    if "error" in result:
        console.print(f"[red]Error: {result['error']}[/red]")
        sys.exit(1)

    if result.get("created_golden"):
        console.print(f"[green]Golden file created successfully[/green]")
        sys.exit(0)

    if result.get("failed", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()