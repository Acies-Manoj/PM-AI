# PMAI OpenTofu Infrastructure (Approach 2: single-step first deployment)

This folder builds the PMAI AWS setup with OpenTofu. This branch is **Approach 2**: one `tofu apply`
creates everything (including the container, `desired_count = 1`) and the CORS origin is derived
automatically from the Amplify app. GitHub Actions handle the first deployment, day-to-day changes and
Bedrock prompt versions.

```text
Amplify frontend
   -> API Gateway HTTP API
   -> VPC Link
   -> internal ALB
   -> ECS Fargate FastAPI backend
   -> S3, DynamoDB, CloudWatch, Translate, Bedrock
```

The network is not created here: the stack uses an **existing VPC** and its private subnets
(`create_vpc = false`). The VPC needs two private subnets in different availability zones, outbound
access for private containers (a NAT gateway or VPC endpoints) and permission to create security groups.

## Files

| Path | Purpose |
|---|---|
| `*.tf` | The infrastructure: network lookup, security groups, IAM, ECR, S3, DynamoDB, ECS, ALB, API Gateway, Amplify |
| `environments/opentofu/practice.tfvars` | The settings of this environment |
| `environments/opentofu/prompt-ids-practice.tfvars.json` | Bedrock prompt ids, written by the prompts workflow. Pass it as a second `-var-file`. |
| `environments/opentofu/backend-practice.hcl` | Remote state settings (state key, region, lock file). The bucket name is passed at init, never stored. |
| `environments/opentofu/opentofu-cg-existing-vpc.tfvars` | Template for a client environment. Replace every `CHANGE_ME`. |
| `environments/opentofu/backend.hcl.template` | Template for the remote state settings of another account |
| `ci/github-oidc-trust-policy.json`, `ci/pipeline-permissions-policy.json` | The AWS role the workflows assume, with placeholders (see "The pipeline role") |
| `../.github/workflows/` | `infra.yml`, `app.yml`, `prompts.yml` |
| `../.github/actions/sync-task-definition/` | Rolls the latest task definition out with the image that is running |

No file holds credentials, account ids or secret values. Real ids belong only in `*.local.json` copies
of the role files (git-ignored) and in GitHub variables.

## One-time setup (once per AWS account)

1. **State bucket**, created by hand (it must not be managed by the stack it stores): private,
   versioned, encrypted, no public access. OpenTofu 1.10+ locks state with a lock file in the bucket.
2. **GitHub OIDC provider** `token.actions.githubusercontent.com` in IAM. An account can have only one.
3. **The pipeline role** (below).
4. **GitHub settings** on the repository (Settings, Secrets and variables, Actions), at **repository**
   level, because the plan job does not use an environment:

   | Kind | Name | Value |
   |---|---|---|
   | Variable | `AWS_ROLE_ARN` | ARN of the pipeline role |
   | Variable | `TF_STATE_BUCKET` | Name of the state bucket |
   | Secret | `TF_VAR_amplify_access_token` | GitHub token, needed when the Amplify app is created |
   | Environment | `practice` | Required reviewer |

5. **Bedrock prompts**: in a **new AWS account** run the prompts workflow manually with `all` ticked (creates every prompt
   that does not exist yet and records the ids) before the first deployment. Prompts survive `tofu destroy`.

## The pipeline role

One role signs in without keys (OIDC). Its two files hold placeholders (`<ACCOUNT_ID>`, `<GITHUB_USER>`,
`<OWNER_ID>`, `<REPO>`, `<REPO_ID>`). Never commit real values: copy each file to a name ending `.local.json`
(git-ignored), fill the placeholders, and from the **repository root** run:

```
aws iam create-role --role-name <ROLE_NAME> --assume-role-policy-document file://infra/ci/trust.local.json --profile <profile>
aws iam put-role-policy --role-name <ROLE_NAME> --policy-name pmai-deploy --policy-document file://infra/ci/permissions.local.json --profile <profile>
```

