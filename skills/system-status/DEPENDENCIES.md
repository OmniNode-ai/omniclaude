# System Status Skills Dependencies

This document lists all external dependencies required for the system status monitoring skills and provides installation instructions.

## System Dependencies (Required)

### Docker

**Purpose**: Container inspection, logs, stats, health checks

**Commands Used**:
- `docker ps` - List running containers
- `docker inspect` - Get detailed container information
- `docker logs` - Retrieve container logs
- `docker stats` - Monitor resource usage

**Installation**:

**macOS**:
```bash
# Install Docker Desktop
# Download from: https://www.docker.com/products/docker-desktop
```

**Ubuntu/Debian**:
```bash
sudo apt-get update
sudo apt-get install docker.io
sudo systemctl enable docker
sudo systemctl start docker
```

**CentOS/RHEL**:
```bash
sudo yum install -y yum-utils
sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo yum install docker-ce docker-ce-cli containerd.io
sudo systemctl enable docker
sudo systemctl start docker
```

**Arch Linux**:
```bash
sudo pacman -S docker
sudo systemctl enable docker
sudo systemctl start docker
```

### kcat (Kafka CLI)

**Purpose**: Kafka topic operations, message sampling, broker metadata

**Required by**:
- `check-kafka-topics` - Topic listing and metadata retrieval
- `check-infrastructure` - Kafka connectivity and topic health checks
- `check-system-health` - Overall Kafka health status
- `diagnose-issues` - Kafka troubleshooting and diagnostics
- `generate-status-report` - Kafka metrics in comprehensive reports
- All skills using `kafka_helper.py` functions (`check_kafka_connection`, `list_topics`, `get_topic_stats`)

**Commands Used**:
- `kcat -L` - List topics and broker metadata
- `kcat -C` - Consume messages from topics
- `kcat -t` - Target specific topics

**Installation**:

**macOS**:
```bash
brew install kcat
```

**Ubuntu/Debian** (older systems may have `kafkacat` name):
```bash
# Try kcat first
sudo apt-get install kcat

# If not available, try kafkacat (older name)
sudo apt-get install kafkacat

# Or install from source
git clone https://github.com/edenhill/kcat.git
cd kcat
./bootstrap.sh
make
sudo make install
```

**CentOS/RHEL**:
```bash
# Enable EPEL repository
sudo yum install epel-release

# Install kcat
sudo yum install kcat
```

**Arch Linux**:
```bash
sudo pacman -S kcat
```

**Build from Source**:
```bash
git clone https://github.com/edenhill/kcat.git
cd kcat
./bootstrap.sh
make
sudo make install
```

**Note**: On older systems, the package may be named `kafkacat` instead of `kcat`. Both are the same tool - `kcat` is the new name.

### PostgreSQL Client

**Purpose**: Database connectivity checks, query execution, health monitoring

**Commands Used**:
- `psql` - PostgreSQL interactive terminal
- `psql -c` - Execute single command

**Installation**:

**macOS**:
```bash
brew install postgresql@16
# OR for client only
brew install libpq
```

**Ubuntu/Debian**:
```bash
sudo apt-get update
sudo apt-get install postgresql-client
# OR for specific version
sudo apt-get install postgresql-client-16
```

**CentOS/RHEL**:
```bash
sudo yum install postgresql
# OR for specific version
sudo yum install postgresql16
```

**Arch Linux**:
```bash
sudo pacman -S postgresql-libs
```

## Optional Dependencies

### timeout (GNU coreutils)

**Purpose**: Message sampling timeouts in kafka_helper.py to prevent hanging on unresponsive brokers

**Fallback**: Script works without it but may hang indefinitely on unresponsive Kafka brokers

**Installation**:

**Linux**: Usually pre-installed as part of GNU coreutils

**macOS**:
```bash
brew install coreutils
# This installs `gtimeout` (GNU timeout)
```

**Note for macOS**: The GNU version is prefixed with `g`, so use `gtimeout` instead of `timeout` in scripts on macOS.

### curl

