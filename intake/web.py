"""Loopback operator interface for imports, review, notifications and exports."""

from collections import Counter
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from secrets import compare_digest, token_urlsafe
from urllib.parse import parse_qs, urlencode, urlsplit

from .data import CATEGORIES, MAX_BYTES, parse_csv
from .skill import FIELDS, RulesProvider
from .workflow import export_operations, export_register, review_request, run_request

ASSETS = Path(__file__).with_name("web_assets")
STATUSES = ("queued", "review", "error", "approved", "rejected")
LABELS = {"queued": "Queued", "review": "Review", "error": "Model error",
          "approved": "Approved", "rejected": "Rejected"}


def h(value):
    return escape(str(value) if value is not None else "", quote=True)


def page(title, content, message=""):
    notice = f'<p class="notice" role="status">{h(message)}</p>' if message else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{h(title)} · Purchase Intake</title><link rel="stylesheet" href="/assets/style.css">
<script src="/assets/import.js" defer></script></head>
<body><header class="top"><nav aria-label="Main navigation"><a class="brand" href="/">Purchase Intake</a>
<a href="/import">Import</a><a href="/notifications">Notifications</a></nav></header>
<main>{notice}{content}</main></body></html>"""


def token_field(token):
    return f'<input type="hidden" name="token" value="{h(token)}">'


def detail_url(reference):
    return "/request?" + urlencode({"reference": reference})


def render_table(headers, rows, empty):
    if not rows:
        return f'<p class="empty">{h(empty)}</p>'
    heading = "".join(f'<th scope="col">{h(label)}</th>' for label in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{heading}</tr></thead><tbody>{body}</tbody></table></div>'


def dashboard(store, provider_name, status_filter):
    requests = store.requests()
    counts = Counter(row["status"] for row in requests)
    cards = "".join(
        f'<a class="stat" href="/?status={status}" aria-current="{"true" if status == status_filter else "false"}">'
        f'<span>{LABELS[status]}</span><strong>{counts[status]}</strong></a>' for status in STATUSES
    )
    rows = [
        (f'<a class="ref" href="{h(detail_url(row["reference"]))}">{h(row["reference"])}</a>',
         h(row["source"]["department"].title()), h(row["source"]["date"]),
         f'<span class="state {row["status"]}">{LABELS[row["status"]]}</span>',
         h(row["route"].title() if row["route"] else "—"))
        for row in requests if not status_filter or row["status"] == status_filter
    ]
    clear = '<a href="/">Clear filter</a>' if status_filter else ""
    table = render_table(("Reference", "Department", "Date", "Status", "Route"), rows, "No requests to show.")
    return f"""<section class="hero"><div><h1>Purchase requests</h1>
<p>Import requests, review exceptions, and export your approved register.</p></div>
<a class="button" href="/import">Import requests</a></section>
<div class="stats" aria-label="Filter by status">{cards}</div>
<section class="panel"><div class="section-head"><div><h2>Request queue</h2>
<p class="muted">Provider · {h(provider_name)}</p></div>
<div class="actions">{clear}<a href="/operations.csv">Operations CSV</a><a href="/register.csv">Register CSV</a></div></div>
{table}</section>"""


def imports(token, text="", preview=None, committed=False):
    if preview is None:
        report = ""
    else:
        rows = [(h(line), h(reference), h(status), h(message)) for line, reference, status, message in preview]
        report = ('<section class="panel"><h2>' + ("Import results" if committed else "Import preview") + "</h2>"
                  + render_table(("Row", "Reference", "Status", "Details"), rows, "No data rows found.") + "</section>")
    return f"""<section class="hero"><div><h1>Import requests</h1>
