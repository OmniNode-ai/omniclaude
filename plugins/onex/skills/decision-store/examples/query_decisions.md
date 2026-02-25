# Example: Query Decisions

## Scenario

We want to review all open HIGH-severity conflicts in the `api` domain at the
`architecture` layer before starting a new sprint.

---

## Basic Query — All decisions in a domain

```
/decision-store query --domain api
```

Output:

```
Decisions in domain: api
Showing 1–3 of 3 (page 1/1)

ID       | Type              | Domain | Layer        | Services              | Conflicts | Status
---------|-------------------|--------|--------------|-----------------------|-----------|-------
e1f2g3h4 | API_CONTRACT      | api    | architecture | platform-wide         | 1 HIGH    | OPEN
i5j6k7l8 | DESIGN_PATTERN    | api    | design       | auth-service          | 0         | -
m9n0o1p2 | API_CONTRACT      | api    | planning     | notification-service  | 1 MEDIUM  | OPEN
```

---

## Filtered Query — Only architecture layer decisions with open conflicts

```
/decision-store query \
  --domain api \
  --layer architecture \
  --status open
```

Output:

```
Decisions in domain: api, layer: architecture, status: open
Showing 1–1 of 1

ID       | Type         | Domain | Layer        | Services      | Conflicts | Status
---------|--------------|--------|--------------|---------------|-----------|-------
e1f2g3h4 | API_CONTRACT | api    | architecture | platform-wide | 1 HIGH    | OPEN
```

---

## Paginated Query — Large result sets

```
/decision-store query --domain infrastructure --limit 2
```

Output:

```
Decisions in domain: infrastructure
Showing 1–2 of 8

ID       | Type               | Domain         | Layer        | Services      | Conflicts | Status
---------|--------------------|----------------|--------------|---------------|-----------|-------
a1b2c3d4 | TECH_STACK_CHOICE  | infrastructure | architecture | platform-wide | 0         | -
b2c3d4e5 | TECH_STACK_CHOICE  | infrastructure | architecture | platform-wide | 1 HIGH    | OPEN

[Next page: use --cursor eyJvZmZzZXQiOiAyfQ==]
```

Fetch next page:

```
/decision-store query --domain infrastructure --limit 2 --cursor eyJvZmZzZXQiOiAyfQ==
```

Output:

```
Decisions in domain: infrastructure
Showing 3–4 of 8

ID       | Type               | Domain         | Layer   | Services     | Conflicts | Status
---------|--------------------|-|----|------|----|---------
c3d4e5f6 | DESIGN_PATTERN     | infrastructure | design  | kafka-broker | 0         | -
d4e5f6g7 | SCOPE_BOUNDARY     | infrastructure | design  | kafka-broker | 1 MEDIUM  | OPEN

[Next page: use --cursor eyJvZmZzZXQiOiA0fQ==]
```

---

## Query by service

Find all decisions that affect the `auth-service`:

```
/decision-store query --service auth-service
```

Output:

```
Decisions affecting service: auth-service
Showing 1–2 of 2

ID       | Type            | Domain | Layer  | Services                        | Conflicts | Status
---------|-----------------|--------|--------|---------------------------------|-----------|-------
i5j6k7l8 | DESIGN_PATTERN  | api    | design | auth-service                    | 0         | -
q1r2s3t4 | API_CONTRACT    | api    | design | auth-service, session-service   | 1 MEDIUM  | OPEN
```

---

## Query resolved decisions

Review what was previously resolved:

```
/decision-store query --status resolved
```

Output:

```
Resolved decisions
Showing 1–1 of 1

ID       | Type              | Domain         | Layer        | Resolved By | Resolution Note
---------|-------------------|----------------|--------------|-------------|--------------------
u5v6w7x8 | TECH_STACK_CHOICE | infrastructure | architecture | jonah.gabriel | MongoDB is only for event store; no overlap with PostgreSQL
```
