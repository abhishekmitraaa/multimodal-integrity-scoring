# shared/schema

`event.v1.schema.json` is the canonical client→server event contract (SPEC section 4). Both the
TypeScript client and the Python server validate against it.

`examples/` holds **synthetic** batches, regenerated with
`python shared/schema/examples/make_synthetic_examples.py`. The contract tests are in
`tests/test_event_schema.py`.