**Purpose**: HTTP health checks for services (Qdrant, archon-intelligence, etc.)

**Installation**: Usually pre-installed on most systems

**Ubuntu/Debian**:
```bash
sudo apt-get install curl
```

**macOS**:
```bash
brew install curl
```

## Python Packages

### Required

**psycopg2-binary** - PostgreSQL database adapter

```bash
pip install psycopg2-binary
```

**Purpose**: Connect to PostgreSQL database for health checks and activity queries

**Alternative**: `psycopg2` (requires PostgreSQL development headers)

### Standard Library (No Installation Needed)

These modules are included with Python 3.7+:
- `subprocess` - Command execution
- `json` - JSON parsing and formatting
- `sys` - System operations and exit codes
- `os` - Environment variables and file operations
- `datetime` - Timestamp handling
- `argparse` - Command-line argument parsing

## Verification

Test all dependencies are installed correctly:

```bash
# Docker
docker --version
docker ps  # Should show running containers or empty list (no error)

# kcat
kcat -V  # Should show version (e.g., kcat - Apache Kafka producer and consumer tool)

# If kcat doesn't work, try kafkacat (older name)
kafkacat -V

# PostgreSQL client
psql --version  # Should show version (e.g., psql (PostgreSQL) 16.0)

# timeout (optional)
timeout --version   # Linux - Should show version
gtimeout --version  # macOS - Should show version

# curl (optional)
curl --version  # Should show version

# Python packages
python3 -c "import psycopg2; print('psycopg2:', psycopg2.__version__)"
```

**Expected Output**:
```
Docker version 24.0.5, build ced0996
kcat - Apache Kafka producer and consumer tool
psql (PostgreSQL) 16.0
timeout 8.32
psycopg2: 2.9.9
```

## Troubleshooting

### kcat not found

**Issue**: `kcat: command not found`

**Solutions**:
1. On older systems, try `kafkacat` instead of `kcat` (same tool, older name)
2. Update package lists before installing:
   ```bash
   # Ubuntu/Debian
   sudo apt-get update

   # macOS
   brew update
   ```
3. Install from source if package not available (see installation section above)

### Docker permission denied

**Issue**: `Got permission denied while trying to connect to the Docker daemon socket`

**Solutions**:
1. Add your user to the docker group:
   ```bash
   sudo usermod -aG docker $USER
   ```
2. Log out and log back in (or restart shell):
   ```bash
   # Restart shell
   exec sudo su -l $USER

   # OR log out and log back in
   ```
3. Verify group membership:
   ```bash
   groups  # Should include 'docker'
   ```

### timeout not found (macOS)

**Issue**: `timeout: command not found` on macOS

**Solutions**:
1. Install GNU coreutils:
   ```bash
   brew install coreutils
   ```
2. Use `gtimeout` instead of `timeout`:
   ```bash
   # Edit scripts to use gtimeout on macOS
   which gtimeout  # Verify it's available
   ```
3. Alternative: Create alias in `.bashrc` or `.zshrc`:
   ```bash
   alias timeout='gtimeout'
   ```

### psycopg2 build errors

**Issue**: `Error: pg_config executable not found` or compilation errors

**Solutions**:
1. Use `psycopg2-binary` instead of `psycopg2` (includes precompiled binaries):
   ```bash
   pip uninstall psycopg2
   pip install psycopg2-binary
   ```
2. Install PostgreSQL development headers:
   ```bash
   # Ubuntu/Debian
   sudo apt-get install libpq-dev python3-dev

   # CentOS/RHEL
   sudo yum install postgresql-devel python3-devel

   # macOS
   brew install postgresql
   ```
3. Specify pg_config path:
   ```bash
   export PATH="/usr/local/opt/postgresql@16/bin:$PATH"
   pip install psycopg2
   ```

### PostgreSQL connection refused

**Issue**: `could not connect to server: Connection refused`

**Solutions**:
1. Verify PostgreSQL is running:
   ```bash
   docker ps | grep postgres
   # OR
   systemctl status postgresql
   ```
