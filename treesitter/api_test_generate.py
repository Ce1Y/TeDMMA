from langchain_openai import ChatOpenAI
import yaml

TARGET_ZIP_FILE = "spring-petclinic-main"

f = open("api_key.txt", "r")
API_KEY = f.read().strip()
f.close()

llm = ChatOpenAI(
    model="gpt-4.1-mini",
    api_key=API_KEY,
    temperature=0
)

def analyze_ast_features(ast_features):
    # system_prompt = f"""
    # # Role
    # You are a senior test development engineer and software architect specialized in Monolith-to-Microservices transformation.

    # # Task
    # Synthesize a microservices architecture design by analyzing the provided **AST-extracted features** of a monolithic Spring Boot application.

    # # Input Data Context
    # The input consists of structured Python-like dictionaries categorized by:
    # - Entities: Containing fields, types, and JPA annotations (e.g., @ManyToOne, @OneToMany) which indicate data coupling.
    # - Repositories: Linking managed entities to data access patterns.
    # - Services: Containing a dependencies list and method signatures, representing the core business logic and internal call chains.
    # - Controllers: Defining external endpoints and their immediate service/repository dependencies.
    # - DTOs: Defining the data transfer contract and schema.

    # # Analysis & Decision Logic
    # 1. Bounded Context Identification: Group Components (Controller, Service, Repository, Entity) into logical microservices based on:
    # - Domain Cohesion: Components sharing the same prefix or entity root (e.g., Beer, Order, Customer).
    # - Data Siloing: Identify which entities must stay together based on strong JPA relationships (@OneToMany vs. loose @ManyToOne).
    # 2. Inter-Service Communication Analysis:
    # - Analyze the dependencies list in each Service/Controller.
    # - If a Service in "Service A's Group" depends on a Service/Repository in "Service B's Group", mark this as a Sync/Async integration point.
    # - Differentiate between Logic Dependency (calling a Service) and Data Dependency (direct Repository access).

    # Interface & Schema Mapping:
    # - Map DTO fields to the proposed service interfaces.
    # - Identify "Shared Kernels" (e.g., BaseEntity, BaseItem) that might remain in a common library.

    # # Output Format
    # **STRICT DIRECTIVE: Output ONLY the analysis result following the structure below. Do not include any introductory remarks, conversational filler, or explanations outside the format.**
    # - **Service Map**:
    #     - [Proposed Microservice Name]: List of [Controllers, Services, Entities]
    # - **Dependency Graph**: [Source Service] -> [Target Service]:
    #     - Type: (REST/Message Queue)
    #     - Logic: [Reason based on AST dependencies or method calls]
    #     - Risk: (High/Medium/Low based on coupling degree)
    # - **Data Schemas**: [Service Name] API: Brief summary of key DTOs and critical fields.
    # """
    # === test prompt ===
    system_prompt ="""
# Role
You are a senior test development engineer and software architect specialized in Monolith-to-Microservices transformation.

# Task
Synthesize a production-ready microservices architecture design by analyzing the provided AST-extracted features of a monolithic Spring Boot application.

# Input Data Context
The input consists of structured Python-like dictionaries categorized by:
- Entities: Containing fields, types, and JPA annotations (e.g., @ManyToOne, @OneToMany) which indicate data coupling.
- Repositories: Linking managed entities to data access patterns.
- Services: Containing a dependencies list and method signatures, representing the core business logic and internal call chains.
- Controllers: Defining external endpoints and their immediate service/repository dependencies.
- DTOs: Defining the data transfer contract and schema.

# Analysis & Decision Logic
1. Bounded Context Identification (Data Siloing & Cohesion):
    - Enforce Database-per-Service: Every SQL table (Entity) MUST belong to exactly one microservice. No two services can manage or directly own the same Entity.
    - Flatten Inheritance: If entities inherit from base classes (e.g., BaseEntity, Person), map those parent fields directly into the child entity's schema.
    - Demote Hard Relations to Weak IDs: Transform legacy `@OneToMany` or `@ManyToMany` relationships across boundaries into primitive reference IDs (e.g., `ownerId` instead of an `Owner` object reference).
2. Inter-Service Communication Analysis (Directional Dependency):
    - Strict Directional Rule: The dependency arrow MUST flow from [Caller Service (Client)] -> [Callee Service (Server)]. If Controller/Service X references Repository/Service Y, X depends on Y.
    - Circular Dependency Elimination: If Service A depends on Service B, and Service B simultaneously depends on Service A, you MUST resolve this by introducing an API Gateway / BFF (Backend-for-Frontend) layer for aggregation, or merge them.
    - Shared Kernels: Identify cross-cutting abstract classes (e.g., `BaseEntity`) as Shared Libraries, not as independent runtime microservices.

# Constraints
- STRICT DIRECTIVE: Output ONLY the analysis result following the structured format below. 
- NO PROSE: Do not include any introductory remarks, conversational filler, selection logic justification, or closing summaries. Start directly with "- **Service Map**:".
- Metric Enforcement: You must explicitly compute the Outdegree Score (the count of external microservices this service synchronously invokes) for each service.

# Output Format
- **Service Map**:
    - [Proposed Microservice Name]:
        - Controllers: [List of Controllers]
        - Services: [List of Services]
        - Entities: [List of Entities strictly owned by this service]
        - Shared Libraries: [List of abstract classes or common utilities imported]
- **Dependency Graph**:
    - [Caller Microservice Name] -> [Callee Microservice Name]:
        - Type: (REST / gRPC / Message Queue)
        - Logic: [Exact AST class/method reference causing this network invocation]
        - Risk: (High/Medium/Low based on blocking synchronous calls or transactional coupling)
- **Data Schemas**:
    - [Microservice Name] API DTOs:
        - [DTO Name]: [Flattened fields with primitive ID references instead of object graphs]
"""
    
    
    user_input = f"""
    # AST Metadata Input
    ```json
    {ast_features}
    ```
    """
    
    messages = [
        ("system", system_prompt),
        ("human", user_input),
    ]
    
    analysis_response = llm.invoke(messages)
    print(analysis_response.content)
    return analysis_response.content

