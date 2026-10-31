# Core Demo implementation status

No SQL in this directory has been executed against MySQL. The 11 tables/82 fields match contract names. SQL types and nullability are technical Demo choices, not approved business semantics. No cross-database foreign keys. appeal is provisionally placed in the business schema.

Run from repository root:

```powershell
python -B data/tools/build_core.py
python -B data/tools/check_core.py
python -B data/tools/test_synthetic.py
python -B data/tools/synthetic.py --count-only
```

txn uses a composite primary key including its partition key; IDs are supplied by the writer. Monthly partitions cover October-December 2026. p_before and p_future are explicit catch-all staging partitions: monthly maintenance and partition pruning are NOT yet runtime verified. Four index paths target task status, task transactions ordered by date, task metric code and task report version. EXPLAIN is still required.

The physical dictionary is a separate technical supplement. DA-06 PR #3 was reviewed through local commit 137e199; no cherry-pick or branch merge was performed. Its business dictionary/history are not overwritten.

Migration revisions/environment/configuration are implemented; the Python3.11 dependency environment and running Demo server are still missing. Revision 0001 creates tables; 0002 creates views/grants. Downgrade to 0001 revokes grants/drops views; downgrade to base rejects nonempty tables and needs explicit authorization. It is not a general production rollback. DDL can partially commit.

Security: masking views, account/name format checks and append-only runtime grants are implemented but not applied or runtime verified. JSON/free-text ingress needs upstream sanitization; views do not permit plaintext storage. Logical deletion, historical binding and OCR persistence need contract/owner decisions. Do not treat this as completed backend integration. Synthetic values are Demo-only, not risk thresholds or banking data.
