# Omnidash Integration Quick Start

**Goal**: Add 5 new observability tables to omnidash for full 4-layer traceability

**Estimated Time**: 6.5 hours to working prototype, 5 days to production-ready

---

## What Is Omnidash?

A **production-ready enterprise dashboard** at `/Volumes/PRO-G40/Code/omnidash` with:

- ✅ React + TypeScript + Vite frontend
- ✅ Express backend with Drizzle ORM
- ✅ PostgreSQL integration (192.168.86.200:5436)
- ✅ WebSocket real-time updates
- ✅ Kafka event streaming
- ✅ 12 tables already defined in `shared/intelligence-schema.ts`
- ✅ 100+ API endpoints in `server/intelligence-routes.ts`

**Status**: 90% ready for new observability integration. Just need to add schemas and endpoints.

---

## What's Missing?

**4 new tables** for complete execution traceability:

| Table | Purpose | Priority |
|-------|---------|----------|
| **agent_execution_logs** | Lifecycle tracking (start → progress → complete) | ⭐ Critical |
| **agent_prompts** | Full prompt reconstruction and versioning | ⭐ High |
| **agent_file_operations** | Track all file read/write/edit operations | ⭐ High |
| **agent_intelligence_usage** | Pattern discovery and manifest intelligence | ⭐ Medium |

---

## 6.5 Hour Implementation Plan

### Step 1: Add Schemas (30 min)

**File**: `shared/intelligence-schema.ts`

```typescript
// Add 4 new tables
export const agentExecutionLogs = pgTable('agent_execution_logs', {
  id: uuid('id').primaryKey().defaultRandom(),
  correlationId: uuid('correlation_id').notNull().unique(),
  routingDecisionId: uuid('routing_decision_id'),
  manifestInjectionId: uuid('manifest_injection_id'),
  agentName: text('agent_name').notNull(),
  userPrompt: text('user_prompt').notNull(),
  status: text('status').notNull(), // 'started', 'in_progress', 'completed', 'failed'
  currentStage: text('current_stage'),
  progressPercent: integer('progress_percent').default(0),
  qualityScore: numeric('quality_score', { precision: 5, scale: 4 }),
  startedAt: timestamp('started_at').defaultNow(),
  completedAt: timestamp('completed_at'),
  durationMs: integer('duration_ms'),
  errorMessage: text('error_message'),
  metadata: jsonb('metadata').default({}),
  createdAt: timestamp('created_at').defaultNow(),
  updatedAt: timestamp('updated_at').defaultNow(),
});

// Repeat for: agent_prompts, agent_file_operations, agent_intelligence_usage
// (See full schemas in OMNIDASH_INTEGRATION_ANALYSIS.md)

// Export Zod schemas
export const insertAgentExecutionLogSchema = createInsertSchema(agentExecutionLogs);
// ... (repeat for other tables)

// Export TypeScript types
export type AgentExecutionLog = typeof agentExecutionLogs.$inferSelect;
export type InsertAgentExecutionLog = typeof agentExecutionLogs.$inferInsert;
// ... (repeat for other tables)
```

### Step 2: Update Database Adapter (10 min)

**File**: `server/db-adapter.ts`

```typescript
private getTable(tableName: string): any {
  const tableMap: Record<string, any> = {
    // Existing tables
    'agent_routing_decisions': schema.agentRoutingDecisions,
    'agent_actions': schema.agentActions,
    'agent_manifest_injections': schema.agentManifestInjections,

    // NEW TABLES ⬇️
    'agent_execution_logs': schema.agentExecutionLogs,
    'agent_prompts': schema.agentPrompts,
    'agent_file_operations': schema.agentFileOperations,
    'agent_intelligence_usage': schema.agentIntelligenceUsage,
  };

  return tableMap[tableName];
}
```

### Step 3: Create API Endpoints (2 hours)

**File**: `server/intelligence-routes.ts`

