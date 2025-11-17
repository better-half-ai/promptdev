# Complete Update - .env Automation + Cloud Deployment

## What This Update Does

✅ Automates `.env` creation with secure passwords  
✅ Integrates `.env` setup into Makefile  
✅ Fixes Docker Compose for cloud VM deployment  
✅ Adds deployment automation script  
✅ Protects `.env` from being committed  

## Files to Add/Update

### 📝 New Files (Add to repo)

1. **[scripts/setup_env.sh](computer:///mnt/user-data/outputs/setup_env.sh)** 
   - Auto-generates `.env` with secure passwords
   - Sets proper permissions (chmod 600)
   ```bash
   chmod +x scripts/setup_env.sh
   ```

2. **[.gitignore](computer:///mnt/user-data/outputs/.gitignore)**
   - Protects `.env` from being committed
   - Replace or merge with existing

3. **[QUICKSTART.md](computer:///mnt/user-data/outputs/QUICKSTART.md)**
   - Quick reference for cloud deployment

### 🔧 Updated Files (Replace existing)

4. **[Makefile](computer:///mnt/user-data/outputs/Makefile_updated)**
   - New targets: `setup`, `deploy`, `.env`
   - All relevant targets now depend on `.env`
   - New Docker and DB utilities

5. **[scripts/deploy.sh](computer:///mnt/user-data/outputs/deploy_updated.sh)**
   - Uses Makefile for `.env` setup
   - Cleaner, more modular
   ```bash
   chmod +x scripts/deploy.sh
   ```

6. **[docker-compose.yml](computer:///mnt/user-data/outputs/docker-compose.yml)**
   - Named volumes (not `./pgdata`)
   - No hardcoded passwords
   - Private network
   - No exposed DB port
   - Health checks

7. **[config.toml](computer:///mnt/user-data/outputs/config.toml)**
   - Updated DB host: `postgres` (for Docker networking)
   - Updated Mistral host: `mistral`

### 📚 Documentation (Optional)

8. **[DEPLOYMENT.md](computer:///mnt/user-data/outputs/DEPLOYMENT.md)**
   - Comprehensive deployment guide

## Installation Order

```bash
# 1. Add new files
cp setup_env.sh scripts/
chmod +x scripts/setup_env.sh scripts/deploy.sh

# 2. Update .gitignore (merge with existing if needed)
cp .gitignore .

# 3. Replace existing files
cp Makefile_updated Makefile
cp deploy_updated.sh scripts/deploy.sh
cp docker-compose.yml .
cp config.toml .

# 4. Add documentation
cp QUICKSTART.md .
cp DEPLOYMENT.md .

# 5. Test locally
make setup     # Should create .env
make test      # Should pass all 13 tests
```

## Cloud VM Workflow

**On the cloud VM:**

```bash
# 1. Clone repo (without .env)
git clone <repo>
cd ybh-promptdev

# 2. Setup (creates .env with secure passwords)
make setup

# 3. Deploy (downloads model, starts services)
make deploy

# 4. Verify
curl http://localhost:8001/health
```

## Key Improvements

### Before:
- ❌ Manual `.env` creation
- ❌ Hardcoded passwords in docker-compose
- ❌ Local `./pgdata` directory
- ❌ Exposed Postgres port
- ❌ No automation

### After:
- ✅ Automated `.env` generation
- ✅ Passwords from environment
- ✅ Docker-managed volumes
- ✅ Isolated network
- ✅ One-command deployment: `make deploy`

## Makefile Changes

**New targets:**
```bash
make setup         # Create .env if missing
make deploy        # Full cloud deployment
make .env          # Create .env (auto-dependency)
make dc-logs       # View logs
make dc-restart    # Restart services
make dc-clean      # Clean everything
make db-shell      # Database shell
make db-backup     # Backup database
```

**Updated targets:**
- `make test` - Depends on `.env`
- `make dc-up` - Depends on `.env`

## Security

✅ `.env` auto-generated with cryptographically random passwords  
✅ `.env` has 600 permissions (owner read/write only)  
✅ `.env` never committed to git (in `.gitignore`)  
✅ Passwords displayed once during `make setup`  
✅ Can always view with: `cat .env`  

## Testing the Update

```bash
# Remove existing .env to test
rm .env

# Run setup
make setup
# Should create .env with passwords and display them

# Verify permissions
ls -la .env
# Should show: -rw------- (600)

# Verify content
cat .env
# Should show generated passwords

# Test it's gitignored
git status
# Should NOT show .env as untracked
```

## Rollback (if needed)

Keep backups of:
- Current `Makefile`
- Current `docker-compose.yml`
- Current `config.toml`
- Current `.env`

Then restore if needed.

## Questions?

See:
- [QUICKSTART.md](computer:///mnt/user-data/outputs/QUICKSTART.md) for quick commands
- [DEPLOYMENT.md](computer:///mnt/user-data/outputs/DEPLOYMENT.md) for full guide
