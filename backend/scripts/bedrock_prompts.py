#!/usr/bin/env python
"""Manage the PM-AI system prompts in Amazon Bedrock Prompt Management.

The system prompts are NOT in the Python code. Each LLM call asks for its prompt by call name
(see app/services/common/llm.py, `system_prompt`) and gets it from Bedrock when the name is in the
BEDROCK_PROMPT_IDS environment variable. The text files in backend/prompts/<call_name>.txt are the
starting point you upload once, and a local copy for development; the Docker image does not
contain them.

Run from the backend folder, with AWS credentials that may use Prompt Management
(bedrock:CreatePrompt, UpdatePrompt, CreatePromptVersion, GetPrompt, ListPrompts):

  python scripts/bedrock_prompts.py create --dry-run    show what would be created
  python scripts/bedrock_prompts.py create              upload every prompt file (+ a version each)
  python scripts/bedrock_prompts.py verify              compare Bedrock with the files
  python scripts/bedrock_prompts.py pull                download Bedrock's text back into the files (a backup)
  python scripts/bedrock_prompts.py create --update     upload the files again as a NEW version

`create` prints the BEDROCK_PROMPT_IDS value to put in the environment. Use --only a,b to limit
it to some call names, --region for another region (default BEDROCK_REGION / AWS_REGION).
Variables written {{like_this}} in a file are filled in by the code at call time.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# --region must reach app.config before it is imported.
for _i, _arg in enumerate(sys.argv):
    if _arg == "--region" and _i + 1 < len(sys.argv):
        os.environ["BEDROCK_REGION"] = sys.argv[_i + 1]

from app.config import MODEL_BY_CALL, PROMPTS_DIR  # noqa: E402

# Every LLM call has exactly one system prompt, named after the call.
CALLS: list[str] = list(MODEL_BY_CALL)

# The {{variables}} the code fills in per call (everything else is fixed text).
VARIABLES: dict[str, tuple[str, ...]] = {
    "analysis_designer_template_match": ("template_catalog",),
    "analysis_suggester": ("max_suggestions",),
    "feature_suggester": ("max_suggestions",),
    "drilldown_path": ("max_steps", "max_charts"),
}

NAME_PREFIX = "pmai-"
_VARIABLE = re.compile(r"\{\{(\w+)\}\}")


def prompt_name(call: str) -> str:
    return NAME_PREFIX + call


def _path(call: str) -> Path:
    return PROMPTS_DIR / f"{call}.txt"


def source_text(call: str) -> str:
    path = _path(call)
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist")
    return path.read_bytes().decode("utf-8")


def check_placeholders(call: str, text: str) -> list[str]:
    """Problems that would make Prompt Management misread the text (empty list = fine)."""
    declared = set(VARIABLES.get(call, ()))
    found = set(_VARIABLE.findall(text))
    problems = []
    if found - declared:
        problems.append(f"unexpected {{{{variable}}}} placeholders: {sorted(found - declared)}")
    if text.count("{{") != len(_VARIABLE.findall(text)):
        problems.append("contains '{{' that is not a {{variable}} (Bedrock would treat it as one)")
    missing = declared - found
    if missing:
        problems.append(f"the code supplies {sorted(missing)} but the text never uses it")
    return problems


def _select(only: str | None) -> list[str]:
    if not only:
        return list(CALLS)
    wanted = [w.strip() for w in only.split(",") if w.strip()]
    unknown = [w for w in wanted if w not in CALLS]
    if unknown:
        sys.exit(f"Unknown call name(s): {', '.join(unknown)}\nKnown: {', '.join(CALLS)}")
    return wanted


def _norm(text: str) -> str:
    return "\n".join(line.rstrip() for line in (text or "").strip().splitlines())


def _client():
    from app.services.common import aws_clients

    return aws_clients.bedrock_agent()


def _existing_prompts(client) -> dict[str, str]:
    """name -> prompt id for every prompt already in Prompt Management."""
    found: dict[str, str] = {}
    token = None
    while True:
        kwargs = {"maxResults": 100}
        if token:
            kwargs["nextToken"] = token
        resp = client.list_prompts(**kwargs)
        for item in resp.get("promptSummaries", []):
            found[item["name"]] = item["id"]
        token = resp.get("nextToken")
        if not token:
            return found


def _latest_version(client, prompt_id: str) -> str | None:
    """Highest numbered (non-DRAFT) version of a prompt, or None if it has none yet."""
    best = 0
    token = None
    while True:
        kwargs = {"promptIdentifier": prompt_id, "maxResults": 100}
        if token:
            kwargs["nextToken"] = token
        resp = client.list_prompts(**kwargs)  # with an identifier it lists that prompt's versions
        for item in resp.get("promptSummaries", []):
            version = str(item.get("version", ""))
            if version.isdigit():
                best = max(best, int(version))
        token = resp.get("nextToken")
        if not token:
            break
    return str(best) if best else None


def _variant(call: str, text: str, model: str | None) -> dict:
    variables = [{"name": v} for v in VARIABLES.get(call, ())]
    text_cfg: dict = {"text": text}
    if variables:
        text_cfg["inputVariables"] = variables
    variant: dict = {"name": "default", "templateType": "TEXT", "templateConfiguration": {"text": text_cfg}}
    if model:
        variant["modelId"] = model
    return variant


def _with_model_fallback(fn, variant: dict):
    """Create/update with a model id; if Bedrock rejects the id, retry without one (a variant's
    model is only a console convenience -- the app picks the model per call at run time)."""
    try:
        return fn(variant)
    except Exception as exc:  # noqa: BLE001
        if "modelId" in variant and "model" in str(exc).lower() and "validation" in str(exc).lower():
            print(f"    model id rejected ({exc}); retrying without a model")
            return fn({k: v for k, v in variant.items() if k != "modelId"})
        raise


def _load_ids(ids_file: str | None) -> dict[str, str]:
    raw = Path(ids_file).read_text(encoding="utf-8") if ids_file else os.getenv("BEDROCK_PROMPT_IDS", "")
    if not raw.strip():
        sys.exit("No prompt ids: set BEDROCK_PROMPT_IDS or pass --ids prompts_export/bedrock_prompt_ids.json")
    return json.loads(raw)


# --------------------------------------------------------------------------- commands
def cmd_create(args) -> int:
    from app.config import BEDROCK_DEFAULT_MODEL

    model = args.model or BEDROCK_DEFAULT_MODEL
    client = None if args.dry_run else _client()
    existing = {} if args.dry_run else _existing_prompts(client)
    ids: dict[str, str] = {}
    failures = 0

    for call in _select(args.only):
        name = prompt_name(call)
        try:
            text = source_text(call)
        except FileNotFoundError as exc:
            print(f"SKIP   {call}: {exc}")
            failures += 1
            continue
        problems = check_placeholders(call, text)
        if problems:
            print(f"SKIP   {call}: {'; '.join(problems)}")
            failures += 1
            continue
        if args.dry_run:
            print(f"DRY    {call:34s} -> {name} ({len(text)} chars, variables={list(VARIABLES.get(call, ()))})")
            continue
        try:
            variant = _variant(call, text, model)
            if name in existing and not args.update:
                prompt_id = existing[name]
                latest = _latest_version(client, prompt_id)
                ids[call] = f"{prompt_id}:{latest}" if latest else prompt_id
                print(f"EXISTS {call:34s} {ids[call]}  (use --update to upload the file as a new version)")
                continue
            if name in existing:
                prompt_id = existing[name]
                _with_model_fallback(
                    lambda v: client.update_prompt(
                        promptIdentifier=prompt_id, name=name, defaultVariant="default", variants=[v],
                        description=f"PM-AI system prompt for {call}",
                    ),
                    variant,
                )
                verb = "UPDATED"
            else:
                created = _with_model_fallback(
                    lambda v: client.create_prompt(
                        name=name, defaultVariant="default", variants=[v],
                        description=f"PM-AI system prompt for {call}",
                    ),
                    variant,
                )
                prompt_id = created["id"]
                verb = "CREATED"
            version = client.create_prompt_version(
                promptIdentifier=prompt_id,
                description="uploaded from file" if verb == "CREATED" else "updated from file",
            )["version"]
            ids[call] = f"{prompt_id}:{version}"
            print(f"{verb:7s}{call:34s} {ids[call]}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            hint = "  (is Prompt Management allowed for this user? bedrock:CreatePrompt / CreatePromptVersion)" if "AccessDenied" in str(exc) else ""
            print(f"FAILED {call}: {exc}{hint}")

    if ids:
        value = json.dumps(ids, separators=(",", ":"))
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "bedrock_prompt_ids.json").write_text(json.dumps(ids, indent=2), encoding="utf-8")
        print("\n" + "=" * 78)
        print("Local .env / shell:\n")
        print(f"BEDROCK_PROMPT_IDS={value}")
        print("\nECS task definition (environment entry):\n")
        print(json.dumps({"name": "BEDROCK_PROMPT_IDS", "value": value}, indent=2))
        print(f"\nAlso saved to {(out / 'bedrock_prompt_ids.json').resolve()}")
    return 1 if failures else 0


def cmd_verify(args) -> int:
    from app.services.common import llm

    ids = _load_ids(args.ids_file)
    mismatches = 0
    for call in _select(args.only):
        if call not in ids:
            print(f"UNSET   {call:34s} (not in BEDROCK_PROMPT_IDS)")
            mismatches += 1
            continue
        try:
            remote = llm._fetch_prompt_text(ids[call])
        except Exception as exc:  # noqa: BLE001
            print(f"MISSING {call:34s} {ids[call]}: {exc}")
            mismatches += 1
            continue
        try:
            local = source_text(call)
        except FileNotFoundError:
            print(f"NOFILE  {call:34s} {ids[call]}  (no local file to compare with)")
            continue
        if _norm(remote) == _norm(local):
            print(f"OK      {call:34s} {ids[call]}")
        else:
            mismatches += 1
            print(f"DIFFERS {call:34s} {ids[call]}  (Bedrock differs from backend/prompts/{call}.txt)")
            if args.diff:
                diff = difflib.unified_diff(_norm(local).splitlines(), _norm(remote).splitlines(), "file", "bedrock", lineterm="", n=1)
                for line in list(diff)[:40]:
                    print("        " + line)
    return 1 if mismatches else 0


def cmd_pull(args) -> int:
    """Write what Bedrock holds (the versions in BEDROCK_PROMPT_IDS) into backend/prompts/."""
    from app.services.common import llm

    ids = _load_ids(args.ids_file)
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0
    for call in _select(args.only):
        if call not in ids:
            print(f"UNSET   {call}")
            failures += 1
            continue
        try:
            text = llm._fetch_prompt_text(ids[call])
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED  {call}: {exc}")
            failures += 1
            continue
        if not text:
            print(f"EMPTY   {call}")
            failures += 1
            continue
        _path(call).write_text(text, encoding="utf-8", newline="")
        print(f"PULLED  {call:34s} {ids[call]}  -> {_path(call)}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", help="Bedrock region (default BEDROCK_REGION / AWS_REGION)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create", help="upload the prompt files to Bedrock (and a version each)")
    p.add_argument("--out", default="prompts_export")
    p.add_argument("--only")
    p.add_argument("--model", help="model id stored on the prompt variant (default BEDROCK_DEFAULT_MODEL)")
    p.add_argument("--update", action="store_true", help="upload the files as a new version of prompts that already exist")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_create)

    p = sub.add_parser("verify", help="compare Bedrock's text with the files")
    p.add_argument("--only")
    p.add_argument("--ids", dest="ids_file", help="JSON file of {call: 'ID:version'} (default: BEDROCK_PROMPT_IDS)")
    p.add_argument("--diff", action="store_true")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("pull", help="download Bedrock's text into backend/prompts/ (a backup)")
    p.add_argument("--only")
    p.add_argument("--ids", dest="ids_file", help="JSON file of {call: 'ID:version'} (default: BEDROCK_PROMPT_IDS)")
    p.set_defaults(fn=cmd_pull)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
