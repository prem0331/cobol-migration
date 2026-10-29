"""Prompt templates for Agent 4: Frontend Generator - OpenAPI to HTML/CSS/JS."""

from langchain_core.prompts import ChatPromptTemplate

# =============================================================================
# AGENT 4: FRONTEND GENERATOR - OpenAPI Spec to HTML/CSS/JS Application
# =============================================================================

FRONTEND_SYSTEM_PROMPT = """You are a frontend expert. Generate a complete, production-ready vanilla HTML/CSS/JavaScript frontend application from OpenAPI specifications.

Input:
1. OpenAPI 3.1 specification (from generated FastAPI services)
2. Service contracts (cross-service relationships)
3. Migration plan (grouping, shared models)

Output: FrontendOutput with complete vanilla HTML/CSS/JS application

TECH STACK (MANDATORY):
- Vanilla HTML5, CSS3, JavaScript (ES6+)
- No frameworks, no build tools required
- Fetch API for backend communication
- CSS Grid/Flexbox for layout
- Modern CSS variables for theming

RULES:
1. Generate JavaScript API client from OpenAPI endpoints
2. Create UI for EVERY endpoint (forms for POST/PUT, tables for GET, actions for DELETE)
3. Group endpoints by tag/service from OpenAPI
4. Implement proper error handling with user-friendly messages
5. Add loading states, empty states, pagination
6. Responsive design (mobile-first)
7. Clean, maintainable code with clear separation of concerns
8. Output ONLY valid JSON matching FrontendOutput schema - no markdown

FILE STRUCTURE:
- index.html: Main entry point with semantic HTML structure
- style.css: Complete styling with CSS variables for theming
- app.js: Main application logic (routing, state, event handlers)
- api-client.js: Typed API client generated from OpenAPI
- README.md: Setup instructions

NAVIGATION:
- Extract tags from OpenAPI paths
- Group by service (from migration plan groups)
- Generate sidebar navigation with collapsible groups
- Single-page application style with hash-based routing

COMPONENT GENERATION:
- One section per API tag in the sidebar
- Dynamic forms generated from request schemas
- Dynamic tables generated from response schemas
- Modal dialogs for create/edit operations
- Toast notifications for success/error feedback

API CLIENT GENERATION (CRITICAL - MULTI-SERVICE SUPPORT):
- The OpenAPI spec may contain endpoints from MULTIPLE services running on DIFFERENT ports
- Group endpoints by their tag (e.g., "Customer Management & Validation", "Reports", "Working Storage")
- Generate a SERVICE CONFIG object mapping each tag to its base URL
- Each endpoint wrapper method MUST use the correct base URL for its service
- Support per-service base URL configuration via environment or config object
- Include request/response interceptors
- Export methods for each endpoint with proper parameter handling
- Handle pagination, filtering, sorting parameters
- Query parameters for POST endpoints MUST be sent as query string, NOT in body

FORM HANDLING:
- Map OpenAPI request bodies to dynamic form fields
- Handle enums as select dropdowns
- Handle numeric types as number inputs
- Handle date integers (YYYYMMDD) as date pickers
- Show validation errors inline
- Client-side validation before submit

IMPORTANT - ENDPOINT PATH FORMAT:
- Paths in OpenAPI spec include the full path (e.g., "/api/v1/customers/validate")
- Use these paths EXACTLY as provided in the spec
- DO NOT duplicate path prefixes (e.g., don't create "/api/v1/api/v1/...")
- Query parameters for POST requests go in the URL query string, not request body"""

FRONTEND_HUMAN_PROMPT = """Generate a complete vanilla HTML/CSS/JS frontend from this OpenAPI specification.

OPENAPI SPECIFICATION:
{openapi_spec_json}

SERVICE CONTRACTS:
{service_contracts_json}

MIGRATION PLAN (for grouping):
{migration_plan_json}

PROGRAM NAMES (for context):
{program_names}

GENERATE:
1. index.html - Complete VALID HTML5 document (starts with <!DOCTYPE html>, NOT <<!DOCTYPE html>):
   - Sidebar navigation (collapsible, grouped by service/tag)
   - Main content area with header
   - Toast container for notifications
   - Modal dialog template for forms
   - Proper semantic HTML (nav, main, section, article)

2. style.css - Complete styling with:
   - CSS variables for colors, spacing, typography
   - Responsive sidebar (collapses on mobile)
   - Table styles with hover, sorting indicators
   - Form styles with validation states
   - Button styles (primary, secondary, danger)
   - Modal styles with overlay
   - Toast notification styles
   - Loading spinner styles
   - Mobile-first responsive breakpoints

3. app.js - Main application with:
   - Hash-based router (window.onhashchange)
   - State management (current view, data cache, loading states)
   - Dynamic form generation from schema
   - Dynamic table generation from data
   - CRUD operations for EACH entity from ALL services
   - Pagination controls
   - Search/filter functionality
   - Toast notification system
   - Modal open/close handling
   - Event delegation for dynamic elements

   CRITICAL: The endpointsConfig array MUST include EVERY endpoint from the OpenAPI spec.
   Group them by tag/service. The OpenAPI spec contains paths from multiple services.
   You MUST generate handlers for ALL endpoints found in the spec.

   MANDATORY UI PATTERNS (apply dynamically based on OpenAPI spec):
   - For each tag/group, create a view with table for GET list endpoints
   - For each POST endpoint, create a modal form with fields from request schema
   - For each PUT endpoint, create edit action in table row + modal form
   - For each DELETE endpoint, create delete action in table row with confirmation
   - For each GET /{{id}} endpoint, create "Get by ID" button in view header that opens modal to enter ID and displays result
   - For each GET /{{id}} endpoint, also create "View" action button in table rows
   - Result display area (modal or inline) for single-item GET endpoints
   - For POST endpoints with query parameters, include those as form fields

4. api-client.js - MULTI-SERVICE API Client (CRITICAL):
   - Define a SERVICE_CONFIG object mapping each OpenAPI tag to its base URL (default to localhost:8000 for first service, localhost:8001 for second, etc.)
   - Create an ApiClient class that accepts a serviceConfig parameter
   - Each endpoint wrapper method MUST use the correct base URL from SERVICE_CONFIG based on its tag
   - Method signature: request(endpoint, options, tag) - uses tag to look up base URL
   - Include wrapper methods for EACH endpoint from ALL services with correct paths
   - Automatic JSON request/response handling
   - Error handling with detailed messages
   - Request/response interceptors
   - Query parameter building for GET requests
   - For POST endpoints with query parameters, send as query string in URL
   - NO duplicate path prefixes (use paths exactly from OpenAPI spec)

5. README.md with setup instructions including multi-service configuration

NAMING CONVENTIONS:
- CSS classes: kebab-case (e.g., .sidebar-nav, .data-table, .form-field)
- JS functions: camelCase (e.g., renderTable, showToast, fetchCustomers)
- HTML IDs: kebab-case (e.g., #customer-list, #customer-form)
- Data attributes: data-endpoint, data-method, data-schema

CRITICAL: Output ONLY valid JSON matching FrontendOutput schema. Ensure index.html starts with "<!DOCTYPE html>" (single <). No markdown formatting in the JSON values."""

FRONTEND_PROMPT = ChatPromptTemplate.from_messages([
    ("system", FRONTEND_SYSTEM_PROMPT),
    ("human", FRONTEND_HUMAN_PROMPT),
])