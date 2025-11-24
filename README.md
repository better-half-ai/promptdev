# PromptDev

Prompt engineering workbench for AI companion applications. Operators manage templates, monitor conversations, and intervene in real-time.

---

## Quick Start

### Local Installation

```bash
# Clone repository
git clone https://github.com/better-half-ai/promptdev.git
cd promptdev

# Start services
docker compose up -d

# Initialize database
docker compose exec postgres psql -U promptdev -d promptdev << SQL
\i /migrations/001_init.sql
\i /migrations/002_prompts_schema.sql
\i /migrations/003_guardrails_schema.sql
\i /migrations/004_telemetry_schema.sql
SQL

# Verify running
curl http://localhost:8001/health

# Open operator dashboard
open http://localhost:8001/
```

### Remote Deployment

```bash
# On remote server
git clone https://github.com/better-half-ai/promptdev.git
cd promptdev

# Configure environment
cp .env.example .env
nano .env  # Set DATABASE_URL, LLM_BASE_URL, etc.

# Deploy
docker compose -f docker-compose.yml up -d

# Access via
http://your-server-ip:8001/
```

---

## Usage

### For Operators

#### 1. Access Dashboard
Open http://localhost:8001/ in your browser.

Three main sections:
- **Dashboard** - Overview statistics
- **Personalities** - Manage templates
- **Monitor** - View conversations

#### 2. Create a Template

1. Click **Personalities** in sidebar
2. Click **+ New Personality** button
3. Fill in form:
   - **Name**: e.g., "companion"
   - **Content**: Jinja2 template with variables
   ```
   You are a helpful companion.
   
   User context: {{user_context}}
   Conversation history: {{conversation_history}}
   ```
4. Click **Create**

Template is now available for users.

#### 3. View & Edit Templates

1. In **Personalities** view, see all templates
2. Each template shows:
   - Name
   - Version number
   - Status (ACTIVE/INACTIVE badge)
   - Last updated
3. Click **Edit** to modify
4. Click **History** to see all versions
5. Click **Activate/Deactivate** to toggle

Every edit creates a new version. Old versions are preserved.

#### 4. Rollback Template

1. Click template → Click **History**
2. See all versions with timestamps
3. Click **Rollback to v2** (for example)
4. Confirm rollback

System creates new version with old content.

#### 5. Monitor Conversations

1. Click **Monitor** in sidebar
2. See all users with:
   - User ID
   - Message count
   - Last activity
   - State badge (🟢 ACTIVE or 🔴 HALTED)
3. Click user to view full conversation

#### 6. Halt a Conversation

When you need to review before AI responds:

1. In **Monitor** view, click user
2. Click **Halt** button (top or sidebar)
3. Enter reason: "Review needed"
4. Click **Confirm**

User badge turns RED. AI stops responding.

#### 7. Resume Conversation

1. In halted conversation view
2. Click **Resume** button
3. Confirm

User badge turns GREEN. AI resumes.

#### 8. Inject Message

To add context mid-conversation:

1. In conversation view
2. Click **Inject** button
3. Type message (e.g., "The user prefers formal tone")
4. Click **Send**

Message added to conversation history. AI sees it.

### For End Users

#### Access Chat
Open http://localhost:8001/static/index.html

#### Send Message
1. Type message in text box
2. Press Enter or click Send
3. AI responds based on active template

#### View History
Scroll up to see previous messages.

All conversations are saved per user_id.

---

## How It Works

### Template System

Templates use Jinja2 syntax:

```jinja2
You are {{personality_type}}.

User information:
- Name: {{user_name}}
- Preferences: {{user_preferences}}

Recent conversation:
{{conversation_history}}

Instructions:
- Be helpful and friendly
- Remember user context
```

Variables are populated automatically:
- `{{user_context}}` - User memory (key-value pairs)
- `{{conversation_history}}` - Last N messages
- Custom variables from user memory

### Conversation Flow

```
User sends message
    ↓
Backend checks user state
    ↓
If halted → Return "Conversation paused"
If active → Continue
    ↓
Load template for user
    ↓
Get user memory & history
    ↓
Build prompt from template
    ↓
Call Mistral LLM
    ↓
Save response to history
    ↓
Return to user
```

### Interventions

Operators can intervene at any time:

- **Halt**: Stop AI responses, review conversation
- **Resume**: Allow AI to respond again
- **Inject**: Add context/instructions mid-conversation

### Version Control

Every template update:
1. Creates new version (v1 → v2 → v3)
2. Saves old version in history
3. Allows rollback to any previous version

---

## Development

### Run Tests

```bash
# Install dependencies
uv sync

# Run all 298 tests
uv run pytest tests/ -v

# Run specific module
uv run pytest tests/test_prompts.py -v

# With coverage
uv run pytest tests/ --cov=src --cov-report=html
open htmlcov/index.html
```

**Test breakdown:**
- `test_llm_client.py`: 28 tests - HTTP client, retries
- `test_prompts.py`: 71 tests - Templates, versioning
- `test_memory.py`: 45 tests - Conversations, storage
- `test_context.py`: 32 tests - Prompt assembly
- `test_guardrails.py`: 38 tests - Safety rules
- `test_main.py`: 52 tests - API endpoints
- `test_telemetry.py`: 18 tests - Metrics
- `test_integration_e2e.py`: 14 tests - Full flows

All tests use real PostgreSQL via testcontainers (no mocks).

### Local Development

```bash
# Start services
docker compose up -d

# Watch logs
docker compose logs -f backend

# Restart after code changes
docker compose restart backend

# Access database
docker compose exec postgres psql -U promptdev -d promptdev
```

### Debug

