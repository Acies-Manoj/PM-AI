"""Per-session JSON documents: the replacement for the `data/sessions/<id>/*.json` files.

A document is addressed by (session_id, doc) -- `doc` is a short name such as
"PLANNER_OUTPUT" or "ACACHE#<entry id>". Two backends, chosen once by config:

  * AWS   -- one DynamoDB item per document in the DDB_DOCS table. The JSON is stored as a
             string (`payload`) so floats / big numbers never hit DynamoDB's number rules.
             A payload over ~300 KB (DynamoDB items max out at 400 KB) is written to S3
             under `overflow/` and the item keeps only a pointer (`s3_key`).
  * local -- plain files under data/sessions/<id>/ (the pre-AWS layout), so a laptop with no
             AWS resources keeps working.

Every write bumps a `version`. `update()` uses it for optimistic concurrency, which is what
makes a read-modify-write (e.g. flipping a planner recommendation to "accepted") safe when
two tasks or two threads race.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from app.config import DATA_DIR, DDB_DOCS, S3_BUCKET, SESSION_TTL_DAYS, USE_AWS_STORAGE

# DynamoDB caps an item at 400 KB; stay well under it.
OVERFLOW_BYTES = 300_000

_SESSIONS_DIR = DATA_DIR / "sessions"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")

_local_lock = threading.RLock()

ANY = object()  # "write regardless of the stored version"


class VersionConflict(Exception):
    """A conditional write lost a race: someone else changed the item first."""


def safe_session_id(session_id: str) -> str:
    """Session ids come from URLs, and in local mode they become directory names, so only
    plain id characters are allowed (blocks `../` path tricks)."""
    if not isinstance(session_id, str) or not _SAFE_ID.match(session_id):
        raise ValueError(f"Invalid session id: {session_id!r}")
    return session_id


def _safe_doc(doc: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-.]", "_", doc.replace("#", "__"))


def json_default(o: Any):
    """Make pydantic models, numpy scalars, datetimes and sets JSON-serializable."""
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    if hasattr(o, "item") and callable(o.item):  # numpy scalar
        try:
            return o.item()
        except Exception:
            pass
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    return str(o)


def dumps(data: Any) -> str:
    return json.dumps(data, default=json_default, ensure_ascii=False)


def _ttl(days: int | None = None) -> int:
    return int(time.time()) + 86400 * (days if days is not None else SESSION_TTL_DAYS)


# =====================================================================================
# Generic DynamoDB blob item (shared with session_repo, which stores session headers in
# its own table the same way).
# =====================================================================================
def blob_get(table: str, key: dict[str, str], *, s3_prefix: str) -> tuple[Any, int | None]:
    """Return (data, version) for one item, or (None, None) if it does not exist."""
    from app.services.common import aws_clients

    ddb_key = {k: {"S": v} for k, v in key.items()}
    resp = aws_clients.dynamodb().get_item(TableName=table, Key=ddb_key, ConsistentRead=True)
    item = resp.get("Item")
    if not item:
        return None, None
    version = int(item.get("version", {"N": "0"})["N"])
    if "payload" in item:
        return json.loads(item["payload"]["S"]), version
    if "s3_key" in item:
        obj = aws_clients.s3().get_object(Bucket=S3_BUCKET, Key=item["s3_key"]["S"])
        return json.loads(obj["Body"].read().decode("utf-8")), version
    return None, version


def blob_put(
    table: str,
    key: dict[str, str],
    data: Any,
    *,
    s3_prefix: str,
    expected_version: Any = ANY,
    ttl_days: int | None = None,
    extra: dict[str, str] | None = None,
) -> int:
    """Write one item and return its new version.

    expected_version: ANY = unconditional, 0 = must not exist yet, N = must be at version N
    (raises VersionConflict otherwise). `extra` are additional string attributes (e.g.
    `user_id`) to set on the item.
    """
    from app.services.common import aws_clients

    payload = dumps(data)
    ddb = aws_clients.dynamodb()
    ddb_key = {k: {"S": v} for k, v in key.items()}
    names = {"#t": "ttl", "#u": "updated_at"}
    values: dict[str, Any] = {
        ":t": {"N": str(_ttl(ttl_days))},
        ":u": {"S": datetime.utcnow().isoformat() + "Z"},
        ":one": {"N": "1"},
    }
    sets = ["#t = :t", "#u = :u"]
    removes: list[str] = []

    if len(payload.encode("utf-8")) > OVERFLOW_BYTES:
        s3_key = f"{s3_prefix}.json"
        aws_clients.s3().put_object(
            Bucket=S3_BUCKET, Key=s3_key, Body=payload.encode("utf-8"), ContentType="application/json"
        )
        values[":k"] = {"S": s3_key}
        sets.append("s3_key = :k")
        removes.append("payload")
    else:
        values[":p"] = {"S": payload}
        sets.append("payload = :p")
        removes.append("s3_key")

    for i, (attr, val) in enumerate((extra or {}).items()):
        names[f"#x{i}"] = attr
        values[f":x{i}"] = {"S": val}
        sets.append(f"#x{i} = :x{i}")

    expr = "SET " + ", ".join(sets) + " REMOVE " + ", ".join(removes) + " ADD version :one"
    kwargs: dict[str, Any] = {}
    if expected_version is not ANY:
        if expected_version == 0:
            kwargs["ConditionExpression"] = "attribute_not_exists(version)"
        else:
            kwargs["ConditionExpression"] = "version = :ev"
            values[":ev"] = {"N": str(int(expected_version))}

    try:
        resp = ddb.update_item(
            TableName=table,
            Key=ddb_key,
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="UPDATED_NEW",
            **kwargs,
        )
    except ddb.exceptions.ConditionalCheckFailedException as exc:
        raise VersionConflict(f"{table} {key} changed since it was read") from exc
    return int(resp["Attributes"]["version"]["N"])


def blob_delete(table: str, key: dict[str, str]) -> None:
    from app.services.common import aws_clients

    aws_clients.dynamodb().delete_item(TableName=table, Key={k: {"S": v} for k, v in key.items()})


# =====================================================================================
# Public document API
# =====================================================================================
def _local_path(session_id: str, doc: str) -> Path:
    return _SESSIONS_DIR / safe_session_id(session_id) / f"{_safe_doc(doc)}.json"


def _s3_prefix(session_id: str, doc: str) -> str:
    return f"overflow/{safe_session_id(session_id)}/{_safe_doc(doc)}"


def get(session_id: str, doc: str) -> Any | None:
    """The document's data (whatever JSON was stored), or None if it does not exist."""
    return get_with_version(session_id, doc)[0]


