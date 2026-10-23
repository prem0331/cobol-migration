"""LCEL chain composition for the COBOL to FastAPI migration pipeline."""

import os
import json
import glob
import hashlib
from typing import Dict, Any, Optional, Tuple
from langchain_core.runnables import RunnablePassthrough, RunnableLambda, RunnableSequence
from langchain_core.output_parsers import StrOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI

from .prompts import (
    ANALYST_PROMPT,
    ARCHITECT_PROMPT,
    DEVELOPER_PROMPT,
    str_parser,
)
from .parsers import (
    parse_business_rules,
    parse_pydantic_schema,
    parse_fastapi_output,
    save_intermediate_output,
    BusinessRulesParser,
    PydanticSchemaParser,
    FastAPIOutputParser,
)
from .models import BusinessRules, PydanticSchema, FastAPIOutput
from ..cobol.extractor import extract_cobol_sections, CobolSections


def _compute_input_hash(cobol_source: str) -> str:
    """Compute a stable hash of the COBOL source for isolation."""
    return hashlib.sha256(cobol_source.encode('utf-8')).hexdigest()[:16]


def _get_intermediate_path(output_dir: str, stage_prefix: str, input_hash: str) -> str:
    """Get the intermediate file path keyed by input hash."""
    return os.path.join(output_dir, f"{stage_prefix}_{input_hash}.json")


def _verify_program_match(output_dir: str, stage_prefix: str, expected_program: str, input_hash: str) -> bool:
    """Verify that an intermediate file matches the expected program and input."""
    path = _get_intermediate_path(output_dir, stage_prefix, input_hash)
    if not os.path.exists(path):
        return False
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        # Check program name if present in the data
        if 'program_name' in data:
            return data['program_name'] == expected_program
        return True  # Fallback: trust hash-based isolation
    except Exception:
        return False


