# Values to Fill Before Running

This file lists what to fill and where.

## For Acies practice

Edit:

```text
environments/opentofu/opentofu-acies-practice.tfvars
```

Fill:

| Value | Where to paste | Example / note |
|---|---|---|
| AWS CLI profile | `aws_profile` | Your Acies/SSO profile name |
| Region | `aws_region` | Keep same as practice account region |
| Backend image tag | `image_tag` | `1.0.0` |
| Bedrock model ID | `bedrock_model_id` | Put approved model ID, or keep placeholder until ready |
| Frontend CORS | `api_gateway_cors_allowed_origins`, `s3_cors_allowed_origins` | Add Amplify URL after frontend exists |

Keep first run:

```hcl
desired_count = 0
```

Then after image/secrets are ready:

```hcl
desired_count = 1
```

## For CG existing VPC mode

Edit:

```text
environments/opentofu/opentofu-cg-existing-vpc.tfvars
```

Fill these first:

| Value | Where to paste | Example / note |
|---|---|---|
| CG region | `aws_region` | CG-approved AWS region |
| Deployment role ARN, if used | `assume_role_arn` | Leave empty if CG runs with existing role/session |
| VPC ID | `existing_vpc_id` | `vpc-...` |
| Private subnet IDs | `existing_private_subnet_ids` | Same list used by VPC Link, internal ALB, and ECS |
| Private route table IDs | `existing_private_route_table_ids` | Needed only if `enable_vpc_endpoints=true` |
| Frontend URL | `api_gateway_cors_allowed_origins`, `s3_cors_allowed_origins` | Amplify URL or CG custom domain |
| Tags | `owner`, `cost_center`, `additional_tags` | CG governance tags |
| Bedrock model ID | `bedrock_model_id` | CG-approved Bedrock model |
| Bedrock model ARNs | `bedrock_model_arns` | Specific ARNs if CG provides them; `*` only for early test if allowed |
| Repo URL | `amplify_repository_url` | Only if `enable_amplify=true` |
| Branch | `amplify_branch_name` | `uat`, `main`, etc. |

## Values that should usually NOT be copied from the old Acies doc

Do not copy these into the CG tfvars:

- Acies account ID
- Acies IAM user name
- Acies SSO URL
- Acies ECR URL
- Acies secret values
- Acies exact resource ARNs
- Acies old subnet/security group IDs unless you are practicing in the same Acies account

## If CG provides existing resources

Change these toggles:

```hcl
create_ecr = false
existing_ecr_repository_url = "..."

create_s3_bucket = false
existing_s3_bucket_name = "..."

create_dynamodb_tables = false
existing_dynamodb_table_names = {
  sessions  = "..."
  profiles  = "..."
  docs      = "..."
  audit_log = "..."
}
existing_dynamodb_table_arns = ["..."]

create_iam_roles = false
existing_ecs_execution_role_arn = "..."
existing_ecs_task_role_arn = "..."

create_security_groups = false
existing_vpclink_security_group_id = "..."
existing_alb_security_group_id = "..."
existing_ecs_security_group_id = "..."
```
