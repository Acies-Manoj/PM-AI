"""One lazily-created boto3 client per AWS service, shared by the whole process.

boto3 *clients* are thread-safe, which matters because the Planner and the Analysis
engine fan LLM calls out over a ThreadPoolExecutor. Creating a client is the slow part
(it resolves credentials and loads the service model), so each is built once.

Credentials are never read from code or env vars here: on ECS the task role supplies them
through the container credentials endpoint, and locally boto3 uses whatever
`aws configure` / AWS_PROFILE gave it.
"""
from __future__ import annotations

import threading

import boto3
from botocore.config import Config

from app.config import AWS_REGION, BEDROCK_REGION, TRANSLATE_REGION

_lock = threading.Lock()
_clients: dict[str, object] = {}


def _get(key: str, factory):
    client = _clients.get(key)
    if client is None:
        with _lock:
            client = _clients.get(key)
            if client is None:
                client = factory()
                _clients[key] = client
    return client


def s3():
    return _get(
        "s3",
        lambda: boto3.client(
            "s3",
            region_name=AWS_REGION,
            # Presigned URLs must use the regional endpoint + SigV4, or browsers get
            # redirected (and the CORS preflight fails) for buckets outside us-east-1.
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        ),
    )


def dynamodb():
    """The low-level DynamoDB client (items are passed as {"S": "..."} etc.)."""
    return _get(
        "dynamodb",
        lambda: boto3.client(
            "dynamodb",
            region_name=AWS_REGION,
            config=Config(retries={"max_attempts": 5, "mode": "standard"}),
        ),
    )


def bedrock_runtime():
    """Converse / InvokeModel. LLM calls here are slow (code generation), hence the long
    read timeout; botocore's standard retry mode backs off on throttling."""
    return _get(
        "bedrock-runtime",
        lambda: boto3.client(
            "bedrock-runtime",
            region_name=BEDROCK_REGION,
            config=Config(
                read_timeout=120,
                connect_timeout=10,
                retries={"max_attempts": 4, "mode": "standard"},
            ),
        ),
    )


def bedrock_agent():
    """Prompt Management (GetPrompt)."""
    return _get(
        "bedrock-agent",
        lambda: boto3.client(
            "bedrock-agent",
            region_name=BEDROCK_REGION,
            config=Config(retries={"max_attempts": 3, "mode": "standard"}),
        ),
    )


def translate():
    return _get(
        "translate",
        lambda: boto3.client(
            "translate",
            region_name=TRANSLATE_REGION,
            config=Config(retries={"max_attempts": 4, "mode": "standard"}),
        ),
    )


def reset() -> None:
    """Drop every cached client (used by tests that swap in a mocked AWS)."""
    with _lock:
        _clients.clear()