def generate_api_test(analyzed_ast, test_case, expected_endpoint): 
    prompt = f"""
# Role
You are a Senior Software Engineer specialized in TDD (Test-Driven Development) and Karate DSL, with expertise in Monolith-to-Microservices refactoring.

# Goal
Identify the microservice with the absolute lowest coupling (Leaf Service) from the Monolithic Analysis and implement a "Testing-First" TDD baseline using Karate DSL. 
The generated API tests MUST strictly align with the new microservice architecture defined in the expected endpoint specification.

# Context & Input
1. Monolith Architecture Analysis Report (Legacy service boundaries, dependency graph):
    '''
    {analyzed_ast}
    '''
2. Legacy Source Artifacts (Legacy Unit Tests, DTOs, Mermaid):
    '''
    {test_case}
    '''
3. Expected Microservice Specification (The Single Source of Truth for target endpoints, schemas, and errors):
    '''
    {expected_endpoint}
    '''

# Task: Service Identification & API Testing Generation
Please perform the following steps:
1. Dependency Analysis (Leaf Service Discovery)
    - Identify the "Leaf Service": Analyze the provided Call Graph and Service Map from the Monolith Analysis. Select the service with the lowest Outdegree (the one that calls the fewest, preferably zero, other internal services) that maps to a service defined in the Expected Microservice Specification.
2. API Testing Generation: For that specific identified service, generate the Karate Gherkin features for all its defined endpoints as the baseline for TDD.

# Implementation Rules
## Karate (Behavioral Testing)
- **Format**: `.feature` files. Organize endpoints into logical feature files (e.g., one file per resource domain or main controller flow).
- **Strict Adherence to Expected Specification**:
    - **Endpoint Mapping**: Use the base path, paths, methods, and parameters defined *only* in `expected_microservice.yaml`. Do NOT legacy `@RequestMapping` paths from the AST if they conflict.
    - **Schema Validation (Fuzzy Matching)**: Do NOT use hardcoded response values for validation. You MUST use Karate fuzzy matchers (e.g., `#string`, `#number`, `#boolean`, `#array`, `##string` for nullable fields) to validate response payloads against the schema defined in `expected_microservice.yaml`.
- **Test Case Rules**:
    - Use `Background` to define the base `url` (default: http://localhost:8080).
    - **Happy Path**: Implement the critical "Happy Path" based on business logic and expected success response schemas.
    - **Negative / Error Path**: Include at least one negative test case (e.g., 400 Bad Request, 401 Unauthorized, 404 Not Found). The error response body (e.g., Error DTO, message structure) MUST match the error schema defined in `expected_microservice.yaml`, not the legacy Monolith error format.

# Constraints
- STRICT DIRECTIVE: Output ONLY the result in the format specified below.
- NO PROSE: Do not include any introductory remarks, selection logic, explanations, summary, or closing text.
- No Hallucinations: Only use field names and structures found in `expected_microservice.yaml`. If fields are missing in the specification, mark it as [Insufficient information: Missing X] and suggest a logical default based on the legacy domain context.

# Output Format

### [Service Identification]
- **Target Service**: [Service Name]

### [Artifacts: Karate API Testing]
- **File Name**: src/test/resources/[service-name]/karate/[feature-name].feature
- **Testing Code**:
"""

    response = llm.invoke(prompt)
    print(response.content)
    
