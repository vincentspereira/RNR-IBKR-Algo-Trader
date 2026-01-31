# SDLC MCP - Comprehensive Risk Analysis & Mitigation

## Risk Assessment Framework

**Risk Scoring**: Likelihood (1-5) × Impact (1-5) = Risk Score (1-25)

- **Critical** (20-25): Immediate action required
- **High** (15-19): Priority mitigation needed
- **Medium** (8-14): Planned mitigation
- **Low** (1-7): Monitor and accept

---

## Technical Risks

### R1: PostgreSQL Database Failure

**Likelihood**: 3 | **Impact**: 5 | **Risk Score**: 15 (HIGH)

**Risk**: PostgreSQL becomes unavailable, corrupting analytics and memory storage.

**Mitigation**:

1. **Connection Pooling**: Use `asyncpg` with min=5, max=20 connections
2. **Health Checks**: Ping database every 60s, auto-reconnect on failure
3. **Graceful Degradation**: Cache last 1000 invocations in Redis
4. **Local Fallback**: SQLite backup database for critical routing data

```python
class DatabaseManager:
    def __init__(self):
        self.pg_pool = None
        self.sqlite_fallback = sqlite3.connect('fallback.db')
        self.last_pg_check = None

    async def ensure_connection(self):
        if not self.pg_pool or not await self.health_check():
            try:
                self.pg_pool = await asyncpg.create_pool(...)
            except Exception:
                logger.error("PostgreSQL unavailable, using SQLite fallback")
                return self.sqlite_fallback
        return self.pg_pool
```

**Monitoring**: Alert if >3 connection failures in 5 minutes

---

### R2: Gemini API Rate Limiting / Outage

**Likelihood**: 4 | **Impact**: 4 | **Risk Score**: 16 (HIGH)

**Risk**: Gemini API hits rate limits (15 RPM) or experiences outages, blocking routing.

**Mitigation**:

1. **3-Tier Fallback**: Gemini → Custom LLM → IDE LLM → Rule-based
2. **Request Caching**: Cache Gemini responses for 1 hour in Redis
3. **Rate Limiting**: Client-side rate limiter (14 req/min max)
4. **Circuit Breaker**: After 3 failures, skip Gemini for 5 minutes

```python
class CircuitBreaker:
    def __init__(self, failure_threshold=3, timeout=300):
        self.failures = 0
        self.last_failure = None
        self.threshold = failure_threshold
        self.timeout = timeout

    async def call(self, func, *args):
        if self.is_open():
            raise CircuitOpenError("Circuit breaker open")

        try:
            result = await func(*args)
            self.reset()
            return result
        except Exception as e:
            self.record_failure()
            raise

    def is_open(self):
        if self.failures >= self.threshold:
            if time.time() - self.last_failure < self.timeout:
                return True
            self.reset()
        return False
```

**Fallback Measures**:

- Local Gemma 2 model (9B) for offline routing
- Rule-based routing with 90%+ accuracy for known patterns

---

### R3: Qdrant Vector Database Unavailable

**Likelihood**: 2 | **Impact**: 3 | **Risk Score**: 6 (MEDIUM)

**Risk**: Qdrant fails, disabling semantic memory search.

**Mitigation**:

1. **PostgreSQL pgvector Fallback**: Use PostgreSQL's vector extension
2. **In-Memory Cache**: Keep last 5000 vectors in memory (LRU)
3. **Degrade Gracefully**: Fall back to PostgreSQL full-text search

```python
async def search_memory(embedding):
    try:
        # Primary: Qdrant
        return await qdrant_client.search(...)
    except QdrantException:
        logger.warning("Qdrant unavailable, using pgvector")
        # Fallback: PostgreSQL pgvector
        return await pg_conn.fetch("""
            SELECT id, content,
                   1 - (embedding <=> $1) as similarity
            FROM shared_memory.embeddings
            WHERE 1 - (embedding <=> $1) > 0.7
            ORDER BY similarity DESC
            LIMIT 10
        """, embedding)
```

---

### R4: Neo4j Graph Database Failure

**Likelihood**: 2 | **Impact**: 2 | **Risk Score**: 4 (LOW)

