# PromptDev - Testcontainers Setup

## What Changed

**Tests now use ephemeral testcontainers:**
- No manual DB setup scripts needed
- Each test run gets fresh isolated Postgres
- Random ports, auto cleanup
- 100% isolated from runtime

**Runtime uses docker-compose:**
- Port 5434 (not 5432, avoids conflicts)
- Persistent data
- Separate from tests

## Quick Start

### Run Tests
```bash
cd promptdev
make test
```

That's it. Testcontainers automatically:
1. Pulls postgres:16 (first time only)
2. Starts container on random port
3. Runs migrations
4. Runs tests
5. Stops and removes container

### Start Runtime
```bash
make dc-up
make db-migrate
```

## File Changes

**Tests (use testcontainers):**
- `tests/conftest.py` - Sets up ephemeral container
- `tests/test_db.py` - Uses testcontainer connection
- `scripts/migrate.py` - Reads TEST_DB_* env vars

**Runtime (use docker-compose):**
- `docker-compose.yml` - Postgres on port 5434
- `config.toml` - Points to docker services

**Removed:**
- `scripts/reset_test_db.sh` - Not needed
- `scripts/create_test_db.sh` - Not needed

## How It Works

### Tests
1. Pytest starts
2. `conftest.py` starts testcontainer
3. Sets `TEST_DB_HOST`, `TEST_DB_PORT`, etc in env
4. `migrate.py` reads env vars, connects to testcontainer
5. Tests run
6. Container destroyed

### Runtime
1. `docker compose up -d`
2. Postgres starts on port 5434
3. Backend connects via Docker network
4. Manual migrations: `make db-migrate`

## Verification

```bash
# Run tests (should see 13 passed)
make test

# Start runtime
make dc-up

# Check runtime DB
docker exec promptdev-postgres psql -U promptdev_user -d promptdev_db -c '\dt'
```

## Key Points

✅ **Tests are isolated** - Own container, own data, auto cleanup
✅ **Runtime is stable** - Persistent data, fixed port
✅ **No port conflicts** - Tests use random ports
✅ **No manual setup** - Testcontainers handles everything
✅ **Fast** - Container reuse when possible
