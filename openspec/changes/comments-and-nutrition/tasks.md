# Tasks

## 1. Nutrition fields

- [x] 1.1 Add the per-activity and per-day nutrition and hydration columns to the schema and the ingest mappers; test: ride-without-logged-intake scenario against fixtures

## 2. Comments in

- [x] 2.1 Ingest activity comments into the subjective table, idempotent by comment id, with pin indices; test: pinned and edited-comment scenarios
- [x] 2.2 `fuel_tag.parse(text)` deterministic parser; test: full, partial, no-tag and later-tag scenarios
- [x] 2.3 Reconcile tag carbohydrate with the platform field, retaining both; test: disagreement scenario

## 3. Comments out

- [x] 3.1 `write_comments` config switch, default false, loaded by `domestique.config`; test: default-configuration scenario posts nothing
- [x] 3.2 Comment writer with fixed system marker, pin indices, and per-statement source-layer labels; test: interval-remark and athlete-comment-present scenarios against a fake client
