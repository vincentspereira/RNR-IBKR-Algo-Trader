# SDLC MCP - Detailed Feature Specifications

## 1. Intelligent Routing Engine

### 1.1 Weighted Scoring Algorithm

**Source**: `claude/docs/agent_routing_implementation.py` (Lines 460-548)

```python
def calculate_agent_score(agent, user_request, files, context):
    score = 0

    # Trigger words (10 points each)
    for trigger in agent.triggers:
        if trigger.lower() in user_request.lower():
            score += 10

    # File patterns (8 points each)
    for pattern in agent.file_patterns:
        if matches_glob(pattern, files):
            score += 8

    # Context matching (5 points)
    if context in agent.contexts:
        score += 5

    # Priority boost
    score += {
        'high': 2,
        'medium': 1,
        'low': 0
    }[agent.priority]

    # Historical performance (0-3 points)
    success_rate = get_success_rate(agent.id, days=30)
    if success_rate > 0.8:
        score += 3
    elif success_rate > 0.6:
        score += 2
    elif success_rate > 0.4:
        score += 1

    # Normalize to 0-1 confidence
    max_possible = 35
    confidence = min(score / max_possible, 1.0)

    return score, confidence
```

### 1.2 Agent Registry

All 21 agents with comprehensive metadata:

```python
AGENTS = {
    'code-implementer': {
        'triggers': ['implement', 'code', 'develop', 'build', 'create', 'fix', 'bug', 'feature'],
        'file_patterns': ['*.py', '*.js', '*.ts', '*.java', '*.go', '*.rs'],
        'contexts': ['development', 'implementation', 'bug-fix'],
        'priority': 'high',
        'specializations': ['coding', 'bug-fixing', 'feature-dev'],
        'pairs_with': ['test-engineer', 'code-reviewer']
    },
    'data-engineer': {
        'triggers': ['database', 'schema', 'migration', 'etl', 'pipeline', 'kafka', 'event', 'streaming'],
        'file_patterns': ['*.sql', 'migrations/*', '*kafka*', '*event*', 'alembic/*'],
        'contexts': ['data-modeling', 'database-work', 'streaming'],
        'priority': 'high',  # HIGH for IBKR project
        'specializations': ['data-pipelines', 'kafka', 'databases'],
        'pairs_with': ['backend-developer', 'devops-engineer']
    },
    # ... 19 more agents
}
```

---

## 2. Memory Systems (from Cognee)

**Cognee Overview**: Open-source memory engine that interconnects all data types (conversations, files, images, audio), replaces traditional RAG with unified memory layer (graphs + vectors), reduces developer effort and infrastructure costs while improving quality and precision.

**Source**: `enhanced-cognee/` repository + https://cognee.ai + https://github.com/topoteretes/cognee

### 2.1 Memory Categorization (Project-Specific)

**IMPORTANT**: Memory categorization is **project-specific** and **configurable**. Each project defines its own memory categories based on its domain and architecture.

**Implementation**:
```python
class ProjectMemoryConfig:
    """Memory categorization specific to each project"""
    
    # Example: Multi-Agent System Project
    MULTI_AGENT_CATEGORIES = {
        'ats': ['algorithmic-trading', 'risk-management', 'portfolio-optimizer'],
        'oma': ['code-reviewer', 'bug-detector', 'test-generator'],
        'smc': ['context-manager', 'knowledge-graph', 'message-broker']
    }
    
    # Example: IBKR Trading System Project
    IBKR_TRADING_CATEGORIES = {
        'trading': ['execution-engine', 'order-management', 'market-data'],
        'backtest': ['strategy-tester', 'performance-analyzer', 'optimizer'],
        'live': ['risk-monitor', 'compliance-checker', 'alert-system']
    }
    
    # Example: Web Application Project
    WEB_APP_CATEGORIES = {
        'frontend': ['ui-components', 'state-management', 'routing'],
        'backend': ['api-handlers', 'database-models', 'auth-service'],
        'shared': ['utils', 'types', 'constants']
    }
    
    @classmethod
    def get_categories(cls, project_type: str) -> dict:
        """Return memory categories for specific project type"""
        mapping = {
            'multi_agent_system': cls.MULTI_AGENT_CATEGORIES,
            'ibkr_trading': cls.IBKR_TRADING_CATEGORIES,
            'web_application': cls.WEB_APP_CATEGORIES
        }
        return mapping.get(project_type, cls.default_categories())
    
    @classmethod
    def default_categories(cls) -> dict:
        """Default categories for unknown project types"""
        return {
            'core': [],      # Core business logic
            'utils': [],     # Utility functions
            'shared': []     # Shared components
        }
```