<p>Upload or paste a UTF-8 CSV. Preview cleaned records before saving.</p></div></section>
<section class="panel editor"><form method="post" action="/import">{token_field(token)}
<label for="file">CSV file</label><input id="file" type="file" accept=".csv,text/csv">
<label for="csv">CSV contents</label><textarea id="csv" name="csv" rows="8" required>{h(text)}</textarea>
<p class="muted">Required columns are reference, department, date, currency, amount, and notes.</p>
<div class="actions"><button class="secondary" name="action" value="preview">Preview</button>
<button name="action" value="save">Save to queue</button></div></form></section>{report}"""


def notification_page(store):
    rows = [
        (h(row["created_at"] + " UTC"),
         f'<a href="{h(detail_url(row["reference"]))}">{h(row["reference"])}</a>',
         h(row["kind"].replace("_", " ").title()), h(row["message"]))
        for row in store.events()
    ]
    return '<h1>Notifications</h1><section class="panel">' + render_table(
        ("Time", "Request", "Event", "Message"), rows, "No events yet.") + "</section>"


def source_amount(source):
    minor = source["amount_minor"]
    return f"{minor // 100:,} IDR" if source["currency"] == "IDR" else f"{minor / 100:,.2f} USD"


def detail(row, token):
    reference, status, source = row["reference"], row["status"], row["source"]
    revision = f'<input type="hidden" name="revision" value="{row["revision"]}">'
    hidden = f'{token_field(token)}{revision}<input type="hidden" name="reference" value="{h(reference)}">'
    proposal = row["result"] or {}
    facts = {
        "Department": source["department"].title(),
        "Date": source["date"],
        "Amount": source_amount(source),
        "Route": row["route"].title() if row["route"] else "—",
    }
    pairs = "".join(f"<div><dt>{label}</dt><dd>{h(value)}</dd></div>" for label, value in facts.items())
    issue = f'<p class="issue">{h(row["issue"].replace("_", " "))}</p>' if row["issue"] else ""
    can_process = status in {"queued", "error"}
    run = (f'<form method="post" action="/process">{hidden}<button>'
           f'{"Retry model" if status == "error" else "Process request"}</button></form>') if can_process else ""
    results = ""
    if status in {"review", "error"}:
        options = '<option value="">Select a category</option>' + "".join(
            f'<option value="{category}"{" selected" if proposal.get("category") == category else ""}>'
            f'{category.title()}</option>' for category in CATEGORIES
        )
        results = f"""<section class="panel editor"><h2>{h(row["route"].title())} review</h2>{issue}
<form method="post" action="/review">{hidden}
<label for="vendor">Vendor</label><input id="vendor" name="vendor" value="{h(proposal.get("vendor"))}" maxlength="80">
<label for="item">Item</label><input id="item" name="item" value="{h(proposal.get("item"))}" maxlength="80">
<label for="quantity">Quantity</label><input id="quantity" name="quantity" type="number" min="1" max="9999" value="{h(proposal.get("quantity"))}">
<label for="category">Category</label><select id="category" name="category">{options}</select>
<label for="summary">Source summary</label><textarea id="summary" name="summary" maxlength="180" rows="3">{h(proposal.get("summary"))}</textarea>
<p class="muted">Copy values from the request note before approving.</p>
<div class="actions"><button name="decision" value="approve">Approve and write</button>
<button class="secondary" name="decision" value="reject" formnovalidate>Reject request</button></div></form></section>"""
    elif proposal:
        fields = "".join(f"<div><dt>{name.title()}</dt><dd>{h(proposal.get(name))}</dd></div>" for name in FIELDS)
        results = f'<section class="panel"><h2>Approved record</h2><dl>{fields}</dl></section>'
    return f"""<a href="/">← Request queue</a><section class="hero"><div><h1>{h(reference)}</h1>
