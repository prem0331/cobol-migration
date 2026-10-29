"""
Golden File Equivalence Testing

Runs semantic equivalence tests using:
1. COBOL Simulator (from BusinessRules) -> Golden outputs
2. Generated FastAPI -> Actual outputs
3. Compare both against golden files

Usage:
    # Generate golden files from simulator
    python -m src.testing.golden_test generate --cobol-dir tests/fixtures/phase2_coupled --output tests/golden

    # Run equivalence tests
    python -m src.testing.golden_test test --golden-dir tests/golden --services-dir migration-output
"""

import json
import subprocess
import time
import requests
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from .cobol_simulator import CobolSimulator, load_business_rules, save_simulator_output
from .test_case_generator import generate_test_cases, TestCase, save_test_cases, load_test_cases


class TestStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


@dataclass
class GoldenFile:
    """Golden file containing expected outputs for a program."""
    program_id: str
    test_case_name: str
    simulator_output: Dict[str, Any]
    api_output: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TestResult:
    """Result of a single test."""
    test_case: TestCase
    status: TestStatus
    simulator_match: bool = False
    api_match: bool = False
    simulator_diffs: List[str] = field(default_factory=list)
    api_diffs: List[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    error_message: str = ""


@dataclass
class TestReport:
    """Full test report."""
    program_id: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    results: List[TestResult] = field(default_factory=list)


class FastAPIClient:
    """Client for calling generated FastAPI service."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url

    def call(self, method: str, path: str, data: Dict = None, params: Dict = None) -> Dict:
        """Call an endpoint."""
        url = f"{self.base_url}{path}"
        try:
            if method.upper() == "GET":
                resp = requests.get(url, params=params, timeout=10)
            else:
                resp = requests.post(url, json=data, timeout=10)
            return {"status": resp.status_code, "data": resp.json()}
        except requests.exceptions.ConnectionError:
            return {"status": 0, "error": "Connection refused - server not running"}
        except Exception as e:
            return {"status": 500, "error": str(e)}


class GoldenTestRunner:
    """Runs golden file equivalence tests."""

    def __init__(self, golden_dir: Path, services_base_dir: Path):
        self.golden_dir = Path(golden_dir)
        self.services_base_dir = Path(services_base_dir)
        self.client = FastAPIClient()

    def generate_golden_files(self, cobol_dir: Path, test_cases: List[TestCase] = None):
        """Generate golden files from COBOL simulator."""
        self.golden_dir.mkdir(parents=True, exist_ok=True)

        cobol_files = list(cobol_dir.glob("*.cbl"))
        print(f"Found {len(cobol_files)} COBOL programs")

        for cobol_file in cobol_files:
            program_id = cobol_file.stem
            print(f"\nProcessing {program_id}...")

            # Find business rules in migration intermediates
            rules_file = self._find_business_rules(program_id)
            if not rules_file:
                print(f"  No business rules found for {program_id}")
                continue

            rules = load_business_rules(rules_file)

            # Generate test cases if not provided
            if test_cases is None:
                cases = generate_test_cases(rules)
            else:
                cases = [tc for tc in test_cases if tc.program_id == program_id]

            if not cases:
                print(f"  No test cases for {program_id}")
                continue

            # Run simulator for each test case
            sim = CobolSimulator(rules)

            for tc in cases:
                sim.set_inputs(tc.inputs)
                sim_outputs = sim.run_all()

                # Find corresponding FastAPI service
                service_dir = self._find_service_dir(program_id)
                api_output = {}
                if service_dir:
                    api_output = self._call_fastapi_endpoint(service_dir, tc, rules)

                # Save golden file
                golden = GoldenFile(
                    program_id=program_id,
                    test_case_name=tc.name,
                    simulator_output=sim_outputs,
                    api_output=api_output,
                    metadata={
                        "description": tc.description,
                        "category": tc.category,
                        "inputs": tc.inputs
                    }
                )

                golden_file = self.golden_dir / f"{program_id}_{tc.name}.json"
                with open(golden_file, 'w') as f:
                    json.dump({
                        "program_id": golden.program_id,
                        "test_case_name": golden.test_case_name,
                        "simulator_output": golden.simulator_output,
                        "api_output": golden.api_output,
                        "metadata": golden.metadata
                    }, f, indent=2, default=str)

                print(f"  Generated: {golden_file.name}")

    def run_tests(self, service_ports: Dict[str, int] = None) -> TestReport:
        """Run equivalence tests against golden files."""
        golden_files = list(self.golden_dir.glob("*.json"))
        print(f"Found {len(golden_files)} golden files")

        if service_ports:
            self.client = FastAPIClient()  # Will be overridden per service

        report = TestReport(program_id="ALL")

        for golden_file in golden_files:
            with open(golden_file, 'r') as f:
                golden_data = json.load(f)

            program_id = golden_data["program_id"]
            test_name = golden_data["test_case_name"]
            expected_sim = golden_data["simulator_output"]
            expected_api = golden_data["api_output"]
            inputs = golden_data["metadata"].get("inputs", {})

            print(f"\nTesting {program_id}::{test_name}...")

            # Re-run simulator
            rules_file = self._find_business_rules(program_id)
            if not rules_file:
                report.errors += 1
                report.total += 1
                continue

            rules = load_business_rules(rules_file)
            sim = CobolSimulator(rules)
            sim.set_inputs(inputs)
            actual_sim = sim.run_all()

            # Compare simulator output
            sim_diffs = self._compare_outputs(expected_sim, actual_sim, "simulator")

            # Call FastAPI
            actual_api = {}
            api_diffs = []
            service_dir = self._find_service_dir(program_id)

            if service_dir:
                # Find port for this service
                port = service_ports.get(program_id) if service_ports else None
                if port:
                    self.client = FastAPIClient(f"http://localhost:{port}")

                # Create test case object
                tc = TestCase(
                    name=test_name,
                    description=golden_data["metadata"].get("description", ""),
                    inputs=inputs,
                    expected_outputs={},  # Not used for API comparison directly
                    program_id=program_id
                )
                actual_api = self._call_fastapi_endpoint(service_dir, tc, rules)
                api_diffs = self._compare_outputs(expected_api, actual_api.get("data", {}), "api")

            # Determine status
            sim_match = len(sim_diffs) == 0
            api_match = len(api_diffs) == 0

            if sim_match and api_match:
                status = TestStatus.PASS
                report.passed += 1
            else:
                status = TestStatus.FAIL
                report.failed += 1

            report.total += 1
            report.results.append(TestResult(
                test_case=TestCase(
                    name=test_name,
                    description=golden_data["metadata"].get("description", ""),
                    inputs=inputs,
                    expected_outputs=expected_sim,
                    program_id=program_id
                ),
                status=status,
                simulator_match=sim_match,
                api_match=api_match,
                simulator_diffs=sim_diffs,
                api_diffs=api_diffs
            ))

            status_str = "✓ PASS" if status == TestStatus.PASS else "✗ FAIL"
            print(f"  {status_str} | Sim: {'✓' if sim_match else '✗'} | API: {'✓' if api_match else '✗'}")
            if sim_diffs:
                print(f"    Sim diffs: {sim_diffs[:3]}")
            if api_diffs:
                print(f"    API diffs: {api_diffs[:3]}")

        return report

    def _find_business_rules(self, program_id: str) -> Optional[Path]:
        """Find business rules JSON in intermediates."""
        # Search in migration-output/group-*/intermediates/
        for group_dir in self.services_base_dir.glob("group-*/intermediates"):
            # Look for the business rules files with pattern 02_business_rules_<PROGRAM>_*.json
            for br_file in group_dir.glob(f"02_business_rules_{program_id}_*.json"):
                return br_file
            # Also check hash-named files by reading them to find the program_name
            for br_file in group_dir.glob("02_business_rules_*.json"):
                try:
                    with open(br_file) as f:
                        data = json.load(f)
                        if data.get("program_name") == program_id:
                            return br_file
                except Exception:
                    continue
        return None

    def _find_service_dir(self, program_id: str) -> Optional[Path]:
        """Find the service directory for a program."""
        for group_dir in self.services_base_dir.glob("group-*"):
            prog_dir = group_dir / program_id.lower()
            if prog_dir.exists() and (prog_dir / "main.py").exists():
                return prog_dir
        return None

    def _call_fastapi_endpoint(self, service_dir: Path, test_case: TestCase, rules: Dict) -> Dict:
        """Call the appropriate FastAPI endpoint for a test case."""
        # This needs to map test cases to API endpoints
        # For now, return placeholder - needs customization per program
        return {"status": "not_implemented", "data": {}}

    def _normalize_value(self, value: Any) -> Any:
        """Normalize value for comparison (handle string/Decimal/int/float)."""
        from decimal import Decimal
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, str):
            # Try to convert numeric strings
            try:
                if '.' in value:
                    return float(value)
                return int(value)
            except ValueError:
                return value
        return value

    def _compare_outputs(self, expected: Dict, actual: Dict, source: str) -> List[str]:
        """Compare expected vs actual outputs."""
        diffs = []

        all_keys = set(expected.keys()) | set(actual.keys())
        for key in all_keys:
            exp_val = expected.get(key)
            act_val = actual.get(key)

            # Normalize for comparison
            exp_norm = self._normalize_value(exp_val)
            act_norm = self._normalize_value(act_val)

            if exp_norm != act_norm:
                diffs.append(f"{key}: expected={exp_val}, actual={act_val}")

        return diffs


def generate_golden_files_command(
    cobol_dir: str,
    golden_dir: str,
    services_dir: str
):
    """CLI command to generate golden files."""
    runner = GoldenTestRunner(Path(golden_dir), Path(services_dir))
    runner.generate_golden_files(Path(cobol_dir))
    print(f"\nGolden files generated in {golden_dir}")


def run_tests_command(
    golden_dir: str,
    services_dir: str,
    service_ports: Dict[str, int] = None
) -> TestReport:
    """CLI command to run equivalence tests."""
    runner = GoldenTestRunner(Path(golden_dir), Path(services_dir))
    return runner.run_tests(service_ports)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage:")
        print("  python -m src.testing.golden_test generate <cobol_dir> <golden_dir> <services_dir>")
        print("  python -m src.testing.golden_test test <golden_dir> <services_dir> [port1=8000 port2=8001...]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "generate":
        generate_golden_files_command(sys.argv[2], sys.argv[3], sys.argv[4])
    elif command == "test":
        ports = {}
        if len(sys.argv) > 4:
            for arg in sys.argv[4:]:
                if '=' in arg:
                    k, v = arg.split('=')
                    ports[k] = int(v)
        report = run_tests_command(sys.argv[2], sys.argv[3], ports)
        print(f"\n=== SUMMARY ===")
        print(f"Total: {report.total}, Passed: {report.passed}, Failed: {report.failed}")
        sys.exit(0 if report.failed == 0 else 1)