**Project Detection & Configuration**:
```python
async def configure_memory_categories(project_path: str):
    """Auto-detect or configure memory categories for project"""
    
    # Auto-detect project type
    project_type = await detect_project_type(project_path)
    
    # Get appropriate categories
    categories = ProjectMemoryConfig.get_categories(project_type)
    
    # Save to project config
    config = {
        'project_path': project_path,
        'project_type': project_type,
        'memory_categories': categories
    }
    
    await save_to_file(f"{project_path}/.sdlc/memory_config.yaml", config)
    
    return categories
```

### 2.1.5 Cognee Core Features

**Multi-Data Type Support**:
```python
class CogneeDataIngest:
    """Supports 30+ data source types"""
    
    async def ingest_data(self, data_source, data_type):
        """
        Supported Data Types:
        - Text: conversations, docs, markdown, code
        - Files: PDF, Word, Excel, CSV, JSON
        - Images: PNG, JPG, screenshots (with OCR/vision models)
        - Audio: transcriptions, voice notes, meetings
        - Code: repositories, files, commits
        - Web: URLs, HTML, APIs (30+ integrations)
        """
        
        if data_type == 'image':
            # Extract text from images using vision models
            extracted_text = await self.image_to_text(data_source)
            return await cognee.add(extracted_text, dataset_id="images")
        
        elif data_type == 'audio':
            # Transcribe audio using Whisper or similar
            transcription = await self.audio_to_text(data_source)
            return await cognee.add(transcription, dataset_id="audio")
        
        elif data_type == 'code':
            # Use codify for code analysis (see section 2.6)
            return await self.codify_repository(data_source)
        
        else:
            # Standard text/file ingestion
            return await cognee.add(data_source)
```

**RAG Replacement with Unified Memory**:
```python
class UnifiedMemoryLayer:
    """
    Replaces traditional RAG systems with:
    - Graph-based relationships (Neo4j)
    - Vector similarity (Qdrant/pgvector)
    - Unified query interface
    """
    
    async def query(self, question: str, search_type="GRAPH_COMPLETION"):
        """
        Search Types:
        - GRAPH_COMPLETION: Use knowledge graph relationships
        - RAG_COMPLETION: Traditional vector search
        - CODE: Code-specific search (from codify)
        - CHUNKS: Raw chunk retrieval
        """
        results = await cognee.search(
            query_text=question,
            search_type=search_type
        )
        return results
```

**Cost Reduction & Developer Efficiency**:
- **Reduces infrastructure costs**: Single unified layer vs. multiple RAG systems
- **Reduces developer effort**: Pythonic pipelines vs. custom integrations
- **Improves quality**: Graph + vector hybrid > vector-only
- **Improves precision**: Relationship-aware search > similarity-only

### 2.6 Codify - Code Repository Analysis

**NEW**: Cognee's `codify` feature analyzes code repositories and builds code-specific knowledge graphs.

**Source**: `enhanced-cognee/cognee-mcp/src/server.py` (Lines 411-467)

```python
class CodeAnalysisEngine:
    """Analyze code repositories and build knowledge graphs"""
    
    async def codify_repository(self, repo_path: str):
        """
        Codify Pipeline:
        1. Scan repository for code files
        2. Extract: functions, classes, imports, dependencies
        3. Cognify: Build code graph with relationships
        4. Load: Store in Neo4j + vector embeddings
        
        Knowledge Graph Nodes:
        - Files, Functions, Classes, Variables
        - Imports, Dependencies, Modules
        
        Relationships:
        - CALLS, IMPORTS, INHERITS, USES
        - DEPENDS_ON, DEFINES, REFERENCES
        """
        
        # Start async codify pipeline
        result = await cognee.codify(repo_path)
        
        # Returns code graph structure
        return {
            'files_analyzed': result['file_count'],
            'functions': result['function_count'],
            'classes': result['class_count'],
            'relationships': result['edge_count'],
            'graph_id': result['graph_id']
        }
    
    async def search_code(self, query: str):
        """Search code using code graph"""
        return await cognee.search(
            query_text=query,
            search_type="CODE"  # Uses code graph
        )
    
    async def get_codify_status(self):
        """Check codify pipeline progress"""
        # Useful for large repos (background processing)
        return await cognee.codify_status()
```

