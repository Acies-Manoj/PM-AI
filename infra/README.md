# PMAI OpenTofu Infrastructure

This `/infra` folder is a template implementation for the PMAI AWS setup.

It follows the same architecture described in the E2E/backend/frontend deployment notes:

```text
Amplify frontend
   -> API Gateway HTTP API
   -> VPC Link
   -> internal ALB
   -> ECS Fargate FastAPI backend
   -> S3, DynamoDB, Secrets Manager, CloudWatch, Translate, Bedrock
```

## Important safety point

This code does **not** contain real AWS credentials, account IDs, secret values, subnet IDs, or client-specific values.

You must fill the values in one of these files:

```text
environments/opentofu/opentofu-acies-practice.tfvars
environments/opentofu/opentofu-cg-existing-vpc.tfvars
```

## Two modes

### 1. Acies learning/practice mode

Use:

```hcl
create_vpc = true
```

This creates a fresh VPC, public/private subnets, NAT, route tables, and app resources.

Run with:

```bash
tofu init
tofu fmt -recursive
tofu validate
tofu plan -var-file=environments/opentofu/opentofu-acies-practice.tfvars
```

Only apply after reading the plan:

```bash
tofu apply -var-file=environments/opentofu/opentofu-acies-practice.tfvars
```

### 2. CG existing VPC mode

Use:

```hcl
create_vpc = false
existing_vpc_id = "vpc-..."
existing_private_subnet_ids = ["subnet-a", "subnet-b"]
```

This reuses CG's existing VPC and private subnets, while creating the PMAI app resources.

Run with:

```bash
tofu init -backend-config=environments/opentofu/backend.hcl
tofu fmt -recursive
tofu validate
tofu plan -var-file=environments/opentofu/opentofu-cg-existing-vpc.tfvars
```

Only apply after CG reviews the plan:

```bash
tofu apply -var-file=environments/opentofu/opentofu-cg-existing-vpc.tfvars
```

## Recommended first deployment flow

Use `desired_count = 0` for the first apply. This creates infrastructure but does not start the backend container yet.

Then:

1. Push the Docker image to ECR.
2. Add secret values to Secrets Manager, if OpenRouter/DeepL are enabled.
3. Set `desired_count = 1`.
4. Run `tofu plan` and `tofu apply` again.

## Main values to fill for CG

Use `environments/opentofu/opentofu-cg-existing-vpc.tfvars`.

Required values:

```hcl
aws_region = "CHANGE_ME_CG_REGION"
existing_vpc_id = "CHANGE_ME_VPC_ID"
existing_private_subnet_ids = [
  "CHANGE_ME_PRIVATE_SUBNET_ID_A",
  "CHANGE_ME_PRIVATE_SUBNET_ID_B"
]
api_gateway_cors_allowed_origins = ["CHANGE_ME_FRONTEND_ORIGIN"]
s3_cors_allowed_origins = ["CHANGE_ME_FRONTEND_ORIGIN"]
owner = "CHANGE_ME_OWNER"
cost_center = "CHANGE_ME_COST_CENTER"
bedrock_model_id = "CHANGE_ME_CG_APPROVED_BEDROCK_MODEL_ID"
bedrock_model_arns = ["CHANGE_ME_CG_APPROVED_BEDROCK_MODEL_ARN_OR_STAR_FOR_INITIAL_TEST"]
```

Optional depending on CG rules:

```hcl
enable_vpc_endpoints = true
existing_private_route_table_ids = ["rtb-a", "rtb-b"]
permissions_boundary_arn = "arn:..."
create_iam_roles = false
existing_ecs_execution_role_arn = "arn:..."
existing_ecs_task_role_arn = "arn:..."
create_security_groups = false
existing_vpclink_security_group_id = "sg-..."
existing_alb_security_group_id = "sg-..."
existing_ecs_security_group_id = "sg-..."
```

## Bedrock

Bedrock is enabled by default as an application runtime option:

```hcl
enable_bedrock = true
bedrock_model_id = "CHANGE_ME_CG_APPROVED_BEDROCK_MODEL_ID"
bedrock_model_arns = ["CHANGE_ME_CG_APPROVED_BEDROCK_MODEL_ARN_OR_STAR_FOR_INITIAL_TEST"]
```

This version intentionally does **not** create a prompt registry or Bedrock Prompt Management resource.

## Secret values

Secret containers can be created by OpenTofu, but secret values should be inserted separately.

Example:

```bash
aws secretsmanager put-secret-value \
  --secret-id <openrouter_secret_arn_or_name> \
  --secret-string '<actual-secret-value>' \
  --region <region>
```

Do not put secret values inside `.tf` or `.tfvars` files.

## File map

```text
versions.tf                  Provider version and optional backend block
providers.tf                 AWS provider configuration
variables.tf                 All configurable values
locals.tf                    Derived names/IDs/env vars
network.tf                   VPC/subnets/NAT/routes/endpoints
security_groups.tf           VPC Link, ALB, ECS security groups
ecr.tf                       Backend Docker image repository
iam.tf                       ECS roles and app permissions
secrets.tf                   Placeholder secret containers
storage.tf                   S3 bucket and DynamoDB tables
load_balancer.tf             Internal ALB, target group, listener
ecs.tf                       ECS cluster, task definition, service
api_gateway.tf               HTTP API, VPC Link, ALB integration
amplify.tf                   Optional Amplify app and branch
outputs.tf                   Useful output values
```
