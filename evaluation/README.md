# Local model evaluation

The task is to extract vendor, item and quantity, classify the item, and
select a source-grounded summary from an Indonesian purchase note. The
deterministic baseline reads labeled fields and uses a keyword catalog. The
model is Qwen2.5-0.5B-Instruct Q5_K_M through llama.cpp b12651 on CPU, with
temperature zero and seed 42. The application also checks the model output
against the note and reconciles its category with the catalog when exactly
one category matches.

## Data and scoring

The fixture generator creates 60 development and 40 holdout notes. Holdout
notes use different phrasing templates and item variants. The prompt
comparison uses the same 12 development notes for each revision, followed by
four repeated calls per revision. Development and holdout fixtures contain
fictional vendor names and a deliberately small vocabulary.

Extraction scores exact vendor, item, and quantity values separately. Macro-F1
weights the four categories equally. A grounded summary is a verbatim
continuous excerpt containing the expected item. An incorrectly auto-written
row is a case that passes the source and catalog checks despite an incorrect
field, category, or summary. Review counts here reflect those checks, with
amount, date, and ambiguity routing exercised separately through the app.

## Results

The initial benchmark ran on 24 November 2026.

The selected prompt was v2. On development data, it returned 35/36 correct
fields, compared with 28/36 for v1 and 34/36 for v3. Its 12/12 grounded
summaries compared with 0/12 for v1 and 11/12 for v3. All three revisions
reproduced their initial outputs on the four repeated calls for each.

The holdout run used 40 notes.

- Rules returned **56/120 exact fields** and **8/40 grounded summaries**.
  It omitted 32 summaries. Raw classification macro-F1 was **1.000**.
- The model returned **112/120 exact fields (93.3%)** and **25/40 grounded
  summaries (62.5%)**. The other 15 summaries failed the grounding criterion.
  Raw model classification macro-F1 was **0.262**, rising to **0.975** in the
  workflow after catalog reconciliation.
- Both workflows routed **32/40** cases to review or error under the source
  and catalog checks. The model workflow passed eight records through those
  checks with **zero incorrect automatic writes** in this sample. Median
  model-call latency was **0.405 seconds**.

For example, in `holdout-01` the model classified a notebook as facilities
and rewrote the supplier sentence. The catalog corrected the category to
office. The rewritten summary still failed the source check and the request
was held for review.

A separate HTTP check with the local model imported four sample rows and
flagged one invalid amount. The check confirmed that the operator could
approve a procurement request and a finance request through review, reject
the incomplete request, and see the outcomes in both exports and the
notification inbox.

The keyword catalog already knows the benchmark item families. Its high
classification score is specific to that setting. The model improves
extraction on the tested phrasing while weak raw classification and uneven
summary grounding still require the catalog and review controls. The
synthetic samples establish behavior on these cases and leave accuracy on
real purchase data unmeasured.

## Reproduce

Start the pinned model with `./tools/run-model` from the repo. Run the evaluation from a second terminal.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m evaluation.run \
  --split development --key-file ../runtime/model.key \
  --model-id 'Qwen2.5-0.5B-Instruct Q5_K_M (llama.cpp b12651, CPU)' \
  --revision v1 v2 v3 --output ../runtime/development.json

PYTHONDONTWRITEBYTECODE=1 python3 -m evaluation.run \
  --split holdout --key-file ../runtime/model.key \
  --model-id 'Qwen2.5-0.5B-Instruct Q5_K_M (llama.cpp b12651, CPU)' \
  --revision v2 --output ../runtime/holdout.json
```

The generated JSON includes fixture hashes, evaluated case IDs, raw and
reconciled categories, validation failures, and measured latencies.