**Use Cases**:
```python
# Example 1: Analyze SDLC Agent codebase
await codify_repository("/path/to/sdlc-agent")

# Example 2: Find function usage
results = await search_code("Where is calculate_agent_score used?")

# Example 3: Understand dependencies
results = await search_code("What files depend on routing_engine.py?")

# Example 4: Track status for large repos
status = await get_codify_status()
print(f"Progress: {status['progress']}% complete")
```

### 2.7 Modular ECL Pipelines & User-Defined Tasks

**ECL = Extract, Cognify, Load** (replaces ETL/ELT for AI memory)

```python
class ModularPipeline:
    """User-defined tasks in modular ECL pipelines"""
    
    def create_custom_pipeline(self, pipeline_config):
        """
        Users can define custom pipelines with:
        - Custom extractors (new data sources)
        - Custom cognify steps (domain-specific processing)
        - Custom loaders (new storage backends)
        """
        
        pipeline = [
            # Extract
            ExtractTask(source=pipeline_config['source'],
                       extractor=pipeline_config.get('custom_extractor')),
            
            # Cognify (customizable)
            CognifyTask(processors=pipeline_config.get('processors', [])),
            
            # Load
            LoadTask(targets=pipeline_config.get('targets', ['neo4j', 'qdrant']))
        ]
        
        return pipeline
```

**30+ Data Source Integrations**:
- **Databases**: PostgreSQL, MySQL, MongoDB, Redis, ClickHouse
- **Cloud Storage**: S3, GCS, Azure Blob, Dropbox
- **APIs**: REST, GraphQL, gRPC
- **Documents**: PDF, Word, Excel, PowerPoint, Markdown
- **Code**: GitHub, GitLab, Bitbucket, local repos
- **Communication**: Slack, Discord, Email, Teams  
- **Web**: Web scraping, RSS, Sitemap crawling
- **More**: See Cognee docs for complete list

**Built-in Search Endpoints**:
```python
# Cognee provides ready-to-use search endpoints
@app.post("/search")
async def search_memory(query: str, search_type: str):
    return await cognee.search(query, search_type=search_type)

@app.get("/datasets")
async def list_datasets():
    return await cognee.list_data()
```

### 2.2 Memory Types

```python
class MemoryType(Enum):
    FACTUAL = "factual"        # Facts and assertions
    PROCEDURAL = "procedural"  # How-to knowledge
    EPISODIC = "episodic"      # Event-based memories
    SEMANTIC = "semantic"      # Conceptual relationships
    WORKING = "working"        # Temporary context
```

### 2.3 PostgreSQL + pgvector Storage

```python
async def add_memory(agent_id, content, memory_type, embedding):
    # Store metadata in PostgreSQL
    await pg_conn.execute("""
        INSERT INTO shared_memory.documents
        (id, content, agent_id, memory_category, created_at)
        VALUES ($1, $2, $3, $4, $5)
    """, memory_id, content, agent_id, category, now())

    # Store embedding with pgvector
    await pg_conn.execute("""
        INSERT INTO shared_memory.embeddings
        (id, document_id, embedding, agent_id)
        VALUES ($1, $2, $3, $4)
    """, memory_id, memory_id, embedding, agent_id)
```

### 2.4 Qdrant Vector Search

```python
# Create collection per category
qdrant.create_collection(
    collection_name="cognee_ats_memory",
    vectors_config=VectorParams(size=1024, distance=Distance.COSINE)
)

# Search with filters
results = qdrant.search(
    collection_name="cognee_ats_memory",
    query_vector=embedding,
    query_filter=Filter(must=[
        FieldCondition(key="agent_id", match=MatchValue(value="data-engineer"))
    ]),
    limit=10,
    score_threshold=0.7
)
```

### 2.5 Neo4j Knowledge Graph

```python
# Create entity relationships
session.run("""
    MERGE (e1:Entity {name: $entity1})
    MERGE (e2:Entity {name: $entity2})
    MERGE (e1)-[r:RELATED_TO {
        type: $rel_type,
        confidence: $confidence,
        agent_id: $agent_id
    }]->(e2)
""", entity1="Kafka", entity2="Event Bus", rel_type="implements",
    confidence=0.9, agent_id="data-engineer")
```

