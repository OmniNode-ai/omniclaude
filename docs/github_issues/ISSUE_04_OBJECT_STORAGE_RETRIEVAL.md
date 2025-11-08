# Implement Object Storage Retrieval for State Snapshots

## Labels
`priority:high`, `type:feature`, `component:storage`, `observability`

## Description

Large state snapshots (>1MB) are stored in object storage but cannot be retrieved, breaking state replay and debugging capabilities.

## Current Behavior

`state_snapshots.py` returns `None` for snapshots stored in object storage:

```python
# agents/lib/state_snapshots.py:108-115
async def get_snapshot(self, run_id: str, step_id: str) -> Optional[Dict[str, Any]]:
    # ... query database ...

    if row["storage_uri"]:
        # TODO: Implement object storage retrieval
        return None
    else:
        return row["snapshot"]
```

## Impact

- ❌ **Data Loss**: Large snapshots (>1MB) cannot be retrieved
- ❌ **Debugging Broken**: Complex workflows cannot be replayed
- ❌ **Observability Gap**: Missing critical state information
- ❌ **Feature Incomplete**: Snapshot storage partially implemented

## Expected Behavior

Should:
1. Parse storage_uri (s3://, file://, minio://)
2. Retrieve snapshot from appropriate backend
3. Support streaming for very large snapshots
4. Implement caching layer (Valkey) for hot snapshots
5. Generate signed URLs for secure external access

## Implementation Plan

### 1. Add Storage Backend Interface

```python
# agents/lib/storage/base.py
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

class StorageBackend(ABC):
    """Abstract storage backend interface."""

    @abstractmethod
    async def get(self, uri: str) -> Optional[Dict[str, Any]]:
        """Retrieve object from storage."""
        pass

    @abstractmethod
    async def put(self, uri: str, data: Dict[str, Any]) -> str:
        """Store object and return URI."""
        pass

    @abstractmethod
    async def delete(self, uri: str) -> bool:
        """Delete object from storage."""
        pass

    @abstractmethod
    async def get_signed_url(
        self,
        uri: str,
        expiration_seconds: int = 3600
    ) -> str:
        """Generate signed URL for secure access."""
        pass
```

### 2. Implement S3/MinIO Backend

```python
# agents/lib/storage/s3_backend.py
import aioboto3
from urllib.parse import urlparse

class S3Backend(StorageBackend):
    """S3/MinIO storage backend."""

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ):
        self.endpoint_url = endpoint_url  # For MinIO
        self.access_key = access_key
        self.secret_key = secret_key
        self.session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    async def get(self, uri: str) -> Optional[Dict[str, Any]]:
        """Retrieve object from S3/MinIO."""
        parsed = urlparse(uri)
        bucket = parsed.netloc
        key = parsed.path.lstrip('/')

        async with self.session.client(
            's3',
            endpoint_url=self.endpoint_url,
        ) as s3:
            try:
                response = await s3.get_object(Bucket=bucket, Key=key)
                body = await response['Body'].read()
                return json.loads(body)
            except Exception as e:
                logger.error(f"Failed to retrieve {uri}: {e}")
                return None

    async def put(self, uri: str, data: Dict[str, Any]) -> str:
        """Store object in S3/MinIO."""
        parsed = urlparse(uri)
        bucket = parsed.netloc
        key = parsed.path.lstrip('/')

        async with self.session.client(
            's3',
            endpoint_url=self.endpoint_url,
        ) as s3:
            body = json.dumps(data).encode('utf-8')
            await s3.put_object(Bucket=bucket, Key=key, Body=body)
            return uri

    async def get_signed_url(
        self,
        uri: str,
        expiration_seconds: int = 3600
    ) -> str:
        """Generate signed URL for S3/MinIO."""
        parsed = urlparse(uri)
        bucket = parsed.netloc
        key = parsed.path.lstrip('/')

        async with self.session.client(
            's3',
            endpoint_url=self.endpoint_url,
        ) as s3:
            url = await s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket, 'Key': key},
                ExpiresIn=expiration_seconds,
            )
            return url
```

### 3. Implement Local Filesystem Backend

```python
# agents/lib/storage/filesystem_backend.py
import aiofiles
from pathlib import Path

class FilesystemBackend(StorageBackend):
    """Local filesystem storage backend."""

    def __init__(self, base_path: str = "/var/lib/omniclaude/snapshots"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def get(self, uri: str) -> Optional[Dict[str, Any]]:
        """Retrieve object from filesystem."""
        parsed = urlparse(uri)
        path = self.base_path / parsed.path.lstrip('/')

        if not path.exists():
            return None

        async with aiofiles.open(path, 'r') as f:
            content = await f.read()
            return json.loads(content)

    async def put(self, uri: str, data: Dict[str, Any]) -> str:
        """Store object in filesystem."""
        parsed = urlparse(uri)
        path = self.base_path / parsed.path.lstrip('/')
        path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(path, 'w') as f:
            await f.write(json.dumps(data, indent=2))

        return uri
```

### 4. Add Storage Factory

```python
# agents/lib/storage/factory.py
from urllib.parse import urlparse

def get_storage_backend(uri: str) -> StorageBackend:
    """Create appropriate storage backend based on URI scheme."""
    parsed = urlparse(uri)

    if parsed.scheme == 's3':
        return S3Backend(
            endpoint_url=os.getenv('S3_ENDPOINT_URL'),
            access_key=os.getenv('S3_ACCESS_KEY'),
            secret_key=os.getenv('S3_SECRET_KEY'),
        )
    elif parsed.scheme == 'file':
        return FilesystemBackend(
            base_path=os.getenv('SNAPSHOT_STORAGE_PATH', '/var/lib/omniclaude/snapshots')
        )
    else:
        raise ValueError(f"Unsupported storage scheme: {parsed.scheme}")
```

### 5. Update StateSnapshotManager

```python
# agents/lib/state_snapshots.py
class StateSnapshotManager:
    def __init__(self):
        # ... existing init ...
        self._storage_cache: Dict[str, StorageBackend] = {}

    def _get_storage_backend(self, uri: str) -> StorageBackend:
        """Get cached storage backend for URI scheme."""
        scheme = urlparse(uri).scheme
        if scheme not in self._storage_cache:
            self._storage_cache[scheme] = get_storage_backend(uri)
        return self._storage_cache[scheme]

    async def get_snapshot(
        self,
        run_id: str,
        step_id: str,
        use_cache: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Get workflow state snapshot."""
        pool = await get_pg_pool()
        if pool is None:
            return None

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT snapshot, storage_uri
                FROM state_snapshots
                WHERE run_id = $1 AND step_id = $2
                """,
                run_id,
                step_id,
            )

            if not row:
                return None

            if row["storage_uri"]:
                # Check Valkey cache first
                if use_cache:
                    cached = await self._get_from_cache(row["storage_uri"])
                    if cached:
                        return cached

                # Retrieve from object storage
                backend = self._get_storage_backend(row["storage_uri"])
                snapshot = await backend.get(row["storage_uri"])

                # Cache for future requests
                if snapshot and use_cache:
                    await self._put_in_cache(row["storage_uri"], snapshot)

                return snapshot
            else:
                return row["snapshot"]

    async def _get_from_cache(self, uri: str) -> Optional[Dict[str, Any]]:
        """Get snapshot from Valkey cache."""
        # TODO: Implement Valkey caching
        return None

    async def _put_in_cache(
        self,
        uri: str,
        snapshot: Dict[str, Any],
        ttl_seconds: int = 3600,
    ):
        """Store snapshot in Valkey cache."""
        # TODO: Implement Valkey caching
        pass
```

### 6. Add Configuration

```python
# .env
# Object storage configuration
SNAPSHOT_STORAGE_BACKEND=s3  # s3, filesystem
SNAPSHOT_STORAGE_PATH=/var/lib/omniclaude/snapshots  # For filesystem backend
S3_ENDPOINT_URL=http://minio.local:9000  # For MinIO
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=omniclaude-snapshots
SNAPSHOT_CACHE_TTL_SECONDS=3600
```

## Testing

```python
# tests/lib/test_state_snapshots.py
@pytest.mark.asyncio
async def test_retrieve_from_s3(state_snapshot_manager, s3_mock):
    """Test retrieving snapshot from S3."""
    # Arrange: Store large snapshot in S3
    large_snapshot = {"data": "x" * 2_000_000}  # >2MB
    uri = "s3://test-bucket/snapshots/run123/step456.json"

    await s3_mock.put_object(
        Bucket="test-bucket",
        Key="snapshots/run123/step456.json",
        Body=json.dumps(large_snapshot),
    )

    # Insert DB record with storage_uri
    await insert_snapshot_record(
        run_id="run123",
        step_id="step456",
        storage_uri=uri,
    )

    # Act
    retrieved = await state_snapshot_manager.get_snapshot(
        run_id="run123",
        step_id="step456",
    )

    # Assert
    assert retrieved == large_snapshot

@pytest.mark.asyncio
async def test_retrieve_from_filesystem(state_snapshot_manager, tmp_path):
    """Test retrieving snapshot from filesystem."""
    # Arrange
    snapshot = {"data": "test"}
    uri = f"file:///snapshots/run123/step456.json"

    # Write to filesystem
    snapshot_path = tmp_path / "snapshots" / "run123" / "step456.json"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(json.dumps(snapshot))

    # Act
    retrieved = await state_snapshot_manager.get_snapshot(
        run_id="run123",
        step_id="step456",
    )

    # Assert
    assert retrieved == snapshot
```

## Success Criteria

- [ ] Storage backend interface defined
- [ ] S3/MinIO backend implemented
- [ ] Local filesystem backend implemented
- [ ] Storage factory creates appropriate backend
- [ ] StateSnapshotManager retrieves from storage
- [ ] Valkey caching implemented (optional)
- [ ] Signed URL generation supported
- [ ] Tests verify retrieval from multiple backends
- [ ] Documentation updated

## Related Issues

- Part of PR #22 review (Issue #21)
- Improves observability and debugging

## Files to Modify

- `agents/lib/state_snapshots.py` - Add storage retrieval
- `agents/lib/storage/base.py` - Create backend interface
- `agents/lib/storage/s3_backend.py` - Create S3 backend
- `agents/lib/storage/filesystem_backend.py` - Create filesystem backend
- `agents/lib/storage/factory.py` - Create backend factory
- `.env.example` - Add storage configuration
- `config/settings.py` - Add storage settings
- `requirements.txt` - Add aioboto3, aiofiles
- `tests/lib/test_state_snapshots.py` - Add retrieval tests

## Estimated Effort

- Backend interface: 2-3 hours
- S3 backend: 3-4 hours
- Filesystem backend: 2-3 hours
- Integration: 2-3 hours
- Testing: 3-4 hours
- Caching (optional): 2-3 hours
- Documentation: 1-2 hours
- **Total**: 2-4 days

## Priority Justification

**HIGH** - Large state snapshots are currently lost, breaking debugging and replay capabilities for complex workflows. This limits observability for production issues.

## Dependencies

- `aioboto3` - Async S3 client
- `aiofiles` - Async file I/O
- Optional: `minio` - MinIO client library