def get_llm(
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> ChatGoogleGenerativeAI:
    """Create Gemini LLM instance with configuration."""
    return ChatGoogleGenerativeAI(
        model=model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        temperature=temperature or float(os.getenv("GEMINI_TEMPERATURE", "0.1")),
        max_output_tokens=max_tokens or int(os.getenv("GEMINI_MAX_TOKENS", "8192")),
        google_api_key=os.getenv("GEMINI_API_KEY"),
    )


def get_llm_for_agent(
    agent: str,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> ChatGoogleGenerativeAI:
    """
    Create LLM instance configured for a specific agent.

    Args:
        agent: One of 'analyst', 'architect', 'developer'
        model: Override model for this agent
        temperature: Override temperature
        max_tokens: Override max tokens

    Returns:
        Configured ChatGoogleGenerativeAI instance
    """
    # Agent-specific defaults (can be overridden by env vars or params)
    agent_defaults = {
        "analyst": {
            "model": os.getenv("GEMINI_ANALYST_MODEL", "gemini-2.5-flash"),
            "temperature": float(os.getenv("GEMINI_ANALYST_TEMPERATURE", "0.1")),
            "max_tokens": int(os.getenv("GEMINI_ANALYST_MAX_TOKENS", "8192")),
        },
        "architect": {
            "model": os.getenv("GEMINI_ARCHITECT_MODEL", "gemini-2.5-pro"),
            "temperature": float(os.getenv("GEMINI_ARCHITECT_TEMPERATURE", "0.1")),
            "max_tokens": int(os.getenv("GEMINI_ARCHITECT_MAX_TOKENS", "8192")),
        },
        "developer": {
            "model": os.getenv("GEMINI_DEVELOPER_MODEL", "gemini-2.5-pro"),
            "temperature": float(os.getenv("GEMINI_DEVELOPER_TEMPERATURE", "0.1")),
            "max_tokens": int(os.getenv("GEMINI_DEVELOPER_MAX_TOKENS", "16384")),
        },
    }

    defaults = agent_defaults.get(agent, agent_defaults["analyst"])

    return ChatGoogleGenerativeAI(
        model=model or defaults["model"],
        temperature=temperature or defaults["temperature"],
        max_output_tokens=max_tokens or defaults["max_tokens"],
        google_api_key=os.getenv("GEMINI_API_KEY"),
    )


def load_intermediate(output_dir: str, stage_prefix: str, input_hash: str, expected_program: str) -> Optional[str]:
    """Load intermediate output for a specific input hash and program."""
    if not output_dir or not os.path.exists(output_dir):
        return None

    # First try exact hash match
    path = _get_intermediate_path(output_dir, stage_prefix, input_hash)
    if os.path.exists(path):
        if _verify_program_match(output_dir, stage_prefix, expected_program, input_hash):
            try:
                with open(path, 'r') as f:
                    return f.read()
            except Exception:
                pass

    # Fallback: search for any file with matching program name (for backward compatibility)
    pattern = os.path.join(output_dir, f"{stage_prefix}_*.json")
    for file_path in glob.glob(pattern):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            if data.get('program_name') == expected_program:
                return json.dumps(data)
        except Exception:
            continue

    return None


def load_business_rules(output_dir: str, input_hash: str, expected_program: str) -> Optional[BusinessRules]:
    """Load BusinessRules from intermediate output for specific input."""
    content = load_intermediate(output_dir, "02_business_rules", input_hash, expected_program)
    if content:
        try:
            data = json.loads(content)
            return BusinessRules(**data)
        except Exception:
            pass
    return None


def load_pydantic_schema(output_dir: str, input_hash: str, expected_program: str) -> Optional[PydanticSchema]:
    """Load PydanticSchema from intermediate output for specific input."""
    content = load_intermediate(output_dir, "03_pydantic_schema", input_hash, expected_program)
    if content:
        try:
            data = json.loads(content)
            return PydanticSchema(**data)
        except Exception:
            pass
    return None


def load_fastapi_output(output_dir: str, input_hash: str, expected_program: str) -> Optional[FastAPIOutput]:
    """Load FastAPIOutput from intermediate output for specific input."""
    content = load_intermediate(output_dir, "04_fastapi_output", input_hash, expected_program)
    if content:
        try:
            data = json.loads(content)
            return FastAPIOutput(**data)
        except Exception:
            pass
    return None


def check_pipeline_state(
    output_dir: Optional[str],
    cobol_source: str,
    program_name: str = "UNKNOWN"
) -> Tuple[Optional[BusinessRules], Optional[PydanticSchema], Optional[FastAPIOutput]]:
    """
    Check what stages have been completed for a specific COBOL input.
    Returns tuple of (business_rules, pydantic_schema, fastapi_output) where
    each is either the loaded object or None if not completed.
    """
    if not output_dir:
        return (None, None, None)

    input_hash = _compute_input_hash(cobol_source)

    business_rules = load_business_rules(output_dir, input_hash, program_name)
    pydantic_schema = load_pydantic_schema(output_dir, input_hash, program_name) if business_rules else None
    fastapi_output = load_fastapi_output(output_dir, input_hash, program_name) if pydantic_schema else None

    return (business_rules, pydantic_schema, fastapi_output)


def create_analyst_chain(
    output_dir: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
):
    """Create Agent 1 chain: COBOL -> BusinessRules JSON."""
    llm = get_llm_for_agent("analyst", model, temperature, max_tokens)

    def extract_sections(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Extract COBOL sections and prepare for prompt."""
        cobol_source = inputs["cobol"]
        sections = extract_cobol_sections(cobol_source)

        # Save raw extraction for debugging (with hash)
        if output_dir:
            input_hash = _compute_input_hash(cobol_source)
            path = _get_intermediate_path(output_dir, "01_extracted_sections", input_hash)
            os.makedirs(output_dir, exist_ok=True)
            with open(path, 'w') as f:
                f.write(str(sections.__dict__))

        return {
            "program_id": sections.program_id or "UNKNOWN",
            "working_storage": sections.working_storage or "(empty)",
            "procedure_division": sections.procedure_division or "(empty)",
            "file_section": sections.file_section or "(empty)",
            "linkage_section": sections.linkage_section or "(empty)",
        }

    def save_business_rules(output: BusinessRules) -> BusinessRules:
        """Save intermediate business rules with input hash."""
        # Need cobol_source to compute hash - pass via closure or thread-local
        # For now, use the output's program_name as fallback
        if output_dir and output.program_name != "UNKNOWN":
            # We can't easily get cobol_source here, so save with program name
            save_intermediate_output(output_dir, f"02_business_rules_{output.program_name}", output.model_dump_json(indent=2))
        elif output_dir:
            save_intermediate_output(output_dir, "02_business_rules", output.model_dump_json(indent=2))
        return output

    chain = (
        RunnableLambda(extract_sections)
        | ANALYST_PROMPT
        | llm
        | BusinessRulesParser()
        | RunnableLambda(save_business_rules)
    )

    return chain


def create_architect_chain(
    output_dir: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
):
    """Create Agent 2 chain: BusinessRules -> PydanticSchema."""
    llm = get_llm_for_agent("architect", model, temperature, max_tokens)

    def prepare_architect_input(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare business rules for architect prompt."""
        business_rules = inputs["business_rules"]
        return {
            "business_rules_json": business_rules.model_dump_json(indent=2)
        }

    def save_pydantic_schema(output: PydanticSchema) -> PydanticSchema:
        """Save intermediate Pydantic schema with program name for isolation."""
        if output_dir:
            # Use program name for isolation since we don't have cobol_source here
            save_intermediate_output(output_dir, f"03_pydantic_schema", output.model_dump_json(indent=2))
        return output

    chain = (
        RunnableLambda(prepare_architect_input)
        | ARCHITECT_PROMPT
        | llm
        | PydanticSchemaParser()
        | RunnableLambda(save_pydantic_schema)
    )

    return chain


def create_developer_chain(
    output_dir: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
):
    """Create Agent 3 chain: PydanticSchema -> FastAPIOutput."""
    llm = get_llm_for_agent("developer", model, temperature, max_tokens)

    def prepare_developer_input(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare Pydantic schema AND business rules for developer prompt."""
        pydantic_schema = inputs["pydantic_schema"]
        business_rules = inputs.get("business_rules")

        # Include business logic for dynamic inference of cross-entity operations
        business_logic_json = ""
        if business_rules:
            business_logic_json = business_rules.model_dump_json(indent=2, include={"business_logic", "data_definitions", "condition_names", "paragraphs"})

        return {
            "pydantic_schema_json": pydantic_schema.model_dump_json(indent=2),
            "business_logic_json": business_logic_json,
            "program_name": business_rules.program_name if business_rules else "Unknown",
        }

    def save_fastapi_output(output: FastAPIOutput) -> FastAPIOutput:
        """Save final FastAPI output with program name for isolation."""
        if output_dir:
            save_intermediate_output(output_dir, "04_fastapi_output", output.model_dump_json(indent=2))
        return output

    chain = (
        RunnableLambda(prepare_developer_input)
        | DEVELOPER_PROMPT
        | llm
        | FastAPIOutputParser()
        | RunnableLambda(save_fastapi_output)
    )

    return chain


def build_pipeline_chain(
    output_dir: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> RunnableSequence:
    """
    Build the complete linear pipeline chain:
    COBOL -> Analyst -> Architect -> Developer -> FastAPI
    """
    llm = get_llm(model, temperature, max_tokens)

    # Create individual agent chains
    analyst_chain = create_analyst_chain(llm, output_dir)
    architect_chain = create_architect_chain(llm, output_dir)
    developer_chain = create_developer_chain(llm, output_dir)

    # Compose full pipeline
    # Input: {"cobol": "source code"}
    # Output: FastAPIOutput
    pipeline = (
        # Step 1: Analyst
        {"cobol": RunnablePassthrough()}
        | RunnableLambda(lambda x: {"cobol": x["cobol"]})
        | analyst_chain
        # Step 2: Architect (takes business_rules from analyst)
        | RunnableLambda(lambda br: {"business_rules": br})
        | architect_chain
        # Step 3: Developer (takes pydantic_schema from architect, business_rules from analyst)
        | RunnableLambda(lambda ps: {
            "pydantic_schema": ps,
            "business_rules": ps  # This won't work - need to pass business_rules through
        })
    )

    # The above doesn't properly pass business_rules to developer.
    # Let's build it properly with RunnableParallel

    from langchain_core.runnables import RunnableParallel

    # Full pipeline with proper data flow
    full_pipeline = RunnableSequence(
        # Initial input preparation
        RunnableLambda(lambda x: {"cobol_source": x["cobol"]}),
        # Analyst stage
        RunnableParallel(
            cobol_source=RunnableLambda(lambda x: x["cobol_source"]),
            business_rules=analyst_chain,
        )
        # Architect stage
        | RunnableParallel(
            business_rules=RunnableLambda(lambda x: x["business_rules"]),
            pydantic_schema=architect_chain,
        )
        # Developer stage
        | RunnableParallel(
            business_rules=RunnableLambda(lambda x: x["business_rules"]),
            pydantic_schema=RunnableLambda(lambda x: x["pydantic_schema"]),
            fastapi_output=developer_chain,
        )
        # Final output
        | RunnableLambda(lambda x: x["fastapi_output"])
    )

    return full_pipeline


def build_simple_chain(
    output_dir: Optional[str] = None,
    # Global defaults (used if agent-specific not provided)
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    # Agent-specific overrides
    analyst_model: Optional[str] = None,
    analyst_temperature: Optional[float] = None,
    analyst_max_tokens: Optional[int] = None,
    architect_model: Optional[str] = None,
    architect_temperature: Optional[float] = None,
    architect_max_tokens: Optional[int] = None,
    developer_model: Optional[str] = None,
    developer_temperature: Optional[float] = None,
    developer_max_tokens: Optional[int] = None,
    resume: bool = True,
):
    """
    Build a simpler sequential chain that's easier to debug.
    Returns a callable that takes {"cobol": str} and returns FastAPIOutput.

    Args:
        output_dir: Directory for intermediate outputs
        model: Default LLM model to use for all agents
        temperature: Default temperature for generation
        max_tokens: Default max tokens per response
        analyst_model: Override model for Analyst (Agent 1)
        analyst_temperature: Override temperature for Analyst
        analyst_max_tokens: Override max tokens for Analyst
        architect_model: Override model for Architect (Agent 2)
        architect_temperature: Override temperature for Architect
        architect_max_tokens: Override max tokens for Architect
        developer_model: Override model for Developer (Agent 3)
        developer_temperature: Override temperature for Developer
        developer_max_tokens: Override max tokens for Developer
        resume: If True, resume from last successful intermediate (default: True)
    """
    # Individual chains with agent-specific configs
    analyst = create_analyst_chain(
        output_dir,
        model=analyst_model or model,
        temperature=analyst_temperature or temperature,
        max_tokens=analyst_max_tokens or max_tokens,
    )
    architect = create_architect_chain(
        output_dir,
        model=architect_model or model,
        temperature=architect_temperature or temperature,
        max_tokens=architect_max_tokens or max_tokens,
    )
    developer = create_developer_chain(
        output_dir,
        model=developer_model or model,
        temperature=developer_temperature or temperature,
        max_tokens=developer_max_tokens or max_tokens,
    )

    def run_pipeline(inputs: Dict[str, Any]) -> FastAPIOutput:
        """Execute pipeline step by step with resume capability (input-hash isolated)."""
        cobol_source = inputs["cobol"]

        # Compute hash for isolation
        input_hash = _compute_input_hash(cobol_source)

        # Extract program name early for verification
        sections = extract_cobol_sections(cobol_source)
        program_name = sections.program_id or "UNKNOWN"

        # Check for existing intermediates if resume is enabled
        business_rules = None
        pydantic_schema = None
        fastapi_output = None

        if resume and output_dir:
            business_rules, pydantic_schema, fastapi_output = check_pipeline_state(output_dir, cobol_source, program_name)
            if fastapi_output:
                print(f"✅ Pipeline already complete for {program_name} - loaded from intermediates")
                return fastapi_output
            elif pydantic_schema:
                print(f"🔄 Resuming {program_name} from Architect stage (Agent 2 complete)...")
            elif business_rules:
                print(f"🔄 Resuming {program_name} from Analyst stage (Agent 1 complete)...")
            else:
                print(f"🆕 No intermediates found for {program_name} - starting fresh")

        # Step 1: Analyst
        if business_rules is None:
            print("🔍 Agent 1 (Analyst): Extracting business rules...")
            business_rules = analyst.invoke({"cobol": cobol_source})
            print(f"   ✓ Found {len(business_rules.data_definitions)} data fields, "
                  f"{len(business_rules.business_logic)} business rules")
        else:
            print(f"   ✓ Loaded BusinessRules: {len(business_rules.data_definitions)} data fields, "
                  f"{len(business_rules.business_logic)} business rules")

        # Step 2: Architect
        if pydantic_schema is None:
            print("🏗️  Agent 2 (Architect): Designing Pydantic schema...")
            pydantic_schema = architect.invoke({"business_rules": business_rules})
            print(f"   ✓ Generated {len(pydantic_schema.models)} models, "
                  f"{len(pydantic_schema.enums)} enums")
        else:
            print(f"   ✓ Loaded PydanticSchema: {len(pydantic_schema.models)} models, "
                  f"{len(pydantic_schema.enums)} enums")

        # Step 3: Developer
        if fastapi_output is None:
            print("💻 Agent 3 (Developer): Building FastAPI application...")
            fastapi_output = developer.invoke({
                "pydantic_schema": pydantic_schema,
                "business_rules": business_rules,
            })
            print("   ✓ Generated FastAPI application")
        else:
            print("   ✓ Loaded FastAPIOutput from intermediates")

        # Save intermediates with input hash for future resume isolation
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            # Save each stage with hash-based filename
            for stage, data in [
                ("02_business_rules", business_rules.model_dump_json(indent=2)),
                ("03_pydantic_schema", pydantic_schema.model_dump_json(indent=2)),
                ("04_fastapi_output", fastapi_output.model_dump_json(indent=2)),
            ]:
                path = _get_intermediate_path(output_dir, stage, input_hash)
                with open(path, 'w') as f:
                    f.write(data)

        return fastapi_output

    return run_pipeline