---

## 3. Workflow Templates

**Source**: `claude/global-routing/USER_GUIDE.md` (Lines 240-364)

### 3.1 Pre-defined Workflows

```python
WORKFLOWS = {
    'new_feature': {
        'pattern': 'sequential',
        'agents': ['software-architect', 'code-implementer', 'test-engineer', 'code-reviewer'],
        'description': 'Architect → Implement → Test → Review'
    },
    'bug_fix': {
        'pattern': 'sequential',
        'agents': ['debug-specialist', 'code-implementer', 'test-engineer'],
        'description': 'Debug → Fix → Verify'
    },
    'code_review': {
        'pattern': 'parallel',
        'agents': ['code-reviewer', 'security-specialist', 'performance-optimizer'],
        'description': 'Simultaneous code, security, and performance review'
    },
    'api_development': {
        'pattern': 'sequential',
        'agents': ['software-architect', 'backend-developer', 'technical-writer', 'test-engineer'],
        'description': 'Design → Implement → Document → Test'
    },
    'deployment': {
        'pattern': 'sequential',
        'agents': ['code-reviewer', 'test-engineer', 'devops-engineer'],
        'description': 'Review → Test → Deploy'
    },
    'security_audit': {
        'pattern': 'parallel',
        'agents': ['security-specialist', 'code-reviewer', 'performance-optimizer'],
        'description': 'Security scan + Code review + Impact assessment'
    },
    'performance_optimization': {
        'pattern': 'sequential',
        'agents': ['performance-optimizer', 'code-implementer', 'test-engineer'],
        'description': 'Profile → Optimize → Benchmark'
    }
}
```

### 3.2 Workflow Detection

```python
def detect_workflow(user_request):
    request_lower = user_request.lower()

    if any(kw in request_lower for kw in ['new feature', 'add feature', 'implement feature']):
        return 'new_feature'
    elif any(kw in request_lower for kw in ['fix bug', 'debug', 'resolve issue']):
        return 'bug_fix'
    elif any(kw in request_lower for kw in ['review', 'analyze code']):
        return 'code_review'
    elif any(kw in request_lower for kw in ['api', 'endpoint', 'rest']):
        return 'api_development'
    elif any(kw in request_lower for kw in ['deploy', 'release', 'production']):
        return 'deployment'
    elif any(kw in request_lower for kw in ['security', 'vulnerability', 'audit']):
        return 'security_audit'
    elif any(kw in request_lower for kw in ['optimize', 'performance', 'slow']):
        return 'performance_optimization'

    return None
```

---

## 4. Monitoring & Alerts

**Source**: `claude/global-routing/core/monitoring_and_alerts.py`

### 4.1 Alert Types