```typescript
// Full Correlation Trace Endpoint (4-layer observability)
intelligenceRouter.get('/trace/:correlationId', async (req, res) => {
  const { correlationId } = req.params;

  // Layer 1: Routing decision
  const routing = await dbAdapter.query('agent_routing_decisions', {
    where: { correlationId },
    limit: 1,
  });

  // Layer 2: Manifest injection
  const manifest = await dbAdapter.query('agent_manifest_injections', {
    where: { correlationId },
    limit: 1,
  });

  // Layer 3: Execution log
  const execution = await dbAdapter.query('agent_execution_logs', {
    where: { correlationId },
    limit: 1,
  });

  // Layer 4: Actions
  const actions = await dbAdapter.query('agent_actions', {
    where: { correlationId },
    orderBy: { column: 'created_at', direction: 'asc' },
  });

  // Additional layers
  const fileOperations = await dbAdapter.query('agent_file_operations', {
    where: { correlationId },
  });

  const intelligence = await dbAdapter.query('agent_intelligence_usage', {
    where: { correlationId },
  });

  const prompts = await dbAdapter.query('agent_prompts', {
    where: { correlationId },
  });

  return res.json({
    correlationId,
    routing: routing[0] || null,
    manifest: manifest[0] || null,
    execution: execution[0] || null,
    actions,
    fileOperations,
    intelligence,
    prompts,
    stats: {
      actionCount: actions.length,
      fileOperationCount: fileOperations.length,
      intelligenceQueryCount: intelligence.length,
      // ... (more stats)
    },
  });
});

// Additional endpoints:
// GET /api/intelligence/execution-logs/recent
// GET /api/intelligence/execution-logs/by-agent/:agentName
// GET /api/intelligence/execution-logs/by-correlation/:correlationId
// (See full implementation in OMNIDASH_INTEGRATION_ANALYSIS.md)
```

### Step 4: Create Data Source (30 min)

**File**: `client/src/lib/data-sources/correlation-trace-source.ts`

```typescript
export interface CorrelationTrace {
  correlationId: string;
  routing: any;
  manifest: any;
  execution: any;
  actions: any[];
  fileOperations: any[];
  intelligence: any[];
  prompts: any[];
  stats: {
    actionCount: number;
    fileOperationCount: number;
    intelligenceQueryCount: number;
  };
}

export async function fetchCorrelationTrace(correlationId: string): Promise<CorrelationTrace> {
  const response = await fetch(`/api/intelligence/trace/${correlationId}`);

  if (!response.ok) {
    throw new Error(`Failed to fetch correlation trace: ${response.statusText}`);
  }

  return await response.json();
}
```

### Step 5: Build CorrelationTrace Page (3 hours)

**File**: `client/src/pages/CorrelationTrace.tsx`

```typescript
import { useParams } from 'wouter';
import { useQuery } from '@tanstack/react-query';
import { fetchCorrelationTrace } from '@/lib/data-sources/correlation-trace-source';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

export default function CorrelationTrace() {
  const { correlationId } = useParams();

  const { data: trace, isLoading } = useQuery({
    queryKey: ['correlation-trace', correlationId],
    queryFn: () => fetchCorrelationTrace(correlationId!),
    enabled: !!correlationId,
  });

  if (isLoading) return <div>Loading...</div>;

  return (
    <div className="p-8 space-y-6">
      <h1 className="text-3xl font-bold">Agent Execution Trace</h1>

      {/* Layer 1: Routing Decision */}
      <Card>
        <CardHeader>
          <CardTitle>Routing Decision</CardTitle>
        </CardHeader>
        <CardContent>
          {/* Display routing data */}
        </CardContent>
      </Card>

      {/* Layer 2: Manifest Injection */}
      <Card>
        <CardHeader>
          <CardTitle>Manifest Injection</CardTitle>
        </CardHeader>
        <CardContent>
          {/* Display manifest data */}
        </CardContent>
      </Card>

      {/* Layer 3: Execution Lifecycle */}
      <Card>
        <CardHeader>
          <CardTitle>Execution Lifecycle</CardTitle>
        </CardHeader>
        <CardContent>
          {/* Display execution data */}
        </CardContent>
      </Card>

      {/* Layer 4: Actions Timeline */}
      <Card>
        <CardHeader>
          <CardTitle>Actions Timeline</CardTitle>
        </CardHeader>
        <CardContent>
          {/* Display actions */}
        </CardContent>
      </Card>

      {/* Additional: File Operations, Intelligence Usage */}
    </div>
  );
}
```

### Step 6: Add Route (5 min)

**File**: `client/src/App.tsx`