**Risk**: Neo4j unavailable, losing knowledge graph capabilities.

**Mitigation**:

1. **Optional Feature**: Knowledge graph is enhancement, not critical path
2. **PostgreSQL Relations**: Store basic relationships in PostgreSQL as backup
3. **Rebuild Capability**: Can reconstruct graph from PostgreSQL data

**Impact**: Reduced relationship insights, no critical functionality lost

---

### R5: Redis Cache Failure

**Likelihood**: 2 | **Impact**: 2 | **Risk Score**: 4 (LOW)

**Risk**: Redis crashes, losing cache layer.

**Mitigation**:

1. **Performance Degradation Only**: System still works, just slower
2. **Direct Database Access**: Query PostgreSQL/Qdrant directly
3. **Auto-Reconnect**: Attempt reconnection every 30s

---

### R6: Docker Container Failures

**Likelihood**: 3 | **Impact**: 4 | **Risk Score**: 12 (MEDIUM)

**Risk**: Docker containers (PostgreSQL, Qdrant, Neo4j, Redis) deleted, corrupted, won't start, or volumes lost.

**Failure Scenarios**:
1. **Container deleted**: User accidentally runs `docker rm` or `docker-compose down -v`
2. **Container won't start**: Port conflicts, resource limits, corrupted image
3. **Volume corruption**: Disk issues, improper shutdown, file system corruption
4. **Network issues**: Docker network misconfiguration, DNS problems
5. **Resource exhaustion**: Out of disk space, memory limits exceeded

**Mitigation**:

1. **Docker Compose Health Checks**:
```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:17-alpine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 40s
    restart: unless-stopped  # Auto-restart on failure
    
  qdrant:
    image: qdrant/qdrant:v1.12.0
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
```

2. **Volume Backup Scripts**:
```bash
#!/bin/bash
# backup_docker_volumes.sh - Run daily via cron

BACKUP_DIR="/backups/docker-volumes/$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# Backup PostgreSQL data
docker exec sdlc-postgres pg_dumpall -U postgres > "$BACKUP_DIR/postgres_dump.sql"

# Backup Qdrant volume
docker run --rm \
  -v sdlc_qdrant_data:/source \
  -v "$BACKUP_DIR":/backup \
  alpine tar czf /backup/qdrant_data.tar.gz -C /source .

# Backup Neo4j volume
docker run --rm \
  -v sdlc_neo4j_data:/source \
  -v "$BACKUP_DIR":/backup \
  alpine tar czf /backup/neo4j_data.tar.gz -C /source .

echo "✅ Backup completed: $BACKUP_DIR"
```

3. **Automated Recovery Script**:
```python
import docker
import time

class DockerRecoveryManager:
    def __init__(self):
        self.client = docker.from_env()
        self.required_containers = [
            'sdlc-postgres', 'sdlc-qdrant', 
            'sdlc-neo4j', 'sdlc-redis'
        ]
    
    def check_and_recover(self):
        """Check container status and attempt recovery"""
        for container_name in self.required_containers:
            try:
                container = self.client.containers.get(container_name)
                
                if container.status != 'running':
                    logger.warning(f"{container_name} not running, attempting restart...")
                    container.restart()
                    time.sleep(10)  # Wait for startup
                    
                    # Verify health
                    container.reload()
                    if container.status == 'running':
                        logger.info(f"✅ {container_name} restarted successfully")
                    else:
                        logger.error(f"❌ {container_name} failed to restart")
                        self.rebuild_container(container_name)
                        
            except docker.errors.NotFound:
                logger.error(f"❌ {container_name} not found, recreating...")
                self.rebuild_container(container_name)
    
    def rebuild_container(self, container_name):
        """Rebuild container from docker-compose"""
        os.system(f"docker-compose up -d {container_name}")
```

