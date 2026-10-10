#!/usr/bin/env bash
# A smoke test that asks something. Waiting for a rollout proves the scheduler ran;
# it does not prove the pod can answer. So: wait for readiness, then put a real
# question to the service and assert the shape of what comes back — the outcome,
# a statement, and a citation that names a document and a device.
#
# The question is one of the recorded evaluation cases, word for word, so the whole
# lock runs with no network and no API key.
set -euo pipefail

# 127.0.0.1, not localhost: kind publishes the node port on IPv4 only, and on a host
# where localhost resolves to ::1 first the connection is accepted and then closed —
# "Recv failure: Connection closed by peer", which reads like a broken service and is not.
BASE="${1:-http://127.0.0.1:30080}"
QUESTION='Qual é o objetivo da avaliação interna de risco prevista na Circular 3.978?'

echo "== readiness"
curl -fsS "$BASE/readyz" | python3 -m json.tool

echo "== asking"
BODY=$(curl -fsS -X POST "$BASE/ask" \
  -H 'content-type: application/json' \
  --data "$(python3 -c 'import json,sys; print(json.dumps({"question": sys.argv[1]}))' "$QUESTION")")
echo "$BODY" | python3 -m json.tool

python3 - "$BODY" <<'PY'
import json, sys
body = json.loads(sys.argv[1])
assert body["outcome"] == "answered", f'outcome is {body["outcome"]}'
statements = body["draft"]["statements"]
assert statements, "an answer with no statement is not an answer"
citation = statements[0]["citations"][0]
assert citation["doc_id"].startswith("circular-3978-2020"), citation
assert citation["locator"] == "art. 10, caput", citation
assert "identificar e mensurar o risco" in statements[0]["text"]
print("smoke ok: answered, cited", citation["doc_id"], citation["locator"])
PY

echo "== metrics"
curl -fsS "$BASE/metrics" | grep -E 'eclusa_ready|outcome="answered"'