```typescript
import CorrelationTrace from '@/pages/CorrelationTrace';

function App() {
  return (
    <Switch>
      {/* Existing routes */}
      <Route path="/" component={AgentOperations} />

      {/* NEW ROUTE ⬇️ */}
      <Route path="/trace/:correlationId" component={CorrelationTrace} />
    </Switch>
  );
}
```

### Step 7: Link from Agent Operations (10 min)

**File**: `client/src/pages/AgentOperations.tsx`

```typescript
import { Link } from 'wouter';

// In actions list:
<Link href={`/trace/${action.correlationId}`}>
  <div className="p-3 hover:bg-accent cursor-pointer">
    <div className="font-semibold">{action.actionName}</div>
    <div className="text-sm text-muted-foreground">{action.agentName}</div>
  </div>
</Link>
```

### Step 8: Test End-to-End (30 min)

```bash
# 1. Navigate to omnidash
cd /Volumes/PRO-G40/Code/omnidash

# 2. Start development server
PORT=3000 npm run dev

# 3. Open browser
open http://localhost:3000

# 4. Test flow:
#    - Click on any action in Agent Operations
#    - Should navigate to /trace/:correlationId
#    - Verify all 4 layers display with data
```

---

## Key Files to Know

| File | Purpose |
|------|---------|
| `shared/intelligence-schema.ts` | Table definitions (Drizzle ORM) |
| `server/db-adapter.ts` | Database CRUD operations |
| `server/intelligence-routes.ts` | API endpoints (100+ routes) |
| `server/websocket.ts` | Real-time updates |
| `server/event-consumer.ts` | Kafka event streaming |
| `client/src/pages/AgentOperations.tsx` | Main dashboard page |
| `client/src/lib/data-sources/` | Data fetching logic |
| `client/src/components/ui/` | Reusable UI components |

---

## Database Configuration

**Connection Details** (from `.env`):
```bash
DATABASE_URL="postgresql://postgres:<password>@192.168.86.200:5436/omninode_bridge"
POSTGRES_HOST=192.168.86.200
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
```

**Verify Connection**:
```bash
source .env
psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -c "SELECT COUNT(*) FROM agent_routing_decisions;"
```

---

## Required Database Migrations

**Create new tables** (run in psql):

```sql
-- 1. agent_execution_logs
CREATE TABLE agent_execution_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  correlation_id UUID NOT NULL UNIQUE,
  routing_decision_id UUID,
  manifest_injection_id UUID,
  agent_name TEXT NOT NULL,
  user_prompt TEXT NOT NULL,
  status TEXT NOT NULL,
  current_stage TEXT,
  progress_percent INTEGER DEFAULT 0,
  quality_score NUMERIC(5, 4),
  started_at TIMESTAMP DEFAULT NOW(),
  completed_at TIMESTAMP,
  duration_ms INTEGER,
  error_message TEXT,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- 2. agent_prompts
CREATE TABLE agent_prompts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  correlation_id UUID NOT NULL,
  execution_log_id UUID,
  prompt_type TEXT NOT NULL,
  prompt_version TEXT DEFAULT '1.0.0',
  prompt_template TEXT NOT NULL,
  prompt_final TEXT NOT NULL,
  template_variables JSONB DEFAULT '{}',
  token_count INTEGER,
  character_count INTEGER,
  compression_ratio NUMERIC(5, 4),
  created_at TIMESTAMP DEFAULT NOW()
);

-- 3. agent_file_operations
CREATE TABLE agent_file_operations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  correlation_id UUID NOT NULL,
  execution_log_id UUID,
  operation_type TEXT NOT NULL,
  file_path TEXT NOT NULL,
  file_size INTEGER,
  line_count INTEGER,
  tool_name TEXT,
  success BOOLEAN DEFAULT TRUE,
  error_message TEXT,
  duration_ms INTEGER,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMP DEFAULT NOW()
);

-- 4. agent_intelligence_usage
CREATE TABLE agent_intelligence_usage (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  correlation_id UUID NOT NULL,
  manifest_injection_id UUID,
  intelligence_type TEXT NOT NULL,
  source_name TEXT NOT NULL,
  query_type TEXT,
  query_text TEXT,
  result_count INTEGER DEFAULT 0,
  query_time_ms INTEGER,
  cache_hit BOOLEAN DEFAULT FALSE,
  relevance_score NUMERIC(5, 4),
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX idx_agent_execution_logs_correlation_id ON agent_execution_logs(correlation_id);
CREATE INDEX idx_agent_prompts_correlation_id ON agent_prompts(correlation_id);
CREATE INDEX idx_agent_file_operations_correlation_id ON agent_file_operations(correlation_id);
CREATE INDEX idx_agent_intelligence_usage_correlation_id ON agent_intelligence_usage(correlation_id);
CREATE INDEX idx_agent_execution_logs_started_at ON agent_execution_logs(started_at DESC);
```