4. **Fallback to Local PostgreSQL**:
```python
class DatabaseConnectionManager:
    def __init__(self):
        self.docker_postgres = None
        self.local_postgres = None
        self.fallback_active = False
    
    async def get_connection(self):
        """Try Docker PostgreSQL first, fallback to local"""
        try:
            if not self.docker_postgres:
                # Try Docker PostgreSQL (port 5432)
                self.docker_postgres = await asyncpg.create_pool(
                    host='localhost',
                    port=5432,
                    user='postgres',
                    password=os.getenv('POSTGRES_PASSWORD'),
                    database='sdlc_db'
                )
            
            # Test connection
            await self.docker_postgres.fetchval("SELECT 1")
            self.fallback_active = False
            return self.docker_postgres
            
        except Exception as e:
            logger.warning(f"Docker PostgreSQL unavailable: {e}")
            
            # Fallback to local PostgreSQL installation (port 5433)
            if not self.local_postgres:
                self.local_postgres = await asyncpg.create_pool(
                    host='localhost',
                    port=5433,  # Local PostgreSQL on different port
                    user='postgres',
                    database='sdlc_db_local'
                )
            
            self.fallback_active = True
            logger.info("Using local PostgreSQL fallback")
            return self.local_postgres
```

5. **Startup Verification**:
```bash
#!/bin/bash
# startup_check.sh - Run after docker-compose up

echo "🔍 Checking Docker containers..."

containers=("sdlc-postgres" "sdlc-qdrant" "sdlc-neo4j" "sdlc-redis")
all_healthy=true

for container in "${containers[@]}"; do
    if docker ps | grep -q "$container"; then
        health=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "unknown")
        echo "  $container: $health"
        
        if [ "$health" != "healthy" ] && [ "$health" != "unknown" ]; then
            all_healthy=false
        fi
    else
        echo "  ❌ $container: NOT RUNNING"
        all_healthy=false
    fi
done

if [ "$all_healthy" = true ]; then
    echo "✅ All containers healthy"
    exit 0
else
    echo "⚠️  Some containers unhealthy, attempting recovery..."
    python3 docker_recovery.py
    exit 1
fi
```

6. **Resource Monitoring**:
```python
def monitor_docker_resources():
    """Monitor Docker resource usage"""
    client = docker.from_env()
    
    for container in client.containers.list():
        stats = container.stats(stream=False)
        
        # Check disk usage
        if stats['storage_stats']['usage_bytes'] > 10 * 1024**3:  # >10GB
            logger.warning(f"{container.name}: High disk usage")
        
        # Check memory usage
        mem_usage = stats['memory_stats']['usage']
        mem_limit = stats['memory_stats']['limit']
        if mem_usage / mem_limit > 0.9:  # >90%
            logger.warning(f"{container.name}: High memory usage")
```

**Recovery Procedures**:

```bash
# Scenario 1: Container deleted - Rebuild
docker-compose up -d

# Scenario 2: Volume corrupted - Restore from backup
docker-compose down
docker volume rm sdlc_qdrant_data
docker volume create sdlc_qdrant_data
tar xzf /backups/qdrant_data.tar.gz -C /var/lib/docker/volumes/sdlc_qdrant_data/_data
docker-compose up -d

# Scenario 3: Port conflict - Change ports
# Edit docker-compose.yml, change port mapping
# ports: - "5433:5432" instead of "5432:5432"
docker-compose up -d

# Scenario 4: Full reset (nuclear option)
docker-compose down -v  # Remove volumes
rm -rf ./data/*  # Clear local data
./scripts/init_databases.sh  # Reinitialize
docker-compose up -d
```

**Monitoring**: 
- Health check every 60s
- Alert if any container unhealthy for >5 minutes
- Daily volume backups at 2 AM UTC
- Weekly backup verification tests

---

## Integration Risks

### R7: IDE Compatibility Issues

**Likelihood**: 4 | **Impact**: 4 | **Risk Score**: 16 (HIGH)

**Risk**: MCP server incompatible with one or more IDEs (Kilo Code, Copilot, Claude Code, Antigravity).

**Mitigation**:

1. **MCP Standard Compliance**: Strictly follow MCP 0.5.0 specification
2. **Multiple Transports**: Support SSE, HTTP, stdio
3. **Extensive Testing**: Test on all 4 IDE/ CLIs before release
4. **Fallback REST API**: Provide REST API as alternative to MCP