```python
class AlertType(Enum):
    UNUSED_AGENT = "unused_agent"
    UNDERUSED_AGENT = "underused_agent"
    LOW_CONFIDENCE = "low_confidence"
    HIGH_OVERLAP = "high_overlap"
    PERFORMANCE_DEGRADATION = "performance_degradation"

# Alert 1: Unused Agent (14+ days no invocations)
def check_unused_agents():
    cutoff = datetime.now() - timedelta(days=14)
    unused = db.query("""
        SELECT agent_id, MAX(created_at) as last_used
        FROM sdlc_analytics.agent_invocations
        GROUP BY agent_id
        HAVING MAX(created_at) < $1 OR MAX(created_at) IS NULL
    """, cutoff)

    return [
        Alert(
            type=AlertType.UNUSED_AGENT,
            severity="warning",
            agent_id=row['agent_id'],
            message=f"Agent {row['agent_id']} unused for {days} days",
            action="flag_for_review"
        )
        for row in unused
    ]

# Alert 2: Underused Agent (<5% usage in 28 days)
def check_underused_agents():
    total_invocations = db.scalar("SELECT COUNT(*) FROM sdlc_analytics.agent_invocations WHERE created_at > NOW() - INTERVAL '28 days'")

    agent_usage = db.query("""
        SELECT agent_id, COUNT(*) as count
        FROM sdlc_analytics.agent_invocations
        WHERE created_at > NOW() - INTERVAL '28 days'
        GROUP BY agent_id
    """)

    return [
        Alert(
            type=AlertType.UNDERUSED_AGENT,
            severity="info",
            agent_id=row['agent_id'],
            message=f"Agent used only {(row['count']/total_invocations)*100:.1f}% of time",
            action="review_or_consolidate"
        )
        for row in agent_usage
        if (row['count'] / total_invocations) < 0.05
    ]

# Alert 3: Low Confidence (<40% avg confidence)
def check_low_confidence():
    low_conf = db.query("""
        SELECT agent_id, AVG(confidence_score) as avg_conf
        FROM sdlc_analytics.agent_invocations
        WHERE created_at > NOW() - INTERVAL '7 days'
        GROUP BY agent_id
        HAVING AVG(confidence_score) < 0.4
    """)

    return [Alert(...) for row in low_conf]

# Alert 4: High Overlap (>75% co-invocation)
def check_high_overlap():
    overlaps = db.query("""
        SELECT agent_1, agent_2,
               (co_invocation_count * 1.0 / total_invocations) as overlap_rate
        FROM sdlc_analytics.agent_synergies
        WHERE (co_invocation_count * 1.0 / total_invocations) > 0.75
    """)

    return [Alert(...) for row in overlaps]

# Alert 5: Performance Degradation (>20% slower)
def check_performance_degradation():
    degraded = db.query("""
        SELECT agent_id,
               AVG(CASE WHEN created_at > NOW() - INTERVAL '7 days'
                   THEN execution_time_ms END) as recent_avg,
               AVG(CASE WHEN created_at BETWEEN NOW() - INTERVAL '30 days'
                   AND NOW() - INTERVAL '7 days'
                   THEN execution_time_ms END) as baseline_avg
        FROM sdlc_analytics.agent_invocations
        GROUP BY agent_id
        HAVING recent_avg > baseline_avg * 1.2
    """)

    return [Alert(...) for row in degraded]
```

### 4.2 Weekly Reports

```python
def generate_weekly_report():
    return {
        'period': '7 days',
        'usage_summary': {
            'total_requests': count_invocations(days=7),
            'agents_used': count_unique_agents(days=7),
            'avg_score': avg_routing_score(days=7),
            'avg_confidence': avg_confidence(days=7)
        },
        'top_agents': get_top_agents(limit=5, days=7),
        'underperforming_agents': check_all_alerts(),
        'overlapping_agents': check_high_overlap(),
        'recommendations': generate_recommendations()
    }
```

---

## 5. LLM Integration

### 5.1 Gemini API (Primary)

```python
import google.generativeai as genai

class GeminiLLM:
    def __init__(self, api_key, model="gemini-2.5-pro"):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model)

    async def analyze_routing(self, user_request, agents, context):
        prompt = f"""
        Analyze this SDLC task and recommend the best agents:

        Task: {user_request}
        Available agents: {[a['name'] for a in agents]}
        Context: {context}

        Return JSON: {{"primary": "agent_id", "secondary": ["agent_id1", "agent_id2"], "reasoning": "why"}}
        """

        try:
            response = await asyncio.wait_for(
                self.model.generate_content_async(prompt),
                timeout=10.0
            )
            return parse_json(response.text)
        except asyncio.TimeoutError:
            raise LLMTimeoutError("Gemini timed out")
        except Exception as e:
            raise LLMError(f"Gemini failed: {e}")
```

### 5.2 Custom API (Secondary)

```python
class CustomLLM:
    def __init__(self, api_key, endpoint, model):
        self.api_key = api_key
        self.endpoint = endpoint
        self.model = model

    async def analyze_routing(self, user_request, agents, context):
        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": f"Analyze SDLC task and recommend agents:\n{user_request}"
            }]
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=10
            ) as resp:
                result = await resp.json()
                return parse_llm_response(result)
```

### 5.3 Fallback Chain

```python
class LLMManager:
    def __init__(self):
        self.primary = GeminiLLM(os.getenv("GEMINI_API_KEY"))
        self.secondary = CustomLLM(
            os.getenv("CUSTOM_LLM_API_KEY"),
            os.getenv("CUSTOM_LLM_ENDPOINT"),
            os.getenv("CUSTOM_LLM_MODEL")
        )
        self.fallback_rule_based = True

    async def analyze(self, user_request, agents, context):
        # Try Gemini
        try:
            result = await self.primary.analyze_routing(user_request, agents, context)
            logger.info("Routed using Gemini API")
            return result, "gemini"
        except (LLMTimeoutError, LLMError) as e:
            logger.warning(f"Gemini failed: {e}")

        # Try Custom API
        if self.secondary:
            try:
                result = await self.secondary.analyze_routing(user_request, agents, context)
                logger.info("Routed using Custom LLM API")
                return result, "custom"
            except Exception as e:
                logger.warning(f"Custom LLM failed: {e}")

        # Fallback to rule-based
        if self.fallback_rule_based:
            result = rule_based_routing(user_request, agents, context)
            logger.info("Routed using rule-based fallback")
            return result, "rule_based"

        raise NoLLMAvailableError("All LLMs failed")
```