- The role is **not** named `pmai-*`, so its IAM permissions (limited to `pmai-*` roles) cannot be used
  to change the role itself.
- Newer GitHub repositories put numeric ids in the identity string:
  `repo:<GITHUB_USER>@<OWNER_ID>/<REPO>@<REPO_ID>:ref:refs/heads/<branch>`. The ids are public:
  `https://api.github.com/repos/<GITHUB_USER>/<REPO>` returns `id` and `owner.id`. The match is
  case-sensitive.
- The trust policy in this branch allows the branch `single-1step`, the `practice` environment and pull
  requests of this repository only. If the same role is also used from another branch, add that branch's
  subject to the list and run `aws iam update-assume-role-policy`.
- To change the permissions later, edit the JSON and run `put-role-policy` again.

## First deployment (single step)

There is nothing to start by hand. Push the branch (or any change under `infra/`) to a new environment and
`infra.yml` does it all, because an empty state means a new environment:

1. Plans, then waits for approval of `practice` (the one click).
2. Applies every resource with `desired_count = 1`, and the task definition points at this commit's image
   tag. The image repository is empty at this point, so ECS cannot start the container.
3. Builds the image, tags it with the commit id and pushes it.
4. Prints what ECS did while the image was missing (deployments and service events).
5. Forces a new deployment of the ECS service, and waits until the service is stable.

CORS needs no edit: the Amplify URL is added automatically. Authorise the GitHub app once in the Amplify
console ("Update required") and Amplify builds the site on every later push. `app.yml` does nothing while the
stack does not exist yet, so pushing everything at once is safe.

## Workflows

| Workflow | Starts on | Does |
|---|---|---|
| `infra.yml` | Changes under `infra/`, pull requests | `init`, `validate`, `plan`; after a push the apply job waits for approval of `practice`, applies, then rolls out the latest task definition. In a new environment it also pushes the first image and forces the deployment. |
| `app.yml` | Changes under `backend/` (not `prompts/` or `scripts/`) | Builds the image, pushes it tagged with the commit id, deploys it to ECS. Skips when the stack does not exist yet. |
| `prompts.yml` | Changes under `backend/prompts/`; a manual run with `all` creates the prompts of a new AWS account (the one manual step, it needs this branch to be the default branch for the button to show) | Lint on pull requests; on a push publishes new versions of the changed prompts, updates only their ids, then calls `infra.yml` |

The ECS service ignores its task definition (`ecs.tf`), so `app.yml` owns which image runs. A change to the
container's environment (prompt ids, CORS origins) creates a new revision that only reaches the running
container through the roll-out step of `infra.yml` or the next `app.yml` run.

## Prompts

The prompt text lives in `backend/prompts/*.txt` and the backend reads it from Bedrock Prompt Management,
by the ids in `prompt-ids-practice.tfvars.json`. Edit a file and merge: the workflow publishes a new version
of that prompt only, records its id, and the apply puts it into the container. Bedrock prompts are shared by
name in an account, so the workflow stops if the latest version in Bedrock is not the one recorded in the
ids file (someone published it outside the pipeline). Roll back by reverting the ids file.

## Running OpenTofu by hand

Run from this folder. Pass the settings **and** the ids file, and the bucket name at init:

```
tofu init -backend-config=environments/opentofu/backend-practice.hcl -backend-config="bucket=<state bucket>" -backend-config="profile=<profile>"
tofu plan -var-file=environments/opentofu/practice.tfvars -var-file=environments/opentofu/prompt-ids-practice.tfvars.json
```

A plan without `-var-file` uses the defaults and wants to rebuild everything: never apply it.

## Teardown

```
tofu destroy -var-file=environments/opentofu/practice.tfvars -var-file=environments/opentofu/prompt-ids-practice.tfvars.json
```

The state bucket, the pipeline role, the GitHub provider, the Bedrock prompts and the shared VPC are not
managed by this stack and stay.