```python
# Support all MCP transports
if transport == "sse":
    app = FastAPI()
    @app.get("/sse")
    async def sse_endpoint():
        return EventSourceResponse(mcp_event_generator())

elif transport == "http":
    @app.post("/mcp")
    async def http_endpoint(request: MCPRequest):
        return handle_mcp_request(request)

elif transport == "stdio":
    async def stdio_handler():
        while True:
            line = await asyncio.get_event_loop().run_in_executor(
                None, sys.stdin.readline
            )
            response = handle_mcp_request(json.loads(line))
            print(json.dumps(response))
```

**Testing Plan**:

- Week 9: Test in Kilo Code (VS Code extension)
- Week 9: Test with GitHub Copilot Agent
- Week 9: Test with Claude Code CLI
- Week 9: Test in Google Antigravity

---

### R7: Routing Accuracy Below 80%

**Likelihood**: 3 | **Impact**: 4 | **Risk Score**: 12 (MEDIUM)

**Risk**: Routing algorithm selects wrong agents, reducing user trust.

**Mitigation**:

1. **User Feedback Loop**: "Was this routing helpful? (Y/N)"
2. **Confidence Thresholds**: Don't route if confidence <30%
3. **Show Alternatives**: Always show top 3 agent recommendations
4. **Learning System**: Track successful routes, boost trigger words

```python
async def route_with_feedback(task):
    routing = await router.route(task)

    if routing.confidence < 0.3:
        return {
            'status': 'low_confidence',
            'message': 'Unable to confidently route. Please rephrase or select manually.',
            'all_agents': router.list_agents()
        }

    return {
        'primary': routing.primary_agent,
        'confidence': routing.confidence,
        'alternatives': routing.alternatives[:3],
        'reasoning': routing.explanation
    }

async def record_feedback(invocation_id, helpful: bool):
    await db.execute("""
        UPDATE sdlc_analytics.agent_invocations
        SET feedback_score = $1, updated_at = NOW()
        WHERE id = $2
    """, 5 if helpful else 1, invocation_id)
```

**Monitoring**: Alert if avg routing score <0.6 for 7 days

---

### R8: LLM Costs Spiral Out of Control

**Likelihood**: 3 | **Impact**: 3 | **Risk Score**: 9 (MEDIUM)

**Risk**: Gemini API usage costs exceed budget ($100/month target).

**Mitigation**:

1. **Aggressive Caching**: Cache responses for 1 hour (dedup identical requests)
2. **Request Batching**: Batch up to 5 routing requests
3. **Cost Monitoring**: Track API calls, alert at $80 spending
4. **Token Limits**: Max 2000 tokens per request

```python
class CostMonitor:
    def __init__(self, monthly_budget=100.0):
        self.budget = monthly_budget
        self.spent = 0.0
        self.calls_this_month = 0

    def track_call(self, tokens_used, cost_per_1k_tokens=0.01):
        cost = (tokens_used / 1000) * cost_per_1k_tokens
        self.spent += cost
        self.calls_this_month += 1

        if self.spent > self.budget * 0.8:
            logger.warning(f"80% of monthly budget spent: ${self.spent:.2f}")

        return self.spent < self.budget
```

---

## Performance Risks

### R9: Memory Leaks from Connection Pools

**Likelihood**: 3 | **Impact**: 3 | **Risk Score**: 9 (MEDIUM)

**Risk**: Long-running MCP server leaks memory, crashes after hours/days.

**Mitigation**:

1. **Connection Pool Limits**: Max 20 connections per database
2. **Periodic Cleanup**: Close idle connections after 10 minutes
3. **Memory Monitoring**: Alert if RAM >2GB (normal <500MB)
4. **Automatic Restart**: Restart server if memory >3GB

```python
async def periodic_cleanup():
    while True:
        await asyncio.sleep(600)  # Every 10 minutes

        # Check memory usage
        process = psutil.Process()
        mem_mb = process.memory_info().rss / 1024 / 1024

        if mem_mb > 2048:
            logger.warning(f"High memory usage: {mem_mb:.0f}MB")

        if mem_mb > 3072:
            logger.critical("Memory limit exceeded, restarting...")
            os.execv(sys.executable, ['python'] + sys.argv)

        # Cleanup connections
        await pg_pool.clear()
        await redis_client.close()
        # Reconnect
        await initialize_connections()
```