---

## 6. Project Auto-Prioritization

```python
class ProjectAnalyzer:
    async def analyze_project(self, project_path):
        tech_stack = await self.detect_tech_stack(project_path)
        project_type = self.infer_project_type(tech_stack)
        agent_priorities = self.calculate_priorities(project_type, tech_stack)

        return {
            'project_path': project_path,
            'project_type': project_type,
            'tech_stack': tech_stack,
            'agent_priorities': agent_priorities
        }

    async def detect_tech_stack(self, project_path):
        stack = {
            'languages': [],
            'frameworks': [],
            'databases': [],
            'tools': []
        }

        # Check for language files
        if Path(project_path, 'package.json').exists():
            stack['languages'].append('JavaScript/TypeScript')
            stack['frameworks'].extend(self.parse_package_json())

        if Path(project_path, 'requirements.txt').exists():
            stack['languages'].append('Python')
            deps = Path(project_path, 'requirements.txt').read_text()
            if 'kafka' in deps:
                stack['tools'].append('Kafka')
            if 'fastapi' in deps:
                stack['frameworks'].append('FastAPI')

        if Path(project_path, 'Cargo.toml').exists():
            stack['languages'].append('Rust')

        # Check for databases
        if Path(project_path, 'docker-compose.yml').exists():
            compose = yaml.safe_load(Path(project_path, 'docker-compose.yml').read_text())
            for service in compose.get('services', {}):
                if 'postgres' in service:
                    stack['databases'].append('PostgreSQL')
                if 'redis' in service:
                    stack['databases'].append('Redis')

        return stack

    def calculate_priorities(self, project_type, tech_stack):
        priorities = {}

        if project_type == 'trading_system':
            priorities = {
                'data-engineer': 'high',
                'backend-developer': 'high',
                'security-specialist': 'high',
                'devops-engineer': 'medium',
                'performance-optimizer': 'medium',
                'test-engineer': 'medium',
                'mobile-developer': 'low'
            }
        elif project_type == 'web_application':
            priorities = {
                'frontend-developer': 'high',
                'backend-developer': 'high',
                'ui-ux-designer': 'high',
                'test-engineer': 'medium',
                'devops-engineer': 'medium',
                'mobile-developer': 'low'
            }
        # ... more project types

        return priorities

    async def present_to_user(self, analysis):
        print(f"\n🔍 Project Analysis Results\n")
        print(f"Project Type: {analysis['project_type']}")
        print(f"Tech Stack: {', '.join(analysis['tech_stack']['languages'])}")
        print(f"\n📊 Recommended Agent Priorities:\n")

        for agent_id, priority in sorted(analysis['agent_priorities'].items(),
                                         key=lambda x: {'high': 0, 'medium': 1, 'low': 2}[x[1]]):
            emoji = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}[priority]
            print(f"{emoji} {agent_id}: {priority.upper()}")

        choice = input("\n✅ Accept these priorities? (y/n/edit): ")

        if choice.lower() == 'y':
            await self.save_config(analysis)
        elif choice.lower() == 'edit':
            modified = await self.interactive_edit(analysis)
            await self.save_config(modified)
```

---

## 7. MCP Server Tools

