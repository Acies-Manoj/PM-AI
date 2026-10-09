# CI role for the GitHub Actions pipelines

The workflows in `.github/workflows/` sign in to AWS with OpenID Connect, so no access keys are stored
in GitHub. GitHub proves which repo and branch is running, and AWS lets that identity assume one role.

| File | Purpose |
|---|---|
| `github-oidc-trust-policy.json` | Who may assume the role: only this repo, the infra branch, the `practice` environment and pull requests |
| `pipeline-permissions-policy.json` | What the role may do: the services the stack uses, IAM only for `pmai-*` roles, S3 only for `pmai-*` buckets (including the state bucket) |

Both files hold placeholders: `<ACCOUNT_ID>`, `<GITHUB_USER>`, `<OWNER_ID>`, `<REPO>`, `<REPO_ID>`.
Do **not** commit real values.

Newer GitHub repositories put numeric ids in the OIDC subject, for example
`repo:<GITHUB_USER>@<OWNER_ID>/<REPO>@<REPO_ID>:ref:refs/heads/<branch>`. If the login fails with
"Not authorized to perform sts:AssumeRoleWithWebIdentity" although the names look right, print the real
`sub` claim (a temporary workflow step that decodes the OIDC token and prints `sub`) and match it exactly.
The ids are public: `https://api.github.com/repos/<GITHUB_USER>/<REPO>` returns `id` (the repo id) and
`owner.id` (the owner id).
Copy each file to a name ending `.local.json` (git-ignored), replace the placeholders, then run, with an
identity that may create IAM roles:

```
aws iam create-role --role-name gha-practice-manoj --assume-role-policy-document file://infra/ci/trust.local.json --profile <profile>
aws iam put-role-policy --role-name gha-practice-manoj --policy-name pmai-deploy --policy-document file://infra/ci/permissions.local.json --profile <profile>
```

The role is deliberately **not** named `pmai-*`, so the IAM permissions above cannot be used to change
the role itself.

The account must already have the OIDC provider `token.actions.githubusercontent.com`
(`aws iam list-open-id-connect-providers`). An account can have only one.

GitHub settings on the repo (Settings, Secrets and variables, Actions):

| Kind | Name | Value |
|---|---|---|
| Variable | `AWS_ROLE_ARN` | ARN of `gha-practice-manoj` |
| Variable | `TF_STATE_BUCKET` | Name of the state bucket |
| Secret | `TF_VAR_amplify_access_token` | GitHub token for Amplify |
| Environment | `practice` | Required reviewer: you |