---

### R10: Slow Routing (>5s Response Time)

**Likelihood**: 2 | **Impact**: 3 | **Risk Score**: 6 (MEDIUM)

**Risk**: Routing takes too long, degrading user experience.

**Mitigation**:

1. **Parallel Scoring**: Score all agents concurrently
2. **Redis Caching**: Cache routing decisions for identical requests
3. **Timeout Limits**: Abort LLM calls after 10s, use fallback
4. **Pre-computed Scores**: Pre-calculate agent scores for common patterns

```python
async def route_with_timeout(task, timeout=5.0):
    try:
        return await asyncio.wait_for(
            route_task(task),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.warning("Routing timeout, using cached result")
        return await get_cached_routing(task) or default_route(task)
```

**Target**: 95th percentile <2s, 99th percentile <5s

---

## Operational Risks

### R11: Project Auto-Prioritization Incorrect

**Likelihood**: 4 | **Impact**: 2 | **Risk Score**: 8 (MEDIUM)

**Risk**: Auto-detected priorities are wrong, wasting user time.

**Mitigation**:

1. **Always Show Reasoning**: Explain why priorities were chosen
2. **Easy Override**: One-command edit: `sdlc config edit-priorities`
3. **Conservative Defaults**: When uncertain, use balanced priorities
4. **User Confirmation Required**: Never commit without user approval

```python
async def auto_prioritize_with_confirmation(project_path):
    analysis = await analyze_project(project_path)

    print(f"\n🔍 Detected: {analysis['project_type']}")
    print(f"📋 Based on: {', '.join(analysis['indicators'])}\n")
    print(f"📊 Recommended Priorities:\n")

    for agent, priority in analysis['priorities'].items():
        print(f"  {agent}: {priority}")

    print(f"\nConfidence: {analysis['confidence']:.0%}")

    choice = input("\n[A]ccept / [E]dit / [S]kip: ")

    if choice.lower() == 'a':
        return analysis['priorities']
    elif choice.lower() == 'e':
        return await interactive_edit(analysis['priorities'])
    else:
        return default_priorities()
```

---

### R12: Agent Definition Conflicts

**Likelihood**: 2 | **Impact**: 3 | **Risk Score**: 6 (MEDIUM)

**Risk**: Multiple agents have overlapping triggers, causing routing conflicts.

**Mitigation**:

1. **Specialization Hierarchy**: Prefer more specialized agents
2. **Overlap Detection**: Alert if 2 agents have >70% trigger overlap
3. **Priority Tie-Breaking**: Use agent priority as tie-breaker
4. **Multi-Agent Mode**: Return top 3 when confidence spread <10%

---

### R13: Database Migration Failures

**Likelihood**: 2 | **Impact**: 4 | **Risk Score**: 8 (MEDIUM)

**Risk**: Schema updates fail, corrupting existing data.

**Mitigation**:

1. **Alembic Migrations**: Use versioned schema migrations
2. **Automatic Backups**: Backup database before each migration
3. **Rollback Scripts**: Every migration has a rollback
4. **Test Migrations**: Test on copy database first

```bash
# Migration workflow
alembic revision --autogenerate -m "add_agent_synergies_table"
pg_dump sdlc_db > backup_$(date +%Y%m%d).sql
alembic upgrade head

# If fails
alembic downgrade -1
psql sdlc_db < backup_$(date +%Y%m%d).sql
```

---

### R14: Security Vulnerabilities (API Key Leakage)

**Likelihood**: 3 | **Impact**: 5 | **Risk Score**: 15 (HIGH)

**Risk**: API keys exposed in logs, configs, or error messages.

**Mitigation**:

1. **Environment Variables Only**: Never hardcode keys
2. **Log Sanitization**: Redact keys from all logs
3. **.gitignore Protection**: Exclude .env, config.yaml
4. **Key Rotation**: Rotate keys every 90 days