def get_with_version(session_id: str, doc: str) -> tuple[Any | None, int | None]:
    if USE_AWS_STORAGE:
        return blob_get(DDB_DOCS, {"session_id": safe_session_id(session_id), "doc": doc}, s3_prefix=_s3_prefix(session_id, doc))
    path = _local_path(session_id, doc)
    with _local_lock:
        if not path.exists():
            return None, None
        try:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, None
    return wrapper["data"], int(wrapper.get("version", 1))


def put(session_id: str, doc: str, data: Any, *, expected_version: Any = ANY, ttl_days: int | None = None) -> int:
    """Create or replace a document; returns the new version."""
    if USE_AWS_STORAGE:
        return blob_put(
            DDB_DOCS,
            {"session_id": safe_session_id(session_id), "doc": doc},
            data,
            s3_prefix=_s3_prefix(session_id, doc),
            expected_version=expected_version,
            ttl_days=ttl_days,
        )
    path = _local_path(session_id, doc)
    with _local_lock:
        current = 0
        if path.exists():
            try:
                current = int(json.loads(path.read_text(encoding="utf-8")).get("version", 1))
            except (OSError, json.JSONDecodeError):
                current = 0
        if expected_version is not ANY and expected_version != current:
            raise VersionConflict(f"{session_id}/{doc} changed since it was read")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps({"version": current + 1, "data": data}), encoding="utf-8")
        return current + 1


def update(
    session_id: str,
    doc: str,
    fn: Callable[[Any], Any],
    *,
    default: Any = None,
    retries: int = 8,
) -> Any:
    """Atomic read-modify-write. `fn` receives the current data (or `default` if the document
    does not exist yet) and returns the new data. If another writer got in between, the whole
    thing is retried with fresh data, so concurrent updates are never silently lost."""
    last: Exception | None = None
    for attempt in range(retries):
        current, version = get_with_version(session_id, doc)
        base = default if current is None else current
        new_data = fn(base)
        try:
            put(session_id, doc, new_data, expected_version=(version or 0))
            return new_data
        except VersionConflict as exc:
            last = exc
            time.sleep(0.02 * (attempt + 1))
    raise VersionConflict(f"Could not update {session_id}/{doc} after {retries} attempts") from last


def delete(session_id: str, doc: str) -> None:
    if USE_AWS_STORAGE:
        blob_delete(DDB_DOCS, {"session_id": safe_session_id(session_id), "doc": doc})
        return
    path = _local_path(session_id, doc)
    with _local_lock:
        path.unlink(missing_ok=True)


def list_docs(session_id: str, prefix: str = "") -> dict[str, Any]:
    """Every document of a session whose name starts with `prefix`, as {doc: data}."""
    out: dict[str, Any] = {}
    if USE_AWS_STORAGE:
        from app.services.common import aws_clients

        ddb = aws_clients.dynamodb()
        kwargs: dict[str, Any] = {
            "TableName": DDB_DOCS,
            "ConsistentRead": True,
            "KeyConditionExpression": "session_id = :s" + (" AND begins_with(#d, :p)" if prefix else ""),
            "ExpressionAttributeValues": {":s": {"S": safe_session_id(session_id)}},
        }
        if prefix:
            kwargs["ExpressionAttributeNames"] = {"#d": "doc"}
            kwargs["ExpressionAttributeValues"][":p"] = {"S": prefix}
        while True:
            resp = ddb.query(**kwargs)
            for item in resp.get("Items", []):
                name = item["doc"]["S"]
                if "payload" in item:
                    out[name] = json.loads(item["payload"]["S"])
                elif "s3_key" in item:
                    obj = aws_clients.s3().get_object(Bucket=S3_BUCKET, Key=item["s3_key"]["S"])
                    out[name] = json.loads(obj["Body"].read().decode("utf-8"))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return out

    folder = _SESSIONS_DIR / safe_session_id(session_id)
    safe_prefix = _safe_doc(prefix)
    with _local_lock:
        if not folder.exists():
            return out
        for path in folder.glob("*.json"):
            if not path.stem.startswith(safe_prefix):
                continue
            try:
                wrapper = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(wrapper, dict) and "data" in wrapper and "version" in wrapper:
                # local names are the sanitized form ("ACACHE__<id>"); map "__" back to "#".
                out[path.stem.replace("__", "#", 1)] = wrapper["data"]
    return out
