# Cloud VM Deployment - Quick Reference

## Fresh Deployment on Cloud VM

### 1. Clone Repo
```bash
git clone https://github.com/your-org/ybh-promptdev.git
cd ybh-promptdev
```

### 2. Setup Environment
```bash
make setup
```
This creates `.env` with secure auto-generated passwords.

**Important:** The passwords are displayed once. Save them!

### 3. Deploy Stack
```bash
make deploy
```
This runs the full deployment:
- Downloads Mistral model (~4GB, first time only)
- Starts all containers
- Runs migrations

### 4. Verify
```bash
curl http://localhost:8001/health
```

## Common Operations

```bash
# View logs
make dc-logs

# Restart services
make dc-restart

# Stop everything
make dc-down

# Start everything
make dc-up

# Run tests
make test

# Database shell
make db-shell

# Backup database
make db-backup
```

## File Structure on VM

```
ybh-promptdev/
├── .env                    # ✅ Created by: make setup
├── .env.example            # Template (committed to repo)
├── docker-compose.yml      # ✅ Updated version
├── config.toml             # ✅ Updated for Docker networking
├── Makefile                # ✅ Updated with setup targets
├── scripts/
│   ├── setup_env.sh        # ✅ New - creates .env
│   ├── deploy.sh           # ✅ Updated - uses Makefile
│   └── ...
└── ...
```

## What Gets Created

**On first `make setup`:**
- `.env` file with passwords (chmod 600)

**On first `make deploy`:**
- Docker volumes:
  - `promptdev-pgdata` (Postgres data)
  - `promptdev-models` (Mistral GGUF, ~4GB)
- Docker network: `promptdev-net`
- 3 containers:
  - `promptdev-postgres`
  - `promptdev-mistral`
  - `promptdev-backend`

## Security Notes

✅ `.env` is auto-generated with strong passwords  
✅ `.env` has 600 permissions (owner read/write only)  
✅ `.env` is in `.gitignore` (never committed)  
✅ Only backend port 8001 exposed to host  
✅ Postgres and Mistral are internal-only  

## Troubleshooting

### "Permission denied" on scripts
```bash
chmod +x scripts/*.sh
```

### ".env already exists" but want to regenerate
```bash
rm .env
make setup
```

### Check what passwords were generated
```bash
cat .env
```

### Forgot to save passwords from setup
```bash
# They're in the .env file
grep PASS .env
```