```python
import re

class SecureLogger:
    SENSITIVE_PATTERNS = [
        r'(api[_-]?key["\s:=]+)([a-zA-Z0-9\-_]{20,})',
        r'(password["\s:=]+)([^\s"]+)',
        r'(token["\s:=]+)([a-zA-Z0-9\-_\.]{20,})'
    ]

    def sanitize(self, message):
        for pattern in self.SENSITIVE_PATTERNS:
            message = re.sub(pattern, r'\1***REDACTED***', message)
        return message

    def info(self, message):
        logger.info(self.sanitize(message))
```

---

### R15: Workflow Template Not Found

**Likelihood**: 3 | **Impact**: 2 | **Risk Score**: 6 (MEDIUM)

**Risk**: User request doesn't match any workflow template.

**Mitigation**:

1. **Fallback to Routing**: Use standard routing if no template matches
2. **Fuzzy Matching**: Use edit distance for template keywords
3. **Custom Workflows**: Allow users to define project-specific workflows

---

### R16: Memory System Partition Confusion

**Likelihood**: 2 | **Impact**: 2 | **Risk Score**: 4 (LOW)

**Risk**: ATS/OMA/SMC categorization causes memory isolation issues.

**Mitigation**:

1. **Cross-Category Search**: Enable searching across all categories
2. **Clear Documentation**: Explain category purposes
3. **Auto-Categorization**: Automatically assign agents to categories

---

### R17: MCP Installation Failures

**Likelihood**: 3 | **Impact**: 3 | **Risk Score**: 9 (MEDIUM)

**Risk**: Auto-installation of recommended MCPs fails due to network, permissions, or compatibility issues.

**Mitigation**:

1. **Pre-flight Checks**: Verify npm/pip available before installation
2. **Permission Detection**: Detect if sudo/admin rights needed
3. **Rollback**: Automatically rollback failed installations
4. **Manual Instructions**: Provide manual install commands on failure
5. **Offline Mode**: Allow manual MCP registration without auto-install

```python
class MCPInstaller:
    async def install_mcp(self, mcp_name: str):
        # Pre-flight checks
        if not self.check_package_manager():
            return InstallResult(
                success=False,
                message="npm not found. Install manually: npm install -g {mcp_name}"
            )
        
        # Try installation
        try:
            result = await asyncio.create_subprocess_exec(
                "npm", "install", "-g", mcp_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            
            if result.returncode == 0:
                return InstallResult(success=True)
            else:
                # Provide fallback instructions
                return InstallResult(
                    success=False,
                    message=f"Auto-install failed. Manual: npm install -g {mcp_name}"
                )
        except Exception as e:
            logger.error(f"MCP installation error: {e}")
            return InstallResult(success=False, message=str(e))
```

**Monitoring**: Track installation success rate per MCP

---

### R18: Privacy Data Leakage (User Isolation Failure) ⭐ NEW

**Likelihood**: 2 | **Impact**: 9 | **Risk Score**: 18 (CRITICAL)

**Risk**: User data accidentally exposed to other users due to improper isolation, causing GDPR violations and loss of trust.

**Mitigation**:

1. **Database-Level Isolation**:
   - **PostgreSQL**: User ID partitioning on all tables
   - **Qdrant**: Separate collections per user (`user_{uuid}_project`)
   - **Neo4j**: User namespace nodes with relationship constraints
   - **Redis**: Key prefixing with user ID

2. **Access Control**:
   - Every query MUST include `user_id` filter
   - Application-level access checks before DB queries
   - No cross-user queries allowed

3. **Encryption**:
   - Encryption at rest for all databases
   - User-specific encryption keys
   - Audit logging for all data access

4. **Testing**:
   - Integration tests for user isolation
   - Penetration testing for data leakage
   - Regular security audits

```python
class UserIsolatedMemoryManager:
    def __init__(self, user_id: str):
        self.user_id = user_id  # NEVER shared across users
        
    async def search_memory(self, query: str):
        # CRITICAL: Always filter by user_id
        results = await self.pg_pool.fetch(
            """
            SELECT * FROM memories 
            WHERE user_id = $1 AND content @@ to_tsquery($2)
            """,
            self.user_id,  # User isolation
            query
        )
        
        # Qdrant: Use user-specific collection
        collection_name = f"user_{self.user_id}_memory"
        vector_results = self.qdrant_client.search(
            collection_name=collection_name,
            query_vector=embedding,
            limit=10
        )
        
        return results
    
    async def add_memory(self, content: str):
        # Audit log: who accessed what
        await self.audit_log.record(
            user_id=self.user_id,
            action="add_memory",
            timestamp=datetime.utcnow()
        )
        
        # Store with user_id
        await self.pg_pool.execute(
            "INSERT INTO memories (user_id, content) VALUES ($1, $2)",
            self.user_id,
            content
        )
```