---

## Testing Checklist

- [ ] Database tables created successfully
- [ ] API endpoint `/api/intelligence/trace/:correlationId` returns data
- [ ] CorrelationTrace page renders all 4 layers
- [ ] Click on action in Agent Operations navigates to trace page
- [ ] All layers display real data (not mock)
- [ ] WebSocket real-time updates working (optional for prototype)
- [ ] Error handling works (404 for invalid correlation ID)
- [ ] Loading states display correctly
- [ ] Page is responsive (mobile, tablet, desktop)

---

## Troubleshooting

### Issue: API returns 404

**Solution**: Verify table names match in schema and adapter:
```typescript
// server/db-adapter.ts
'agent_execution_logs': schema.agentExecutionLogs, // Must match exactly
```

### Issue: Database connection failed

**Solution**: Check `.env` file has correct credentials:
```bash
source .env
echo "Host: $POSTGRES_HOST"
echo "Port: $POSTGRES_PORT"
echo "Database: $POSTGRES_DATABASE"
```

### Issue: TypeScript errors in schema

**Solution**: Regenerate Drizzle types:
```bash
npm run db:push
```

### Issue: WebSocket not connecting

**Solution**: Verify WebSocket server is running:
```bash
curl -i -N \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: SGVsbG8sIHdvcmxkIQ==" \
  http://localhost:3000/ws
```

---

## Performance Tips

### 1. Use Indexes

Create indexes on frequently queried columns:
```sql
CREATE INDEX idx_agent_execution_logs_agent_name ON agent_execution_logs(agent_name);
CREATE INDEX idx_agent_file_operations_file_path ON agent_file_operations(file_path);
```

### 2. Enable Query Caching

Configure TanStack Query caching:
```typescript
const { data } = useQuery({
  queryKey: ['correlation-trace', correlationId],
  queryFn: () => fetchCorrelationTrace(correlationId!),
  staleTime: 5 * 60 * 1000, // 5 minutes
  cacheTime: 30 * 60 * 1000, // 30 minutes
});
```

### 3. Paginate Large Results

Use cursor-based pagination:
```typescript
const logs = await dbAdapter.query('agent_execution_logs', {
  where: cursor ? { created_at: { $lt: cursor } } : {},
  limit: 50,
});
```

---

## Next Steps After Prototype

1. **Add Real-Time Updates** (1 hour)
   - WebSocket events for execution progress
   - Live dashboard updates

2. **Build Advanced Visualizations** (4 hours)
   - Execution timeline (Gantt chart)
   - Action flow diagram
   - File heatmap

3. **Add Export Functionality** (1 hour)
   - Export trace to JSON
   - Export trace to CSV

4. **Write Tests** (2 hours)
   - Unit tests for API endpoints
   - Component tests for CorrelationTrace page

5. **Add Monitoring** (1 hour)
   - Health checks for new tables
   - Data freshness alerts

**Total to Production**: 5 days (40 hours)

---

## Resources

- **Full Analysis**: `OMNIDASH_INTEGRATION_ANALYSIS.md` (17 sections, 1000+ lines)
- **Dashboard Location**: `/Volumes/PRO-G40/Code/omnidash`
- **Database**: `postgresql://postgres:***@192.168.86.200:5436/omninode_bridge`
- **Kafka**: `192.168.86.200:9092`
- **Dev Server**: `http://localhost:3000` (port 3000, not 5000!)

---

**Status**: Ready for implementation
**Estimated Prototype**: 6.5 hours
**Estimated Production**: 5 days
**Risk**: Low (infrastructure 90% ready)
