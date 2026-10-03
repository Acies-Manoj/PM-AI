# Deploy files

| File | Use |
|---|---|
| `taskdef.json` | ECS Fargate task definition. Replace every `<PLACEHOLDER>`, then `aws ecs register-task-definition --cli-input-json file://deploy/taskdef.json`. |
| `iam/pmai-task-role.json` | One policy for the **task role** `pmai-task-role` (S3, DynamoDB, Bedrock, Translate). IAM -> Roles -> `pmai-task-role` -> Add permissions -> Create inline policy -> JSON. |

The **execution role** (`pmai-task-exec-role`) is separate: it only pulls the image and writes logs.
The OpenRouter and DeepL secrets are no longer used, so the task definition has no `secrets` block.

## What the backend reads from the environment

| Variable | Purpose |
|---|---|
| `S3_BUCKET`, `DDB_SESSIONS`, `DDB_DOCS` | If **all three** are set, sessions use S3 + DynamoDB. Otherwise local files (dev). |
| `DDB_PROFILES`, `DDB_AUDIT` | Per-user KPI/Analysis profiles; the audit log. |
| `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID` | If **both** are set, every `/api` request needs a valid Entra bearer token. |
| `CORS_ORIGINS` | Comma-separated allowed browser origins (your Amplify URL). |
| `BEDROCK_DEFAULT_MODEL`, `BEDROCK_STRONG_MODEL` | Bedrock model / `eu.` inference-profile ids. Confirm them in the Bedrock console. |
| `BEDROCK_PROMPT_IDS` | Optional JSON map of call name -> Prompt Management id. |
| `AWS_REGION`, `BEDROCK_REGION`, `TRANSLATE_REGION` | Regions. |

## Resources the backend expects

DynamoDB (on-demand): `pmai-sessions` (`session_id`), `pmai-docs` (`session_id`, `doc`),
`pmai-profiles` (`user_id`, `profile`), `pmai-audit-log` (`session_id`, `ts_event`, plus GSI
`by-user` on `user_id`, `ts_event`). TTL attribute `ttl` on sessions, docs and the audit log.
S3: one private bucket with CORS allowing `PUT`/`GET` from the Amplify origin.