**Guarantees**:
- ✅ Your 10 projects help YOUR 11th project
- ❌ Other users CANNOT access your data
- ✅ GDPR compliant (right to be forgotten, data portability)

**Monitoring**: 
- Alert on any cross-user queries (should NEVER happen)
- Audit log review weekly
- Quarterly security audits

---

### R19: Port Conflicts (MCP Server Cannot Start) ⭐ NEW

**Likelihood**: 4 | **Impact**: 2 | **Risk Score**: 8 (MEDIUM)

**Risk**: Default port 8000 already in use, preventing MCP server from starting.

**Mitigation**:

1. **Smart Port Allocation**:
   - Try preferred port (8000)
   - Try ports 8001-8100 in sequence
   - Fall back to random available port (49152-65535)
   - Save chosen port to `.sdlc/server_info.json`

2. **User Override**:
   - CLI flag: `sdlc-mcp start --port 8500`
   - Config file: `.sdlc/config.yaml` → `server.port: 8500`
   - Environment variable: `SDLC_MCP_PORT=8500`

3. **IDE Auto-Discovery**:
   - Write port to `.sdlc/server_info.json`
   - IDEs read this file to discover server
   - No manual configuration needed

```python
class PortManager:
    DEFAULT_PORT = 8000
    PORT_RANGE = range(8000, 8101)  # 8000-8100
    
    def find_available_port(self, preferred_port: int = None) -> int:
        # User override takes priority
        if preferred_port:
            if self.is_port_available(preferred_port):
                return preferred_port
            else:
                raise PortUnavailableError(
                    f"Requested port {preferred_port} is in use"
                )
        
        # Try default
        if self.is_port_available(self.DEFAULT_PORT):
            return self.DEFAULT_PORT
        
        # Try range 8000-8100
        for port in self.PORT_RANGE:
            if self.is_port_available(port):
                logger.info(f"Port {self.DEFAULT_PORT} in use, using {port}")
                return port
        
        # Fallback to random high port
        random_port = self.get_random_port()
        logger.warning(f"All preferred ports busy, using random port {random_port}")
        return random_port
    
    def save_server_info(self, port: int):
        # Save for IDE auto-discovery
        server_info = {
            "port": port,
            "host": "localhost",
            "protocol": "http",
            "url": f"http://localhost:{port}"
        }
        
        with open(".sdlc/server_info.json", "w") as f:
            json.dump(server_info, f)
```

**User Experience**:
```bash
$ sdlc-mcp start
⚠️  Port 8000 is in use
✅ Using port 8023 instead
🚀 SDLC MCP Server running at http://localhost:8023
📝 Server info saved to .sdlc/server_info.json

# OR with override
$ sdlc-mcp start --port 9000
✅ Using port 9000
🚀 SDLC MCP Server running at http://localhost:9000
```

**Monitoring**: Track port selection statistics

---

## Monitoring & Alerting

### M1: Health Check Dashboard

```python
@app.get("/health")
async def health_check():
    health = {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'components': {}
    }

    # PostgreSQL
    try:
        await pg_pool.fetchval("SELECT 1")
        health['components']['postgresql'] = 'healthy'
    except:
        health['components']['postgresql'] = 'unhealthy'
        health['status'] = 'degraded'

    # Qdrant
    try:
        qdrant_client.get_collections()
        health['components']['qdrant'] = 'healthy'
    except:
        health['components']['qdrant'] = 'unhealthy'

    # ... check all components

    return health
```

### M2: Performance Metrics

```python
class PerformanceMonitor:
    def __init__(self):
        self.metrics = {
            'routing_times': [],
            'llm_call_times': [],
            'database_query_times': [],
            'total_requests': 0,
            'failed_requests': 0
        }

    def record_routing(self, duration_ms):
        self.metrics['routing_times'].append(duration_ms)
        self.total_requests += 1

        # Alert if p95 > 5000ms
        if self.p95_routing_time() > 5000:
            alert("Routing performance degraded", severity="warning")
```

