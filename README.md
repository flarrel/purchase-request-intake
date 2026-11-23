# Purchase Request Intake

Purchase Request Intake turns CSV batches with Indonesian purchase notes into
a register of approved requests. Operations staff can preview and clean a
batch, extract request details with a local language model, and inspect
exceptions in a review queue. The app routes higher-value requests to finance
review and exports both the approved register and an operations report.

## Run on Apple Silicon macOS

Requires Python 3.12, Git for cloning, and about 540 MB of initial downloads.
Run the following commands from the cloned repository.

```sh
./tools/setup-model
./tools/run-model
```

Start the operator app in a second terminal.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m intake --model-key-file ../runtime/model.key
```

Open [Purchase Intake](http://127.0.0.1:8080). The model server and app listen
only on loopback. The pinned llama.cpp runtime, Qwen weights, generated key, and
SQLite database live in the sibling `runtime/` directory. The deterministic
baseline can run without model downloads using `python3 -m intake --rules`.
Use `--port`, `--db`, or `--model-url` to run against another local instance.

The pinned runtime is [llama.cpp b12651](https://github.com/ggml-org/llama.cpp/releases/tag/b12651).
The pinned model is [Qwen2.5-0.5B-Instruct Q5_K_M](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/tree/9217f5db79a29953eb74d5343926648285ec7e67).

## Process a sample batch

Generate a CSV with four fictional purchase requests.

```sh
python3 examples/make_demo.py > ../runtime/demo.csv
```

1. Open **Import**, select the sample CSV, and preview it. The app flags the
   invalid amount on the fourth row. Save the valid rows and open the queue.
2. Open **DEMO-101** and process it. Verify the draft against the note if the
   model routes it to review.
3. Process **DEMO-102** and open **Finance review**. Check the vendor
   `PT Sumber Fiktif`, item `keyboard rapat`, quantity `4`, and category `it`.
   Enter a continuous excerpt such as `item: keyboard rapat; jumlah 4 unit`
   in **Source summary**, then approve.
4. Process **DEMO-103** and reject it in review because the note lacks a
   confirmed vendor and quantity. Check **Notifications**, then download the
   operations report and approved register to compare their contents.

## Validation and review

CSV import normalizes columns, references, dates, and amounts and reports
invalid rows and conflicts. Each import uses a reference and a fingerprint of
the normalized data to recognize replays.

The local provider proposes a vendor, item, quantity, category, and extractive
summary. The workflow checks that the proposed text appears in the note,
checks the quantity, and reconciles the category when a single item-catalog
category matches. Automatic approval requires a request dated within the last
90 days, an amount below the finance threshold, explicitly labeled vendor and
item fields that match the extraction, and a corroborated category.
Requests at or above IDR 2,000,000 or USD 150 go to
finance review. Ambiguous or incomplete records go to human review regardless
of amount. Review can correct or reject a request. Corrections still need
source support. A retryable model error gets two total attempts, then produces
an alert with options to retry or review manually.

State changes, register writes, and notifications commit together in SQLite.
Approval creates an entry in the local register. The app is designed for a
single local operator. Use synthetic inputs. Before storing notes, the app
redacts recognizable email addresses and Indonesian phone numbers.

## Verify

```sh
PYTHONDONTWRITEBYTECODE=1 INTAKE_HTTP_TEST=1 python3 -m unittest discover -s tests -v
```

The HTTP test uses a deterministic provider double to exercise the operator
paths and reproduce model failures. The [evaluation notes](evaluation/README.md)
describe the separate inference runs with the actual local model.