```python
# Tool 1: Route Task
@mcp_server.tool()
async def route_task(task_description: str, project_path: str = None,
                     context: str = "", files: List[str] = None):
    """Route a task to the appropriate SDLC agent(s)"""
    routing_result = await router.route(
        task_description, project_path, context, files
    )
    return routing_result

# Tool 2: Get Recommendations
@mcp_server.tool()
async def get_agent_recommendations(task_description: str, limit: int = 5):
    """Get ranked agent recommendations for a task"""
    return await router.recommend_agents(task_description, limit)

# Tool 3: Get Analytics
@mcp_server.tool()
async def get_analytics(days: int = 7):
    """Get routing analytics and performance metrics"""
    return await analytics.generate_report(days)

# Tool 4: Record Execution
@mcp_server.tool()
async def record_execution(agent_id: str, execution_data: dict, project_path: str):
    """Record agent execution for learning"""
    await analytics.record_invocation(agent_id, execution_data, project_path)

# Tool 5: List Agents
@mcp_server.tool()
async def list_agents(category: str = None):
    """List all available SDLC agents"""
    return router.list_agents(category)

# Tool 6: Add Memory
@mcp_server.tool()
async def add_memory(agent_id: str, content: str, memory_type: str, metadata: dict = None):
    """Add memory entry for agent"""
    return await memory.add_memory(agent_id, content, memory_type, metadata)

# Tool 7: Search Memory
@mcp_server.tool()
async def search_memory(query: str, agent_id: str = None, limit: int = 10):
    """Search agent memory"""
    return await memory.search(query, agent_id, limit)
```

---

## 10. MCP Server Tools (v2.0) ⭐ Enhanced

### 10.1 Core Tools (7 Base + 4 Orchestration)

**Total**: 11 MCP Tools

#### Tool 1-7: Base Tools (from v1.0)

Already documented above (route_task, get_recommendations, get_analytics, record_execution, list_agents, add_memory, search_memory)

#### Tool 8: Discover MCPs ⭐ NEW (Phase 1.5)

```python
@mcp_server.tool()
async def discover_mcps(sources: list[str] = ["all"]) -> dict:
    """
    Discover installed MCP servers from multiple sources
    
    Args:
        sources: ["vscode", "claude", "global", "project", "all"]
    
    Returns:
        {
            "discovered": [
                {
                    "name": "github-mcp",
                    "url": "http://localhost:8001/sse",
                    "capabilities": ["PR", "issues", "search"],
                    "health": "healthy"
                },
                ...
            ],
            "total_found": 3
        }
    """
    return await mcp_discovery.discover(sources)
```

**Usage Example**:
```
User: "What MCPs do I have installed?"
→ Tool: discover_mcps(sources=["all"])
→ Result: "Found 3 MCPs: GitHub, Cognee, Docker"
```

#### Tool 9: Recommend MCPs ⭐ NEW (Phase 1.5)

```python
@mcp_server.tool()
async def recommend_mcps(project_path: str = None) -> dict:
    """
    Analyze project and recommend missing MCPs
    
    Returns:
        {
            "current_coverage": 0.30,
            "gaps": [
                {
                    "gap": "version_control",
                    "mcp": "github-mcp",
                    "priority": "high",
                    "reason": "Project on GitHub, 47 issues, 12 PRs",
                    "impact": "Saves 30-45 min/day",
                    "install_command": "npm install -g @modelcontextprotocol/server-github"
                },
                ...
            ]
        }
    """
    analysis = await project_analyzer.analyze(project_path)
    return await mcp_recommender.recommend(analysis)
```

**Usage Example**:
```
User: "What MCPs should I install?"
→ Tool: recommend_mcps(project_path=".")
→ Result: "🔴 HIGH: GitHub MCP (saves 30-45 min/day)
          🔴 HIGH: PostgreSQL MCP (saves 20-30 min/day)"
```

#### Tool 10: Install MCP ⭐ NEW (Phase 1.5)

```python
@mcp_server.tool()
async def install_mcp(mcp_name: str, auto_register: bool = True) -> dict:
    """
    Auto-install and register an MCP
    
    Args:
        mcp_name: MCP package name
        auto_register: Add to .sdlc/mcp-integration.yaml
    
    Returns:
        {
            "success": true,
            "installed": "github-mcp",
            "version": "1.0.0",
            "capabilities": ["PR", "issues", "search"],
            "registered": true
        }
    """
    result = await mcp_installer.install(mcp_name)
    
    if result.success and auto_register:
        await mcp_registry.register(mcp_name, result.url)
    
    return result
```

**Usage Example**:
```
User: "Install the recommended MCPs"
→ Tool: install_mcp(mcp_name="github-mcp", auto_register=True)
→ Result: "✅ GitHub MCP installed and registered
          📝 Updated .sdlc/mcp-integration.yaml"
```

#### Tool 11: Orchestrate Hybrid Workflow ⭐ NEW (Phase 2/6)