### M3: Error Tracking

```python
class ErrorTracker:
    def __init__(self):
        self.errors = defaultdict(int)
        self.last_alert = {}

    def record_error(self, error_type, error_msg):
        self.errors[error_type] += 1

        # Alert if >10 errors of same type in 5 min
        if self.errors[error_type] > 10:
            if time.time() - self.last_alert.get(error_type, 0) > 300:
                alert(f"High error rate: {error_type}", severity="error")
                self.last_alert[error_type] = time.time()
```

---

## Testing Strategy

### T1: Unit Tests (Week 9)

```python
# Test routing accuracy
def test_routing_data_engineer():
    result = route("Implement Kafka event bus with 3 topics")
    assert result.primary_agent == "data-engineer"
    assert result.confidence > 0.7

def test_llm_fallback():
    with mock.patch('gemini_api.call', side_effect=TimeoutError):
        result = route("Complex task")
        assert result.llm_used == "custom" or result.llm_used == "rule_based"

# Test memory systems
@pytest.mark.asyncio
async def test_memory_storage():
    mem_id = await memory.add_memory(
        agent_id="data-engineer",
        content="Kafka requires ZooKeeper",
        memory_type=MemoryType.FACTUAL
    )

    results = await memory.search("kafka zookeeper")
    assert len(results) > 0
    assert mem_id in [r.id for r in results]
```

### T2: Integration Tests (Week 9)

```bash
# Test full routing pipeline
curl -X POST http://localhost:8000/route \
  -d '{"task": "Implement authentication", "project_path": "/ibkr"}' | \
  jq '.primary_agent' | grep -q "security-specialist"

# Test LLM fallback
curl -X POST http://localhost:8000/route \
  -H "X-Force-LLM: custom" \
  -d '{"task": "Test task"}' | \
  jq '.llm_used' | grep -q "custom"
```

### T3: IDE Testing (Week 9)

1. **Kilo Code (VS Code)**:

   - Install SDLC MCP in VS Code settings
   - Test: "Use agents to implement user login"
   - Verify: Correct agent selected, MCP tool invoked

2. **GitHub Copilot Agent**:

   - Configure SDLC MCP server
   - Test: "@sdlc route task: fix authentication bug"
   - Verify: Routing response received

3. **Claude Code CLI**:

   - Test: `claude-code "Use sub agents to optimize database queries"`
   - Verify: SDLC agents invoked correctly

4. **Google Antigravity**:
   - Test MCP integration in Antigravity UI
   - Verify: Natural language routing works

---

## Disaster Recovery

### DR1: Full System Failure

**Scenario**: All databases fail simultaneously.

**Recovery**:

1. **Graceful Degradation**: Route using rule-based fallback
2. **In-Memory Mode**: Keep last 1000 routes in memory
3. **Data Loss**: Accept loss of analytics (not critical path)
4. **Rebuild**: Restore from last backup

### DR2: Data Corruption

**Scenario**: PostgreSQL data corrupted.

**Recovery**:

1. **Daily Backups**: Automated at 2 AM UTC
2. **Point-in-Time Recovery**: WAL archiving enabled
3. **Validation**: Run integrity checks on restore

### DR3: API Key Compromise

**Scenario**: Gemini API key leaked.

**Recovery**:

1. **Immediate Rotation**: Generate new key in Google AI Studio
2. **Update Config**: Update .env file
3. **Restart Server**: Reload with new key
4. **Audit**: Review API usage for unauthorized calls

---

## Success Criteria

1. **Routing Accuracy**: >85% user satisfaction
2. **Performance**: p95 routing time <3s
3. **Reliability**: 99.9% uptime (43min downtime/month)
4. **IDE Compatibility**: Works on all 4 IDEs
5. **Cost**: <$50/month API costs
6. **Data Loss**: <1 hour of analytics data lost

---

For specific implementation details, see `FEATURE_DETAILS.md` and `SDLC_MCP_ARCHITECTURE.md`.