<span class="state {status}">{LABELS[status]}</span></div>{run}</section>
<div class="detail-grid"><section class="panel"><h2>Source</h2><dl>{pairs}</dl>
<h3>Request note</h3><p class="note">{h(source["notes"])}</p></section>{results}</div>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Keep submitted text and request parameters out of HTTP logs.
        return

    def send(self, status, body, media="text/html; charset=utf-8", filename=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; form-action 'self'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def error_page(self, status, message):
        self.send(status, page("Request error", '<p><a href="/">Open request queue</a></p>', message))

    def host_allowed(self):
        port = self.server.server_port
        expected = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            expected.update({"127.0.0.1", "localhost"})
        return self.headers.get("Host") in expected

    def do_GET(self):
        if not self.host_allowed():
            self.error_page(400, "Use the local app address.")
            return
        path = urlsplit(self.path)
        params = parse_qs(path.query)
        store, token = self.server.store, self.server.token
        message = params.get("message", [""])[0][:120]
        try:
            if path.path == "/":
                selected = params.get("status", [""])[0]
                self.send(200, page("Requests", dashboard(store, self.server.provider_name,
                                                          selected if selected in STATUSES else ""), message))
            elif path.path == "/import":
                self.send(200, page("Import", imports(token)))
            elif path.path == "/notifications":
                self.send(200, page("Notifications", notification_page(store)))
            elif path.path == "/request":
                reference = params.get("reference", [""])[0]
                self.send(200, page("Request detail", detail(store.get(reference), token), message))
            elif path.path == "/register.csv":
                self.send(200, export_register(store), "text/csv; charset=utf-8", "approved-register.csv")
            elif path.path == "/operations.csv":
                self.send(200, export_operations(store), "text/csv; charset=utf-8", "operations-report.csv")
            elif path.path == "/assets/style.css":
                self.send(200, (ASSETS / "style.css").read_bytes(), "text/css; charset=utf-8")
            elif path.path == "/assets/import.js":
                self.send(200, (ASSETS / "import.js").read_bytes(), "text/javascript; charset=utf-8")
            else:
                self.error_page(404, "Page unavailable.")
        except KeyError:
            self.error_page(404, "Request unavailable.")

    def read_form(self):
        if self.headers.get_content_type() != "application/x-www-form-urlencoded":
            raise ValueError("Expected a browser form.")
        size = int(self.headers.get("Content-Length", "0"))
        if not 1 <= size <= 3 * MAX_BYTES + 1024:
            raise ValueError("Form is empty or too large.")
        form = {key: values[0] for key, values in parse_qs(
            self.rfile.read(size).decode("utf-8"), keep_blank_values=True, max_num_fields=12
        ).items()}
        token = form.get("token", "")
        if not token.isascii() or not compare_digest(token, self.server.token):
            raise ValueError("Form expired. Reload and try again.")
        return form

    def do_POST(self):
        if not self.host_allowed():
            self.error_page(400, "Use the local app address.")
            return
        store = self.server.store
        try:
            form = self.read_form()
            if self.path == "/import":
                self.handle_import(form)
                return
            reference = form.get("reference", "")
            if self.path == "/process":
                run_request(store, reference, self.server.provider,
                            expected_revision=int(form.get("revision") or "-1"))
            elif self.path == "/review":
                changes = {field: form.get(field) or None for field in FIELDS}
                if form.get("decision") == "approve":
                    try:
                        changes["quantity"] = int(changes["quantity"] or "")
                    except ValueError:
                        raise ValueError("Enter a whole-number quantity.") from None
                review_request(store, reference, int(form.get("revision") or "-1"),
                               form.get("decision"), changes)
            else:
                self.error_page(404, "Page unavailable.")
                return
            self.send_response(303)
            self.send_header("Location", detail_url(reference))
            self.send_header("Content-Length", "0")
            self.end_headers()
        except KeyError:
            self.error_page(404, "Request unavailable.")
        except ValueError as error:
            reference = locals().get("reference")
            if reference and self.path in {"/review", "/process"}:
                try:
                    self.send(400, page("Request detail", detail(store.get(reference), self.server.token), str(error)))
                    return
                except KeyError:
                    pass
            self.error_page(400, str(error))

    def handle_import(self, form):
        raw = form.get("csv", "")
        try:
            entries = parse_csv(raw.encode())
        except ValueError as error:
            self.send(400, page("Import", imports(self.server.token, raw[:MAX_BYTES]), str(error)))
            return
        save = form.get("action") == "save"
        if save:
            rows = self.server.store.intake(entries)
        else:
            rows = [(line, row["reference"] if row else "", "ready" if row else "invalid",
                     error or f'{row["department"].title()} · {row["date"]} · {source_amount(row)}')
                    for line, row, error in entries]
        self.send(200, page("Import", imports(self.server.token, "" if save else raw, rows, save)))


class Server(ThreadingHTTPServer):
    def __init__(self, store, provider, port):
        super().__init__(("127.0.0.1", port), Handler)
        self.store = store
        self.provider = provider
        self.provider_name = "Rules baseline" if isinstance(provider, RulesProvider) else "Local model"
        self.token = token_urlsafe(32)


def serve(store, provider, port):
    with Server(store, provider, port) as server:
        print(f"Purchase Intake is listening at http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