### test ###
def analyze_pure_test(pure_text):
    system_prompt = f"""
    # Role
You are a top-tier Software Architect and Static Code Analysis Expert, specializing in the Domain-Driven Design (DDD) methodology for decomposing monolithic architectures into microservices. You excel at assessing system coupling through the concepts of Abstract Syntax Trees (AST), code dependencies, and data models.

# Task
Please analyze the monolithic system source code (or architectural description) I provide, logically decompose and refactor it into a microservices architecture, and strictly output the Service Map, Dependency Graph, and Data Schemas according to the specified format.

# Constraints & Guidelines
When performing the analysis, you must strictly adhere to the following principles:
1. **Service Map Ownership Principle**: Each Controller, Service, and Entity must be clearly assigned to a single "Proposed Microservice" based on bounded contexts; overlapping or duplicate assignments are not allowed. Shared Libraries refer to abstract classes or common utilities imported across multiple services.
2. **Dependency Graph Networking Principle**: After the monolith is split, original in-process calls will become network calls. Please evaluate the invocation type (REST / gRPC / Message Queue) and precisely pinpoint the exact AST class/method causing this network invocation. Risk assessment standards are as follows:
   - High: Blocking synchronous calls (e.g., chained REST calls) or cross-service distributed transactions (transactional coupling).
   - Medium: Standard synchronous calls.
   - Low: Asynchronous decoupling via Message Queues.
3. **Data Schemas Flattening Principle**: API DTOs between microservices must be decoupled. Please flatten complex object graphs (such as ORM `@OneToMany` associations) and replace entity object references with primitive ID references (e.g., `userId: Long`).

---

# Output Format
Please output strictly in the following format, without any prefaces, postscripts, or additional explanations:

- **Service Map**:
    - [Proposed Microservice Name]:
        - Controllers: [List of Controllers]
        - Services: [List of Services]
        - Entities: [List of Entities strictly owned by this service]
        - Shared Libraries: [List of abstract classes or common utilities imported]
- **Dependency Graph**:
    - [Caller Microservice Name] -> [Callee Microservice Name]:
        - Type: (REST / gRPC / Message Queue)
        - Logic: [Exact AST class/method reference causing this network invocation]
        - Risk: (High/Medium/Low based on blocking synchronous calls or transactional coupling)
- **Data Schemas**:
    - [Microservice Name] API DTOs:
        - [DTO Name]: [Flattened fields with primitive ID references instead of object graphs]
    """

    user_input = f"""
    # Source Code Input
    ```json
    {pure_text}
    ```
    """
    
    messages = [
        ("system", system_prompt),
        ("human", user_input),
    ]
    
    analysis_response = llm.invoke(messages)
    print(analysis_response.content)
    return analysis_response.content