```python
@mcp_server.tool()
async def orchestrate_hybrid(
    task: str,
    use_internal: bool = True,
    use_external: bool = True,
    mode: str = "auto"  # "internal_only", "external_only", "hybrid", "auto"
) -> dict:
    """
    Orchestrate task using internal agents AND/OR external MCPs
    
    Args:
        task: User task description
        use_internal: Allow internal SDLC agents
        use_external: Allow external MCPs
        mode: Routing strategy
    
    Returns:
        {
            "routing_decision": "hybrid",
            "plan": [
                {
                    "step": 1,
                    "type": "internal",
                    "agent": "TestEngineer",
                    "action": "Run tests"
                },
                {
                    "step": 2,
                    "type": "external",
                    "mcp": "github-mcp",
                    "tool": "create_pr",
                    "action": "Create PR with test report"
                }
            ],
            "estimated_time": "3-5 minutes"
        }
    """
    analysis = await routing_engine.analyze_task(task)
    
    # Determine routing strategy
    if mode == "auto":
        mode = await routing_engine.determine_mode(analysis)
    
    # Create execution plan
    plan = await orchestrator.create_plan(
        task=task,
        mode=mode,
        use_internal=use_internal,
        use_external=use_external
    )
    
    return plan
```

**Usage Example**:
```
User: "Create a PR with test coverage report"
→ Tool: orchestrate_hybrid(task="...", mode="auto")
→ Decision: "Hybrid mode - use both internal + external"
→ Plan:
  Step 1: TestEngineer (internal) → Run tests
  Step 2: CodeReviewer (internal) → Analyze changes
  Step 3: GitHub MCP (external) → Create PR
```

### 10.2 Hybrid Orchestration Patterns

#### Pattern 1: Internal Only
```
Task: "Design database schema"
→ Route to: DataEngineer agent (internal)
→ Reason: Requires SDLC domain expertise
```

#### Pattern 2: External Only
```
Task: "Create GitHub PR"
→ Route to: GitHub MCP (external)
→ Reason: GitHub MCP specialized for this
```

#### Pattern 3: Hybrid (Most Powerful)
```
Task: "Deploy with performance analysis"
→ Orchestration:
  1. PerformanceOptimizer (internal) → Analyze performance
  2. Vercel MCP (external) → Deploy to Vercel
  3. Analytics Dashboard (internal) → Track metrics
```

### 10.3 MCP Capability Routing

```python
# Routing decision logic
def route_task_to_mcp_or_agent(task: str):
    # Analyze task requirements
    requirements = analyze_task(task)
    
    # Check if external MCP is better suited
    external_mcp = match_task_to_mcp(task, available_mcps)
    
    if external_mcp and external_mcp.confidence > 0.8:
        # Delegate to external MCP
        return delegate_to_external(external_mcp, task)
    
    elif external_mcp and requires_hybrid(task):
        # Use both internal agents AND external MCP
        return create_hybrid_plan(task, external_mcp)
    
    else:
        # Use internal SDLC agents
        return route_to_internal_agents(task)
```

### 10.4 Real-World Orchestration Example

```
User Request: "Use agents to improve authentication security and create PR"

SDLC MCP Analysis:
✅ Requires: Security (internal) + Code Review (internal) + GitHub (external)
🔄 Routing: Hybrid orchestration

Execution Plan:
┌─ Step 1 [Internal] SecuritySpecialist
│  └─ Action: Audit authentication code
│     └─ Result: Found 3 vulnerabilities, suggested fixes
│
├─ Step 2 [Internal] CodeImplementer  
│  └─ Action: Implement security fixes
│     └─ Result: Fixed vulnerabilities, added 2FA
│
├─ Step 3 [Internal] TestEngineer
│  └─ Action: Run security tests
│     └─ Result: All tests passed, coverage 92%
│
├─ Step 4 [Internal] CodeReviewer
│  └─ Action: Review changes
│     └─ Result: 2 suggestions (addressed)
│
└─ Step 5 [External] GitHub MCP
   └─ Tool: create_pr
   └─ Action: Create PR with security report
   └─ Result: PR #156 created
      └─ Title: "Security: Fix auth vulnerabilities + add 2FA"
      └─ URL: https://github.com/user/repo/pull/156

Total Time: 8 minutes
Orchestration: 4 internal agents + 1 external MCP = HYBRID ✅
```

---

See `RISK_ANALYSIS.md` for comprehensive risk mitigation strategies.
