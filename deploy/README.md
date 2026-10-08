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
| `S3_BUCKET`, `DDB_DOCS` | If **both** are set, sessions use S3 + DynamoDB. Otherwise local files (dev). |
| `DDB_PROFILES`, `DDB_AUDIT` | Per-user KPI/Analysis profiles; the audit log. |
| `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID` | If **both** are set, every `/api` request needs a valid Entra bearer token. |
| `CORS_ORIGINS` | Comma-separated allowed browser origins (your Amplify URL). |
| `BEDROCK_DEFAULT_MODEL`, `BEDROCK_STRONG_MODEL` | Bedrock model / `eu.` inference-profile ids. Confirm them in the Bedrock console. |
| `BEDROCK_PROMPT_IDS` | Optional JSON map of call name -> Prompt Management id. |
| `AWS_REGION`, `BEDROCK_REGION`, `TRANSLATE_REGION` | Regions. |

## Resources the backend expects

DynamoDB (on-demand), three tables: `pmai-docs` (`session_id`, `doc`; also holds the session header as
doc `SESSIONS`), `pmai-profiles` (`user_id`, `profile`), `pmai-audit-log` (`session_id`, `ts_event`, plus
GSI `by-user` on `user_id`, `ts_event` and GSI `by-target` on `target_key`, `ts_event`, both projecting all
attributes). TTL attribute `ttl` on docs, profiles and the audit log. See `docs/DYNAMODB_REDESIGN_PLAN.md`.
S3: one private bucket with CORS allowing `PUT`/`GET` from the Amplify origin.

## Prompts in Amazon Bedrock Prompt Management (optional)

The system prompts live in the source and work with no setup. To manage them in Bedrock instead
(versioned, editable without a redeploy), use `backend/scripts/bedrock_prompts.py` (run from `backend/`):

```
python scripts/bedrock_prompts.py export              # write each prompt to prompts_export/<call>.txt
python scripts/bedrock_prompts.py create --dry-run    # preview
python scripts/bedrock_prompts.py create              # create the 19 prompts + version 1; prints BEDROCK_PROMPT_IDS
python scripts/bedrock_prompts.py verify              # compare Bedrock with the source
python scripts/bedrock_prompts.py create --update     # push the current source text as a new version
```

Put the printed `BEDROCK_PROMPT_IDS` value in the task definition. A prompt is used from Bedrock only
when its call name is in that variable; otherwise (or if Bedrock is unreachable) the in-source text is
used. Lookups are cached for `PROMPT_CACHE_SECONDS` (default 300). Pin versions (`ID:2`), and move to a
new version by editing the variable. The user running the script needs `bedrock:CreatePrompt`,
`UpdatePrompt`, `CreatePromptVersion`, `GetPrompt` and `ListPrompts`; the task role needs `bedrock:GetPrompt`.