```bash
# Backend logs
docker compose logs backend --tail 100

# Test API
curl http://localhost:8001/health
curl http://localhost:8001/admin/users | jq

# Check database
docker compose exec postgres psql -U promptdev -d promptdev -c "SELECT * FROM system_prompt;"
```

---

## API Examples

### Create Template
```bash
curl -X POST http://localhost:8001/admin/templates \
  -H "Content-Type: application/json" \
  -d '{
    "name": "companion",
    "content": "You are a helpful companion.\n\nContext: {{user_context}}",
    "created_by": "admin"
  }'
```

### Send Chat Message
```bash
curl -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user123",
    "message": "Hello!",
    "template_name": "companion"
  }'
```

### List All Users
```bash
curl http://localhost:8001/admin/users | jq
```

### Halt Conversation
```bash
curl -X POST http://localhost:8001/admin/interventions/user123/halt \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "admin",
    "reason": "Review needed"
  }'
```

### View Conversation
```bash
curl http://localhost:8001/admin/conversations/user123 | jq
```

Full API reference: http://localhost:8001/docs

---

## Database

### Schema
- `conversation_history` - All messages
- `user_memory` - Key-value storage (JSONB)
- `user_state` - Active/halted status
- `system_prompt` - Templates
- `prompt_version_history` - Version audit
- `guardrail_configs` - Safety rules
- `llm_requests` - Request logs
- `metrics_aggregated` - Statistics

### Access
```bash
# Connect
docker compose exec postgres psql -U promptdev -d promptdev

# List tables
\dt

# Query templates
SELECT id, name, current_version, is_active FROM system_prompt;

# View conversations
SELECT user_id, role, content, created_at 
FROM conversation_history 
WHERE user_id = 'user123' 
ORDER BY created_at DESC 
LIMIT 10;
```

### Migrations
```bash
# Create new migration
cat > migrations/005_new_feature.sql << SQL
-- Your SQL here
CREATE TABLE ...;
SQL

# Apply
docker compose exec postgres psql -U promptdev -d promptdev -f /migrations/005_new_feature.sql
```

---

## Configuration

**config.toml:**
```toml
[llm]
base_url = "http://mistral:8080"
timeout = 120.0
max_retries = 3

[database]
host = "postgres"
port = 5432
database = "promptdev"
user = "promptdev"
password = "promptdev"
pool_size = 10
```

**.env:**
```bash
POSTGRES_PASSWORD=promptdev
LLM_BASE_URL=http://mistral:8080
```

---

## Production Deployment

**Current Status: STAGING READY**

### Required Before Production

**Critical:**
- [ ] Add authentication (JWT/API keys/OAuth)
- [ ] Add rate limiting (per user, per IP)
- [ ] Enable HTTPS with TLS certificates
- [ ] Set up automated database backups
- [ ] Configure monitoring (Prometheus/Grafana)
- [ ] Secure environment variables
- [ ] Set CORS to specific origins

**Recommended:**
- [ ] Add request logging/audit trail
- [ ] Implement streaming responses
- [ ] Add conversation expiry/cleanup
- [ ] Load test telemetry system
- [ ] Set up error alerting
- [ ] Add health checks for load balancer

### Deploy to Production

```bash
# On production server
git clone https://github.com/better-half-ai/promptdev.git
cd promptdev

# Configure
cp .env.example .env
nano .env  # Set production values

# Deploy
docker compose -f docker-compose.yml up -d

# Check
curl https://your-domain.com/health

# View logs
docker compose logs -f
```

---

## Troubleshooting

**Backend won't start:**
```bash
docker compose logs backend
# Look for import errors, database connection issues
```

**Dashboard returns 404:**
```bash
docker compose exec backend ls -la /app/static/
# Verify static files exist
# Check main.py has static mount
```

**Database connection errors:**
```bash
docker compose exec postgres psql -U promptdev -d promptdev -c "SELECT 1;"
# Verify credentials in config.toml
```

**Templates not activating:**
```bash
curl -X POST http://localhost:8001/admin/templates/1/activate
# Check response status
# Verify endpoint exists in main.py
```

**Tests failing:**
```bash
# Install dependencies
uv pip install testcontainers pytest-asyncio

# Check Docker is running
docker ps

# Run with verbose output
uv run pytest tests/ -vv -s
```

---

## Project Structure

```
promptdev/
├── src/
│   ├── main.py           # FastAPI app (33 endpoints)
│   ├── prompts.py        # Template management
│   ├── memory.py         # Conversation storage
│   ├── context.py        # Prompt assembly
│   ├── guardrails.py     # Safety rules
│   ├── llm_client.py     # Mistral HTTP client
│   ├── telemetry.py      # Metrics tracking
│   └── config.py         # Config loader
├── static/
│   ├── dashboard.html    # Operator dashboard
│   ├── monitor.html      # Conversation monitor
│   ├── editor.html       # Template editor
│   └── index.html        # User chat
├── tests/                # 298 tests
├── migrations/           # Database schema
├── db/                   # Database utilities
├── scripts/              # Deployment scripts
├── models/               # LLM files (10GB+)
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

---

## Support

**Issues:**
1. Check logs: `docker compose logs backend`
2. Test API: `curl http://localhost:8001/health`
3. Verify database: `docker compose exec postgres psql -U promptdev`
4. Review tests for examples

**Documentation:**
- API docs: http://localhost:8001/docs
- Test files: See `tests/` for usage examples
- Database schema: See `migrations/*.sql`

---

## Contributing

1. All code changes require tests
2. Tests must use real databases (no mocks)
3. Use `uv` for dependency management
4. Run full test suite before committing

```bash
# Before committing
uv run pytest tests/ -v
uv run ruff check src/
uv run mypy src/
```