2. Check connection parameters in `.env`:
   ```bash
   source .env
   echo "Host: $POSTGRES_HOST"
   echo "Port: $POSTGRES_PORT"
   ```
3. Test connectivity:
   ```bash
   psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -c "SELECT 1"
   ```

### Kafka broker unreachable

**Issue**: `Failed to connect to Kafka broker` or `Broker: Leader not available`

**Solutions**:
1. Verify Kafka/Redpanda is running:
   ```bash
   docker ps | grep redpanda
   ```
2. Check bootstrap servers in `.env`:
   ```bash
   source .env
   echo "Bootstrap: $KAFKA_BOOTSTRAP_SERVERS"
   ```
3. Test connectivity with kcat:
   ```bash
   kcat -L -b $KAFKA_BOOTSTRAP_SERVERS
   ```
4. Verify network connectivity:
   ```bash
   # For remote broker (192.168.86.200:29092)
   nc -zv 192.168.86.200 29092
   ```

## Environment Variables

Several system status skills require environment variables. Ensure `.env` is sourced before running scripts:

```bash
source .env
```

**Required Environment Variables**:
- `POSTGRES_HOST` - PostgreSQL host (default: 192.168.86.200)
- `POSTGRES_PORT` - PostgreSQL port (default: 5436)
- `POSTGRES_USER` - PostgreSQL user (default: postgres)
- `POSTGRES_PASSWORD` - PostgreSQL password (REQUIRED)
- `POSTGRES_DATABASE` - PostgreSQL database (default: omninode_bridge)
- `KAFKA_BOOTSTRAP_SERVERS` - Kafka bootstrap servers (default: 192.168.86.200:29092)
- `QDRANT_URL` - Qdrant vector database URL (default: http://localhost:6333)

**Verification**:
```bash
# Check all required variables are set
source .env
env | grep -E "(POSTGRES|KAFKA|QDRANT)"
```

## See Also

- [System Status Skills README](README.md) - Overview of available skills
- [Shared Helper Functions](_shared/README.md) - Shared utility documentation
- [Docker Helper](_shared/docker_helper.py) - Docker operations helper
- [Kafka Helper](_shared/kafka_helper.py) - Kafka operations helper
- [Database Helper](_shared/db_helper.py) - PostgreSQL operations helper
- [Qdrant Helper](_shared/qdrant_helper.py) - Qdrant operations helper
- [OmniClaude CLAUDE.md](/Volumes/PRO-G40/Code/omniclaude/CLAUDE.md) - Main project documentation
- [Environment Configuration](../../.env.example) - Environment variable template

## Platform Support

These system status skills are tested and supported on:

- macOS 12+ (Monterey or later)
- Ubuntu 20.04+
- Debian 11+
- CentOS/RHEL 8+
- Arch Linux (rolling)

Other Linux distributions should work but may require adjustments to installation commands.

## Docker Network Requirements

System status skills require access to Docker networks for service health checks:

**Required Networks**:
- `omninode-bridge-network` - Shared infrastructure network
- `app_network` - Local application network

**Verification**:
```bash
docker network ls | grep -E "(omninode-bridge|app_network)"
```

If networks are missing, see deployment documentation for setup instructions.

## Security Considerations

### Credential Storage

Never hardcode credentials in scripts. Always use environment variables:

```bash
# ✅ CORRECT (using environment variables)
source .env
psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER

# ❌ WRONG (hardcoded credentials)
psql -h 192.168.86.200 -p 5436 -U postgres -W mypassword123
```

### Docker Socket Access

System status skills need read-only access to Docker socket for container inspection. Never grant write access unless absolutely necessary.

### Network Security

When connecting to remote services (PostgreSQL, Kafka), ensure:
- Connections use encryption (TLS/SSL) in production
- Firewall rules restrict access to authorized hosts
- API keys and passwords are rotated regularly

See [SECURITY_KEY_ROTATION.md](../../SECURITY_KEY_ROTATION.md) for key rotation procedures.
