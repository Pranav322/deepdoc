from __future__ import annotations

from pathlib import Path

from deepdoc.parser.base import ParsedFile, Symbol
from deepdoc.parser import js_ts_parser
from deepdoc.parser.registry import parse_file
from deepdoc.scanner import (
    discover_config_impacts,
    discover_database_schema,
    discover_debug_signals,
    discover_runtime_surfaces,
)
from deepdoc.scanner.common import (
    DispatchEvidence,
    RuntimeScan,
    RuntimeScheduler,
    RuntimeTask,
)
from deepdoc.scanner.runtime import (
    _collect_dispatch_evidence,
    _discover_nestjs_runtime,
    _link_runtime_evidence,
)


def _parsed_file(
    path: str,
    *,
    language: str = "python",
    imports: list[str] | None = None,
    symbols: list[Symbol] | None = None,
) -> ParsedFile:
    return ParsedFile(
        path=Path(path),
        language=language,
        imports=imports or [],
        symbols=symbols or [],
    )


def test_runtime_and_database_discovery_extracts_runtime_graphql_and_knex_surfaces() -> (
    None
):
    parsed_files = {
        "orders/models.py": _parsed_file(
            "orders/models.py",
            imports=["import catalog.models"],
            symbols=[
                Symbol(
                    name="Order", kind="class", signature="class Order(models.Model):"
                ),
                Symbol(
                    name="OrderItem",
                    kind="class",
                    signature="class OrderItem(models.Model):",
                ),
            ],
        ),
        "catalog/models.py": _parsed_file(
            "catalog/models.py",
            symbols=[
                Symbol(
                    name="CatalogItem",
                    kind="class",
                    signature="class CatalogItem(models.Model):",
                )
            ],
        ),
        "orders/tasks.py": _parsed_file("orders/tasks.py"),
        "orders/scheduler.js": _parsed_file(
            "orders/scheduler.js", language="javascript"
        ),
        "realtime/consumers.py": _parsed_file("realtime/consumers.py"),
        "graphql/schema.py": _parsed_file("graphql/schema.py"),
        "db/orders.js": _parsed_file("db/orders.js", language="javascript"),
    }

    file_contents = {
        "orders/models.py": (
            "from django.db import models\n\n"
            "class Order(models.Model):\n"
            "    status = models.CharField(max_length=32)\n\n"
            "class OrderItem(models.Model):\n"
            "    order = models.ForeignKey('Order', on_delete=models.CASCADE)\n"
        ),
        "catalog/models.py": (
            "from django.db import models\n\n"
            "class CatalogItem(models.Model):\n"
            "    sku = models.CharField(max_length=32)\n"
        ),
        "orders/tasks.py": (
            "from celery import shared_task\n"
            "from celery.schedules import crontab\n\n"
            "@shared_task(queue='critical', autoretry_for=(Exception,), retry_backoff=True)\n"
            "def sync_orders(order_id):\n"
            "    return order_id\n\n"
            "def trigger_invoice(order_id):\n"
            "    send_invoice.delay(order_id)\n\n"
            "app.conf.beat_schedule = {\n"
            "    'nightly-sync': {\n"
            "        'task': 'orders.tasks.sync_orders',\n"
            "        'schedule': crontab(minute='0', hour='2'),\n"
            "    }\n"
            "}\n"
        ),
        "orders/scheduler.js": (
            "const cron = require('node-cron');\n"
            "cron.schedule('*/5 * * * *', () => syncInventory());\n"
        ),
        "realtime/consumers.py": (
            "from channels.auth import AuthMiddlewareStack\n"
            "from channels.generic.websocket import AsyncWebsocketConsumer\n"
            "from channels.routing import ProtocolTypeRouter, URLRouter\n"
            "from django.urls import re_path\n\n"
            "class OrdersConsumer(AsyncWebsocketConsumer):\n"
            "    async def connect(self):\n"
            "        await self.channel_layer.group_add('orders', self.channel_name)\n"
            "        self.scope['user']\n\n"
            "websocket_urlpatterns = [\n"
            "    re_path(r'ws/orders/$', OrdersConsumer.as_asgi()),\n"
            "]\n"
            "application = ProtocolTypeRouter({\n"
            "    'websocket': AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),\n"
            "})\n"
        ),
        "graphql/schema.py": (
            "import graphene\n\n"
            "class OrderType(graphene.ObjectType):\n"
            "    id = graphene.ID()\n"
            "    status = graphene.String()\n\n"
            "    def resolve_status(self, info):\n"
            "        return 'ready'\n\n"
            "class CreateOrder(graphene.Mutation):\n"
            "    ok = graphene.Boolean()\n\n"
            "    def mutate(self, info):\n"
            "        return CreateOrder(ok=True)\n\n"
            "schema = graphene.Schema(query=OrderType, mutation=CreateOrder)\n"
        ),
        "db/orders.js": (
            "exports.up = async function(knex) {\n"
            "  await knex.schema.createTable('orders', function(table) {\n"
            "    table.uuid('id');\n"
            "    table.string('status');\n"
            "    table.uuid('user_id').references('users.id');\n"
            "  });\n"
            "};\n\n"
            "async function loadOrders() {\n"
            "  return knex('orders').leftJoin('users', 'users.id', 'orders.user_id').where({status: 'ready'});\n"
            "}\n"
        ),
    }

    runtime = discover_runtime_surfaces(
        parsed_files,
        file_contents,
        api_endpoints=[
            {
                "method": "POST",
                "path": "/api/orders/sync",
                "file": "orders/tasks.py",
                "handler_file": "orders/tasks.py",
                "route_file": "orders/tasks.py",
            }
        ],
    )

    task_names = {task.name for task in runtime.tasks}
    scheduler_types = {scheduler.scheduler_type for scheduler in runtime.schedulers}
    assert "sync_orders" in task_names
    assert "send_invoice" not in task_names
    assert "beat" in scheduler_types
    assert "node_cron" in scheduler_types

    celery_task = next(task for task in runtime.tasks if task.name == "sync_orders")
    assert celery_task.queue == "critical"
    assert "autoretry_for" in celery_task.retry_policy
    # A call site is dispatch evidence, not an invented task definition.
    assert celery_task.producer_files == []

    beat_scheduler = next(
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "beat"
    )
    assert beat_scheduler.invoked_targets == ["orders.tasks.sync_orders"]

    consumer = runtime.realtime_consumers[0]
    assert consumer.name == "OrdersConsumer"
    assert "ws/orders/$" in consumer.routes
    assert "orders" in consumer.groups
    assert "AuthMiddlewareStack" in consumer.auth_hints

    db_scan = discover_database_schema(parsed_files, file_contents, {}, Path("."))

    assert db_scan.orm_framework == "django"
    assert "knex" in db_scan.orm_frameworks
    assert db_scan.total_models == 3
    assert any(group.key == "orders" for group in db_scan.groups)
    assert any(group.key == "catalog" for group in db_scan.groups)

    orders_group = next(group for group in db_scan.groups if group.key == "orders")
    assert orders_group.model_names == ["Order", "OrderItem"]
    assert orders_group.external_refs == ["catalog"]

    interface_names = {interface.name for interface in db_scan.graphql_interfaces}
    assert "OrderType" in interface_names
    assert "CreateOrder" in interface_names
    assert "schema" in interface_names

    schema_artifact = next(
        artifact
        for artifact in db_scan.knex_artifacts
        if artifact.artifact_type == "schema"
    )
    assert schema_artifact.table_name == "orders"
    assert "status" in schema_artifact.columns
    assert "users.id" in schema_artifact.foreign_keys

    query_artifact = next(
        artifact
        for artifact in db_scan.knex_artifacts
        if artifact.artifact_type == "query"
    )
    assert query_artifact.table_name == "orders"
    assert "leftJoin" in query_artifact.query_patterns[0]


def test_database_grouping_coalesces_sparse_singleton_models() -> None:
    parsed_files: dict[str, ParsedFile] = {}
    file_contents: dict[str, str] = {}

    for index in range(10):
        file_path = f"models/model_{index}.py"
        class_name = f"Model{index}"
        parsed_files[file_path] = _parsed_file(
            file_path,
            symbols=[
                Symbol(
                    name=class_name,
                    kind="class",
                    signature=f"class {class_name}(models.Model):",
                )
            ],
        )
        file_contents[file_path] = (
            "from django.db import models\n\n"
            f"class {class_name}(models.Model):\n"
            "    name = models.CharField(max_length=64)\n"
        )

    db_scan = discover_database_schema(parsed_files, file_contents, {}, Path("."))

    assert len(db_scan.groups) < 10
    core_group = next(group for group in db_scan.groups if group.key == "core-models")
    assert len(core_group.file_paths) == 10
    assert len(core_group.model_names) == 10


def test_discover_config_impacts_maps_keys_to_files_and_endpoints() -> None:
    file_contents = {
        "settings.py": "API_PREFIX = '/api/v2'\nPAYMENTS_HOST = os.getenv('PAYMENTS_HOST', 'https://pay.example')\n",
        "routes.py": "from django.conf import settings\nAPI_ROOT = settings.API_PREFIX\n",
        "payments/client.py": "url = os.getenv('PAYMENTS_HOST')\n",
    }
    api_endpoints = [
        {
            "method": "POST",
            "path": "/api/v2/payments",
            "file": "routes.py",
            "route_file": "routes.py",
            "handler_file": "payments/client.py",
        }
    ]

    impacts = discover_config_impacts(file_contents, api_endpoints)

    by_key = {(impact.key, impact.kind): impact for impact in impacts}
    assert ("PAYMENTS_HOST", "env_var") in by_key
    assert by_key[("PAYMENTS_HOST", "env_var")].default_value == "'https://pay.example'"
    assert by_key[("PAYMENTS_HOST", "env_var")].related_endpoints == [
        "POST /api/v2/payments"
    ]
    assert ("API_PREFIX", "setting") in by_key


def test_runtime_discovery_extracts_django_and_laravel_surfaces() -> None:
    parsed_files = {
        "orders/management/commands/sync_orders.py": _parsed_file(
            "orders/management/commands/sync_orders.py"
        ),
        "orders/signals.py": _parsed_file("orders/signals.py"),
        "app/Jobs/SyncOrders.php": _parsed_file(
            "app/Jobs/SyncOrders.php", language="php"
        ),
        "app/Listeners/SendShipmentWebhook.php": _parsed_file(
            "app/Listeners/SendShipmentWebhook.php", language="php"
        ),
        "app/Events/OrderShipped.php": _parsed_file(
            "app/Events/OrderShipped.php", language="php"
        ),
        "app/Console/Kernel.php": _parsed_file(
            "app/Console/Kernel.php", language="php"
        ),
    }
    file_contents = {
        "orders/management/commands/sync_orders.py": (
            "from django.core.management.base import BaseCommand\n\n"
            "class Command(BaseCommand):\n"
            "    help = 'Sync orders'\n\n"
            "    def handle(self, *args, **options):\n"
            "        return None\n"
        ),
        "orders/signals.py": (
            "from django.dispatch import receiver\n"
            "from django.db.models.signals import post_save\n\n"
            "@receiver(post_save, sender=Order)\n"
            "def publish_order_update(sender, instance, **kwargs):\n"
            "    return None\n"
        ),
        "app/Jobs/SyncOrders.php": (
            "<?php\n"
            "use Illuminate\\Contracts\\Queue\\ShouldQueue;\n"
            "class SyncOrders implements ShouldQueue\n"
            "{\n"
            "    public $queue = 'critical';\n"
            "}\n"
        ),
        "app/Listeners/SendShipmentWebhook.php": (
            "<?php\n"
            "use Illuminate\\Contracts\\Queue\\ShouldQueue;\n"
            "class SendShipmentWebhook implements ShouldQueue\n"
            "{\n"
            "    public function handle(OrderShipped $event) {}\n"
            "}\n"
        ),
        "app/Events/OrderShipped.php": ("<?php\nclass OrderShipped\n{\n}\n"),
        "app/Console/Kernel.php": (
            "<?php\n"
            "$schedule->command('orders:sync')->dailyAt('02:00');\n"
            "$schedule->job(new SyncOrders)->everyFiveMinutes();\n"
        ),
    }

    runtime = discover_runtime_surfaces(parsed_files, file_contents)

    by_name = {task.name: task for task in runtime.tasks}
    assert by_name["sync-orders"].runtime_kind == "django_command"
    assert by_name["sync-orders"].triggers == ["manage.py"]
    assert by_name["publish_order_update"].runtime_kind == "django_signal"
    assert by_name["publish_order_update"].triggers == ["post_save"]
    assert by_name["SyncOrders"].runtime_kind == "laravel_job"
    assert by_name["SyncOrders"].queue == "critical"
    assert by_name["SendShipmentWebhook"].runtime_kind == "laravel_listener"
    assert by_name["SendShipmentWebhook"].triggers == ["OrderShipped"]
    assert by_name["OrderShipped"].runtime_kind == "laravel_event"

    laravel_schedulers = [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "laravel_schedule"
    ]
    assert len(laravel_schedulers) == 2
    assert any(
        scheduler.invoked_targets == ["orders:sync"] for scheduler in laravel_schedulers
    )
    assert any(
        scheduler.invoked_targets == ["SyncOrders"] for scheduler in laravel_schedulers
    )


def test_runtime_discovery_extracts_js_and_go_workers() -> None:
    parsed_files = {
        "workers/orders.js": _parsed_file("workers/orders.js", language="javascript"),
        "cmd/worker/main.go": _parsed_file("cmd/worker/main.go", language="go"),
    }
    file_contents = {
        "workers/orders.js": (
            "const { Worker, Queue } = require('bullmq');\n"
            "const Agenda = require('agenda');\n"
            "const agenda = new Agenda();\n"
            "const queue = new Queue('inventory');\n"
            "queue.add('inventory-refresh', {});\n"
            "new Worker('orders-sync', async job => syncOrders(job));\n"
            "new Worker('inventory-refresh', async () => refreshInventory());\n"
            "agenda.define('nightly-report', async () => {});\n"
            "agenda.every('5 minutes', 'nightly-report');\n"
        ),
        "cmd/worker/main.go": (
            'package main\n\nimport "time"\n\n'
            "func syncLoop() {}\nfunc cleanup() {}\n\n"
            "func main() {\n"
            "    go syncLoop()\n"
            '    c.AddFunc("@every 5m", cleanup)\n'
            "    scheduler.Every(10 * time.Minute).Do(syncLoop)\n"
            "}\n"
        ),
    }

    runtime = discover_runtime_surfaces(parsed_files, file_contents)

    js_workers = {
        task.name: task for task in runtime.tasks if task.runtime_kind == "js_worker"
    }
    assert "orders-sync" in js_workers
    assert js_workers["orders-sync"].queue == "orders-sync"
    assert "inventory-refresh" in js_workers
    assert "nightly-report" in js_workers

    go_workers = {
        task.name: task for task in runtime.tasks if task.runtime_kind == "go_worker"
    }
    assert "syncLoop" in go_workers
    assert "cleanup" in go_workers
    assert "@every 5m" in go_workers["cleanup"].schedule_sources

    scheduler_types = {scheduler.scheduler_type for scheduler in runtime.schedulers}
    assert "agenda" in scheduler_types
    assert "go_cron" in scheduler_types
    assert "go_schedule" in scheduler_types


def test_generic_js_process_and_consume_are_not_queue_workers() -> None:
    """`.process(`/`.consume(` are ordinary method names without a queue import."""
    parsed_files = {
        "src/vs/base/browser/ui/tree/compressedObjectTreeModel.ts": _parsed_file(
            "src/vs/base/browser/ui/tree/compressedObjectTreeModel.ts",
            language="typescript",
        ),
    }
    file_contents = {
        "src/vs/base/browser/ui/tree/compressedObjectTreeModel.ts": (
            "import { Iterable } from '../../../common/iterator.js';\n"
            "export function build(nodes, lineProcessor, replyProcessor) {\n"
            "    Iterable.consume(nodes, 1);\n"
            "    lineProcessor.process(line, context);\n"
            "    return replyProcessor.process(reply);\n"
            "}\n"
        ),
    }

    runtime = discover_runtime_surfaces(parsed_files, file_contents)

    assert [task for task in runtime.tasks if task.runtime_kind == "js_worker"] == []

    # Same `.consume(` shape, but the file really is a broker consumer.
    parsed_files["src/jobs/orderConsumer.ts"] = _parsed_file(
        "src/jobs/orderConsumer.ts", language="typescript"
    )
    file_contents["src/jobs/orderConsumer.ts"] = (
        "import amqplib from 'amqplib';\n"
        "const channel = await (await amqplib.connect(url)).createChannel();\n"
        "channel.consume('orders-sync', handleOrder);\n"
    )

    runtime = discover_runtime_surfaces(parsed_files, file_contents)

    assert [
        task.name for task in runtime.tasks if task.runtime_kind == "js_worker"
    ] == ["orders-sync"]


def test_generic_js_new_worker_is_not_a_queue_worker() -> None:
    """A browser/Node `new Worker(...)` is not a queue job without a queue import."""
    parsed_files = {
        "src/vs/editor/common/services/editorWorkerService.ts": _parsed_file(
            "src/vs/editor/common/services/editorWorkerService.ts",
            language="typescript",
        ),
    }
    file_contents = {
        "src/vs/editor/common/services/editorWorkerService.ts": (
            "import { URI } from '../../../base/common/uri.js';\n"
            "const worker = new Worker('vs/editor/common/services/editorSimpleWorker');\n"
            "worker.postMessage({ type: 'init' });\n"
        ),
    }

    runtime = discover_runtime_surfaces(parsed_files, file_contents)

    assert [task for task in runtime.tasks if task.runtime_kind == "js_worker"] == []


def test_agenda_jobs_need_agenda_evidence() -> None:
    """`agenda.define(...)` only counts when the file really uses Agenda."""
    coincidence = {
        "src/vs/workbench/contrib/notes/browser/agendaView.ts": (
            "const agenda = this.buildAgenda();\n"
            "agenda.define('nightly-report', view => view.render());\n"
            "agenda.every('5 minutes', 'nightly-report');\n"
        ),
    }
    real = {
        "src/jobs/reports.ts": (
            "import Agenda from 'agenda';\n"
            "const agenda = new Agenda({ db: { address: process.env.MONGO_URL } });\n"
            "agenda.define('nightly-report', async () => {});\n"
            "agenda.every('5 minutes', 'nightly-report');\n"
        ),
    }
    parsed = {
        path: _parsed_file(path, language="typescript")
        for path in (*coincidence, *real)
    }

    noise = discover_runtime_surfaces(parsed, coincidence)
    assert [task for task in noise.tasks if task.runtime_kind == "js_worker"] == []
    assert [s for s in noise.schedulers if s.scheduler_type == "agenda"] == []

    detected = discover_runtime_surfaces(parsed, real)
    assert [task.name for task in detected.tasks if task.runtime_kind == "js_worker"] == [
        "nightly-report"
    ]
    assert [s.scheduler_type for s in detected.schedulers] == ["agenda"]


def test_unbound_queue_receivers_are_not_queue_jobs() -> None:
    """A real queue import does not make every same-file call a queue job."""
    path = "src/media/codec.ts"
    content = (
        'import { Queue } from "bullmq";\n'
        'const realQueue = new Queue("real");\n'
        "const codec = { process(_name: string) {} };\n"
        'codec.process("not-a-queue-job");\n'
        'const webWorker = new Worker("browser-worker");\n'
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: content})

    assert [task for task in runtime.tasks if task.runtime_kind == "js_worker"] == []


def test_bullmq_worker_alias_binds_but_a_shadowed_worker_does_not() -> None:
    """The bound alias is the queue job; a nested rebinding of it is not."""
    path = "src/jobs/orders.ts"
    content = (
        'import { Worker as BullWorker } from "bullmq";\n'
        'new BullWorker("orders", handler);\n'
        "export function spawn(BullWorker: typeof globalThis.Worker) {\n"
        '    return new BullWorker("browser-worker");\n'
        "}\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: content})

    assert [
        task.name for task in runtime.tasks if task.runtime_kind == "js_worker"
    ] == ["orders"]


def test_queue_and_agenda_instances_bind_by_symbol_not_by_variable_name() -> None:
    """Binding follows the constructor, so the variable may be named anything."""
    files = {
        "src/jobs/emails.ts": (
            'import Bull from "bull";\n'
            'const mailer = new Bull("emails");\n'
            'mailer.process("send-digest", handleDigest);\n'
        ),
        "src/jobs/reports.ts": (
            'import Agenda from "agenda";\n'
            "const jobs = new Agenda({ db: { address: url } });\n"
            "jobs.define('nightly-report', async () => {});\n"
            "jobs.every('5 minutes', 'nightly-report');\n"
        ),
    }
    parsed = {path: _parsed_file(path, language="typescript") for path in files}

    runtime = discover_runtime_surfaces(parsed, files)

    assert sorted(
        task.name for task in runtime.tasks if task.runtime_kind == "js_worker"
    ) == ["nightly-report", "send-digest"]
    assert [s.scheduler_type for s in runtime.schedulers] == ["agenda"]


def test_agenda_constructor_without_an_agenda_import_is_not_a_job() -> None:
    """`new Agenda()` only binds when the constructor came from the library."""
    path = "src/ui/calendar/agendaView.ts"
    content = (
        "import { View } from './view.js';\n"
        "const agenda = new Agenda();\n"
        "agenda.define('nightly-report', view => view.render());\n"
        "agenda.every('5 minutes', 'nightly-report');\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: content})

    assert [task for task in runtime.tasks if task.runtime_kind == "js_worker"] == []
    assert [s for s in runtime.schedulers if s.scheduler_type == "agenda"] == []


def test_deferred_assignment_binds_only_the_real_broker_channel() -> None:
    """`let channel; channel = await ...` is a flow real broker clients use."""
    path = "src/jobs/orderChannel.ts"
    content = (
        'import amqplib from "amqplib";\n'
        "let channel;\n"
        "export async function boot() {\n"
        "    channel = await (await amqplib.connect(url)).createChannel();\n"
        "}\n"
        'channel.consume("orders-sync", handleOrder);\n'
        "export function drain(channel: LocalChannel) {\n"
        '    channel.consume("not-a-broker-queue", noop);\n'
        "}\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: content})

    assert [
        task.name for task in runtime.tasks if task.runtime_kind == "js_worker"
    ] == ["orders-sync"]


def test_template_literal_prompt_examples_are_not_queue_workers() -> None:
    """Queue code quoted inside a prompt template literal never executes."""
    path = "src/prompts/worker_examples.ts"
    content = (
        "export const WORKER_PROMPT = `\n"
        '  import { Worker } from "bullmq";\n'
        '  new Worker("fake-example", async job => job);\n'
        '  queue.process("also-fake", handler);\n'
        "`;\n"
        "export function buildPrompt(): string {\n"
        "    return WORKER_PROMPT;\n"
        "}\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None and parsed.language == "typescript"

    runtime = discover_runtime_surfaces({path: parsed}, {path: content})

    assert [task for task in runtime.tasks if task.runtime_kind == "js_worker"] == []


def test_real_queue_import_with_embedded_example_emits_no_fake_workers() -> None:
    """A genuine bullmq import does not make quoted example calls real jobs."""
    path = "src/prompts/queue_examples.ts"
    content = (
        'import { Queue } from "bullmq";\n'
        'const realQueue = new Queue("real");\n'
        "export const EXAMPLE = `\n"
        '  new Worker("fake-example", async job => job);\n'
        '  queue.process("also-fake", handler);\n'
        "`;\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: content})

    assert [task for task in runtime.tasks if task.runtime_kind == "js_worker"] == []


def test_vue_queue_workers_come_from_the_script_block() -> None:
    """A Vue SFC is markup around a script block; only the script is real JS."""
    path = "src/components/JobsPanel.vue"
    content = (
        "<template><div>{{ label }}</div></template>\n"
        '<script setup lang="ts">\n'
        'import { Worker } from "bullmq";\n'
        'new Worker("send-digest", handleDigest);\n'
        "</script>\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None and parsed.language == "vue"

    runtime = discover_runtime_surfaces({path: parsed}, {path: content})

    assert [
        task.name for task in runtime.tasks if task.runtime_kind == "js_worker"
    ] == ["send-digest"]


def _js_worker_names(path: str, content: str) -> list[str]:
    parsed = parse_file(Path(path), content)
    assert parsed is not None
    runtime = discover_runtime_surfaces({path: parsed}, {path: content})
    return [task.name for task in runtime.tasks if task.runtime_kind == "js_worker"]


def test_bullmq_queue_is_producer_only_and_never_a_consumer() -> None:
    """BullMQ splits producer from consumer: only `Worker` consumes."""
    assert (
        _js_worker_names(
            "src/jobs/emails.ts",
            'import { Queue } from "bullmq";\n'
            'new Queue("emails").process("send-digest", handleDigest);\n'
            'const queue = new Queue("reports");\n'
            'queue.process("nightly-report", buildReport);\n'
            "queue.add('send-digest', {});\n",
        )
        == []
    )
    # The same file's `Worker` is the real consumer role.
    assert _js_worker_names(
        "src/jobs/both.ts",
        'import { Queue, Worker } from "bullmq";\n'
        'const queue = new Queue("emails");\n'
        'queue.process("not-a-job", handleDigest);\n'
        'new Worker("send-digest", handleDigest);\n',
    ) == ["send-digest"]


def test_amqp_consume_needs_the_connect_create_channel_role() -> None:
    """Only a channel consumes; other amqplib-derived values do not."""
    assert (
        _js_worker_names(
            "src/jobs/orders.ts",
            'import amqplib from "amqplib";\n'
            'amqplib.createCodec().consume("orders-sync", handleOrder);\n'
            "const connection = await amqplib.connect(url);\n"
            'connection.consume("orders-direct", handleOrder);\n',
        )
        == []
    )
    assert _js_worker_names(
        "src/jobs/channel.ts",
        'import * as amqp from "amqplib";\n'
        "const connection = await amqp.connect(url);\n"
        "const channel = await connection.createChannel();\n"
        'channel.consume("orders-sync", handleOrder);\n',
    ) == ["orders-sync"]


def test_agenda_jobs_need_the_agenda_constructor_role() -> None:
    """Any other `agenda` export is not a job scheduler instance."""
    assert (
        _js_worker_names(
            "src/jobs/plainJob.ts",
            'import { Job } from "agenda";\n'
            "const job = new Job({});\n"
            "job.define('nightly-report', buildReport);\n",
        )
        == []
    )
    path = "src/jobs/reports.ts"
    content = (
        'import { Agenda } from "@hokify/agenda";\n'
        "const jobs = new Agenda({ db: { address: url } });\n"
        "jobs.define('nightly-report', buildReport);\n"
        "jobs.every('5 minutes', 'nightly-report');\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None
    runtime = discover_runtime_surfaces({path: parsed}, {path: content})
    assert [t.name for t in runtime.tasks if t.runtime_kind == "js_worker"] == [
        "nightly-report"
    ]
    assert [s.scheduler_type for s in runtime.schedulers] == ["agenda"]


def test_bull_legacy_queue_process_is_a_consumer() -> None:
    """Bull v3 has one class: the instance both produces and consumes."""
    assert _js_worker_names(
        "src/jobs/legacy.js",
        "const Bull = require('bull');\n"
        "const emails = new Bull('emails');\n"
        "emails.process('send-digest', handleDigest);\n",
    ) == ["send-digest"]


def test_queue_roles_follow_aliases_but_not_unrelated_receivers() -> None:
    """The role travels with the bound symbol, whatever it is renamed to."""
    assert _js_worker_names(
        "src/jobs/aliased.ts",
        'import * as bullmq from "bullmq";\n'
        'const { Worker: QueueWorker } = require("bullmq");\n'
        'new bullmq.Worker("orders-sync", handleOrder);\n'
        'new QueueWorker("orders-retry", handleRetry);\n'
        'new bullmq.Queue("emails").process("not-a-job", handleDigest);\n',
    ) == ["orders-sync", "orders-retry"]


def test_unmodelled_queue_apis_fail_closed() -> None:
    """A real library value with an unmapped API shape makes no claim."""
    assert (
        _js_worker_names(
            "src/jobs/unmapped.ts",
            'import { Worker, Queue } from "bullmq";\n'
            'const worker = new Worker("orders-sync", handleOrder);\n'
            'worker.getQueue().process("derived-job", handleOrder);\n'
            'Queue.prototype.process.call(queue, "reflected-job", handleOrder);\n',
        )
        == ["orders-sync"]
    )


def test_js_runtime_fails_closed_without_tree_sitter(monkeypatch) -> None:
    """No syntax nodes means no evidence - never fall back to raw text."""
    monkeypatch.setattr(js_ts_parser, "_TS_AVAILABLE", False)
    path = "workers/orders.js"
    content = (
        "const { Worker } = require('bullmq');\n"
        "new Worker('orders-sync', async job => syncOrders(job));\n"
    )

    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="javascript")}, {path: content}
    )

    assert [task for task in runtime.tasks if task.runtime_kind == "js_worker"] == []


def test_discover_debug_signals_reads_dict_endpoints() -> None:
    signals = discover_debug_signals(
        {},
        {},
        api_endpoints=[
            {
                "path": "/health",
                "handler_file": "src/health.py",
                "file": "src/health.py",
            },
            {
                "path": "/ready",
                "handler_file": "src/readiness.py",
                "file": "src/readiness.py",
            },
        ],
    )

    health = next(
        signal for signal in signals if signal.signal_type == "health_endpoint"
    )
    assert health.file_path == "src/health.py"
    assert "/health" in health.patterns
    assert "src/readiness.py" in health.files


def test_low_trust_fixtures_do_not_create_product_runtime_surfaces() -> None:
    """DD-002: fixture/example/test source must not become product runtime facts."""
    paths = {
        "worker/tasks.py": "python",
        "tests/fixtures/celery_fixture.py": "python",
        "examples/demo_worker.py": "python",
        "app/Jobs/RealJob.php": "php",
        "tests/fixtures/Jobs/FixtureJob.php": "php",
    }
    parsed_files = {
        path: _parsed_file(path, language=language) for path, language in paths.items()
    }
    file_contents = {
        "worker/tasks.py": (
            "from celery import shared_task\n\n"
            "@shared_task(queue='critical')\n"
            "def sync_orders(order_id):\n"
            "    return order_id\n"
        ),
        "tests/fixtures/celery_fixture.py": (
            "from celery import shared_task\n\n"
            "@shared_task(queue='fixture')\n"
            "def fixture_job(x):\n"
            "    return x\n\n"
            "def call_it():\n"
            "    fixture_job.delay(1)\n"
        ),
        "examples/demo_worker.py": (
            "from celery import shared_task\n\n"
            "@shared_task\n"
            "def demo_job(x):\n"
            "    return x\n"
        ),
        "app/Jobs/RealJob.php": (
            "<?php\n"
            "use Illuminate\\Contracts\\Queue\\ShouldQueue;\n"
            "class RealJob implements ShouldQueue\n{\n}\n"
        ),
        "tests/fixtures/Jobs/FixtureJob.php": (
            "<?php\n"
            "use Illuminate\\Contracts\\Queue\\ShouldQueue;\n"
            "class FixtureJob implements ShouldQueue\n{\n}\n"
        ),
    }

    runtime = discover_runtime_surfaces(parsed_files, file_contents)

    task_names = {task.name for task in runtime.tasks}
    assert "sync_orders" in task_names
    assert "RealJob" in task_names
    assert "fixture_job" not in task_names
    assert "demo_job" not in task_names
    assert "FixtureJob" not in task_names
    assert all(
        "fixtures/" not in task.file_path and "examples/" not in task.file_path
        for task in runtime.tasks
    )
    assert all(
        "fixtures/" not in producer
        for task in runtime.tasks
        for producer in task.producer_files
    )


def test_embedded_foreign_language_snippets_do_not_trigger_foreign_detectors() -> None:
    """DD-002: a product TypeScript prompt containing Python is not a Python runtime."""
    parsed_files = {
        "src/chat/prompts.ts": _parsed_file(
            "src/chat/prompts.ts", language="typescript"
        ),
        "src/editor/widget.ts": _parsed_file(
            "src/editor/widget.ts", language="typescript"
        ),
        "worker/tasks.py": _parsed_file("worker/tasks.py", language="python"),
    }
    file_contents = {
        # Product source, but the runtime-looking code is Python inside a TS string.
        "src/chat/prompts.ts": (
            "export const CELERY_PROMPT = `\n"
            "from celery import shared_task\n"
            "@shared_task(queue='prompt')\n"
            "def prompt_job(x):\n"
            "    return x\n"
            "prompt_job.delay(1)\n"
            "from django.core.management.base import BaseCommand\n"
            "class Command(BaseCommand):\n"
            "    pass\n"
            "post_save.connect(prompt_handler)\n"
            "`;\n"
        ),
        # Ordinary TypeScript idioms that merely look like Celery/Django dispatch.
        "src/editor/widget.ts": (
            "import { delay } from 'rxjs/operators';\n"
            "export class Widget {\n"
            "  start() {\n"
            "    this.onDidChange.connect(this._onChange);\n"
            "    this._obs.pipe(delay(300)).subscribe();\n"
            "    this.animation.delay(120);\n"
            "  }\n"
            "}\n"
        ),
        "worker/tasks.py": (
            "from celery import shared_task\n\n"
            "@shared_task(queue='critical')\n"
            "def sync_orders(order_id):\n"
            "    return order_id\n"
        ),
    }

    runtime = discover_runtime_surfaces(parsed_files, file_contents)

    assert {task.name for task in runtime.tasks} == {"sync_orders"}
    assert all(
        not task.file_path.endswith(".ts") for task in runtime.tasks
    ), [task.file_path for task in runtime.tasks]


def test_workflow_linking_is_bounded_to_dispatch_candidates() -> None:
    """DD-001: low-trust and non-dispatching files must not enter the link sweep.

    Deterministic synthetic corpus shaped like the VS Code hotspot: many product
    files that merely *mention* a task name, plus many low-trust fixtures that
    do contain real dispatch syntax. Only genuine product dispatch sites may be
    linked, and only they may cost link work.
    """
    corpus_size = 400
    parsed_files = {
        "worker/tasks.py": _parsed_file("worker/tasks.py", language="python"),
        "worker/api.py": _parsed_file("worker/api.py", language="python"),
    }
    file_contents = {
        "worker/tasks.py": (
            "from celery import shared_task\n\n"
            "@shared_task(queue='critical')\n"
            "def sync_orders(order_id):\n"
            "    return order_id\n"
        ),
        # The only real product dispatch site.
        "worker/api.py": (
            "from .tasks import sync_orders\n\n"
            "def enqueue(order_id):\n"
            "    sync_orders.delay(order_id)\n"
        ),
    }

    for index in range(corpus_size):
        # Product source that mentions the task name but never dispatches it.
        mention = f"src/vs/editor/mod{index}.ts"
        parsed_files[mention] = _parsed_file(mention, language="typescript")
        file_contents[mention] = (
            f"// see worker/tasks.py sync_orders for the ordering contract\n"
            f"export const LABEL_{index} = 'sync_orders';\n"
            + "// padding\n" * 200
        )
        # Low-trust fixture that *does* contain dispatch syntax.
        fixture = f"src/vs/workbench/test/fixtures/prompt{index}.ts"
        parsed_files[fixture] = _parsed_file(fixture, language="typescript")
        file_contents[fixture] = (
            "export const PROMPT = `\nsync_orders.delay(1)\n`;\n" + "// padding\n" * 200
        )

    runtime = discover_runtime_surfaces(parsed_files, file_contents)

    stats = runtime.scan_stats
    assert stats["input_files"] == corpus_size * 2 + 2
    assert stats["low_trust_files_skipped"] == corpus_size
    assert stats["eligible_files"] == corpus_size + 2
    # Only the genuine dispatch site may reach the task x regex sweep.
    assert stats["link_candidate_files"] == 1
    assert stats["link_candidate_files"] < stats["eligible_files"] / 100

    sync_orders = next(task for task in runtime.tasks if task.name == "sync_orders")
    assert sync_orders.producer_files == ["worker/api.py"]


def test_unpublished_endpoints_never_link_to_runtime_surfaces() -> None:
    """DD-002: a route the scan refused to publish is not runtime evidence.

    `publication_ready=False` marks a route the endpoint pass decided is not a
    real published surface (test-only, phantom, import-string artefact). Linking
    it to a task or scheduler smuggles it back into generated runtime evidence,
    so the runtime boundary must fail closed even when a caller hands over the
    raw `api_endpoints` list instead of `RepoScan.published_api_endpoints`.
    """
    path = "orders/tasks.py"
    parsed_files = {path: _parsed_file(path)}
    file_contents = {
        path: (
            "from celery import shared_task\n"
            "from celery.schedules import crontab\n\n"
            "@shared_task(queue='critical')\n"
            "def sync_orders(order_id):\n"
            "    return order_id\n\n"
            "@shared_task\n"
            "def send_invoice(order_id):\n"
            "    return order_id\n\n"
            "def trigger_invoice(order_id):\n"
            "    send_invoice.delay(order_id)\n\n"
            "app.conf.beat_schedule = {\n"
            "    'nightly-sync': {\n"
            "        'task': 'orders.tasks.sync_orders',\n"
            "        'schedule': crontab(minute='0', hour='2'),\n"
            "    }\n"
            "}\n"
        )
    }

    def _endpoint(method: str, route: str, published: bool) -> dict[str, object]:
        return {
            "method": method,
            "path": route,
            "file": path,
            "handler_file": path,
            "route_file": path,
            "publication_ready": published,
        }

    runtime = discover_runtime_surfaces(
        parsed_files,
        file_contents,
        api_endpoints=[
            _endpoint("GET", "/test-only", False),
            _endpoint("POST", "/api/orders/sync", True),
        ],
    )

    triggered = next(task for task in runtime.tasks if task.name == "send_invoice")
    assert triggered.linked_endpoints == ["POST /api/orders/sync"]
    beat = next(
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "beat"
    )
    assert beat.linked_endpoints == ["POST /api/orders/sync"]
    assert all(
        "GET /test-only" not in surface.linked_endpoints
        for surface in (*runtime.tasks, *runtime.schedulers)
    )


class _ProbeCountingStr(str):
    """A file body that counts substring probes made against it.

    `token in content` is exactly the per-task work the DD-001 hotspot did for
    every marker-bearing file, so counting it measures link work directly
    instead of timing it.
    """

    probes = 0

    def __contains__(self, other: object) -> bool:
        _ProbeCountingStr.probes += 1
        return str.__contains__(self, other)


def _marker_heavy_corpus(
    task_count: int, marker_files: int
) -> tuple[dict[str, ParsedFile], dict[str, str]]:
    """Many product files with unrelated `.delay(` calls, plus many real tasks."""
    body = "from celery import shared_task\n\n"
    for index in range(task_count):
        body += f"@shared_task(queue='q{index}')\ndef task_{index}(x):\n    return x\n\n"
    parsed_files = {"worker/tasks.py": _parsed_file("worker/tasks.py")}
    file_contents: dict[str, str] = {
        "worker/tasks.py": _ProbeCountingStr(body),
        # The one genuine product dispatch site.
        "worker/api.py": _ProbeCountingStr(
            "from .tasks import task_7\n\ndef enqueue(x):\n    task_7.delay(x)\n"
        ),
    }
    parsed_files["worker/api.py"] = _parsed_file("worker/api.py")
    for index in range(marker_files):
        path = f"src/vs/editor/animation{index}.ts"
        parsed_files[path] = _parsed_file(path, language="typescript")
        file_contents[path] = _ProbeCountingStr(
            "import { timeout } from './async';\n"
            f"export function run{index}() {{ this.anim.delay(120); }}\n"
            + "// padding\n" * 50
        )
    return parsed_files, file_contents


def test_task_link_work_is_bounded_by_extracted_dispatch_targets() -> None:
    """DD-001: unrelated dispatch markers must not cost one probe per task.

    The VS Code hotspot is a repo with hundreds of runtime tasks and hundreds of
    product files whose `.delay(` calls belong to something else entirely. Link
    work there must follow the dispatch targets a file actually names, so
    doubling the task count must not double the work.
    """
    marker_files = 257

    measurements = {}
    for task_count in (251, 502):
        _ProbeCountingStr.probes = 0
        parsed_files, file_contents = _marker_heavy_corpus(task_count, marker_files)
        runtime = discover_runtime_surfaces(parsed_files, file_contents)
        measurements[task_count] = (_ProbeCountingStr.probes, runtime)

    probes_small, runtime_small = measurements[251]
    probes_large, _ = measurements[502]

    # Doubling the task count must not scale the per-file probing with it.
    assert probes_large < probes_small * 1.2, (probes_small, probes_large)

    stats = runtime_small.scan_stats
    # Unbound TypeScript `.delay` calls are not dispatch evidence at all.
    assert stats["link_candidate_files"] == 1
    # Only `worker/api.py` names a target that resolves to a task, and it
    # resolves to exactly the `task_7` records - never to all 251 tasks.
    assert stats["link_task_checks"] <= 4, stats
    linked = [task for task in runtime_small.tasks if task.producer_files]
    assert {task.name for task in linked} == {"task_7"}
    assert all(task.producer_files == ["worker/api.py"] for task in linked)


def test_every_task_link_grammar_binds_its_producer_file() -> None:
    """The indexed lookup must keep every dispatch shape and its file order."""
    languages = {
        "orders/tasks.py": "python",
        "orders/signals.py": "python",
        "app/Jobs/SyncOrders.php": "php",
        "app/Events/OrderShipped.php": "php",
        "workers/orders.js": "javascript",
        "orders/api.py": "python",
        "orders/batch.py": "python",
        "orders/emit.py": "python",
        "app/Http/OrderController.php": "php",
        "src/producer.js": "javascript",
    }
    parsed_files = {
        path: _parsed_file(path, language=language)
        for path, language in languages.items()
    }
    file_contents = {
        "orders/tasks.py": (
            "from celery import shared_task\n\n"
            "@shared_task(queue='critical')\n"
            "def sync_orders(order_id):\n"
            "    return order_id\n"
        ),
        "orders/signals.py": (
            "from django.dispatch import receiver\n"
            "from django.db.models.signals import post_save\n\n"
            "@receiver(post_save)\n"
            "def audit_order(sender, **kwargs):\n"
            "    return None\n"
        ),
        "app/Jobs/SyncOrders.php": (
            "<?php\n"
            "use Illuminate\\Contracts\\Queue\\ShouldQueue;\n"
            "class SyncOrders implements ShouldQueue\n{\n}\n"
        ),
        "app/Events/OrderShipped.php": "<?php\nclass OrderShipped\n{\n}\n",
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders-sync', async job => syncOrders(job));\n"
        ),
        # Producers, one per dispatch shape.
        "orders/api.py": (
            "from .tasks import sync_orders\n\n"
            "def enqueue(order_id):\n"
            "    sync_orders.delay(order_id)\n"
        ),
        "orders/batch.py": (
            "from .tasks import sync_orders\n\n"
            "def enqueue_batch(order_id):\n"
            "    sync_orders.apply_async(args=[order_id])\n"
        ),
        "orders/emit.py": (
            "from django.db.models.signals import post_save\n\n"
            "def emit(order):\n"
            "    post_save.send(sender=type(order), instance=order)\n"
        ),
        "app/Http/OrderController.php": (
            "<?php\n"
            "class OrderController\n{\n"
            "    public function store($order)\n    {\n"
            "        SyncOrders::dispatch($order);\n"
            "        dispatch(SyncOrders::class);\n"
            "        dispatch(new SyncOrders($order));\n"
            "        event(new OrderShipped($order));\n"
            "    }\n}\n"
        ),
        "src/producer.js": (
            "const Queue = require('bullmq').Queue;\n"
            "const queue = new Queue('orders-sync');\n"
            "queue.add('orders-sync', {});\n"
        ),
    }

    runtime = discover_runtime_surfaces(parsed_files, file_contents)
    producers = {
        (task.name, task.file_path): task.producer_files for task in runtime.tasks
    }

    assert producers[("sync_orders", "orders/tasks.py")] == [
        "orders/api.py",
        "orders/batch.py",
    ]
    assert producers[("audit_order", "orders/signals.py")] == ["orders/emit.py"]
    assert producers[("SyncOrders", "app/Jobs/SyncOrders.php")] == [
        "app/Http/OrderController.php"
    ]
    assert producers[("OrderShipped", "app/Events/OrderShipped.php")] == [
        "app/Http/OrderController.php"
    ]
    assert producers[("orders-sync", "workers/orders.js")] == ["src/producer.js"]


def test_dispatch_index_does_not_collide_shared_word_runs() -> None:
    """Distinct names sharing `sync` must not create one giant candidate bucket."""
    tasks = [
        RuntimeTask(
            name=f"queue-{index}-sync",
            file_path=f"workers/{index}.py",
            runtime_kind="celery",
        )
        for index in range(251)
    ]
    evidence = [
        DispatchEvidence(
            file_path=f"src/marker_{index}.py",
            language="python",
            relation="direct",
            target_aliases=("sync",),
        )
        for index in range(257)
    ]
    runtime = RuntimeScan(tasks=tasks)

    _link_runtime_evidence(runtime, evidence, [])

    # `sync.delay` names no `queue-N-sync` task. It must not verify all 251
    # merely because their terminal word run is the same.
    assert runtime.scan_stats["link_task_checks"] == 0


def test_duplicate_signal_task_names_keep_own_trigger_links() -> None:
    """Same-name handlers must not share the last task's trigger patterns."""
    for triggers in (("post_save", "post_delete"), ("post_delete", "post_save")):
        tasks = [
            RuntimeTask(
                name="handle",
                file_path=f"handlers/{trigger}.py",
                runtime_kind="django_signal",
                triggers=[trigger],
            )
            for trigger in triggers
        ]
        evidence = _collect_dispatch_evidence(
            {"producer.py": "post_save.send(sender=Order)\n"},
            {"producer.py": "python"},
        )
        _link_runtime_evidence(RuntimeScan(tasks=tasks), evidence, [])
        links = {task.triggers[0]: task.producer_files for task in tasks}
        assert links == {"post_save": ["producer.py"], "post_delete": []}


def test_qualified_laravel_dispatch_keeps_its_producer_link() -> None:
    """Exact indexes must retain valid qualified PHP class dispatches."""
    task = RuntimeTask(
        name=r"App\Jobs\SyncOrders",
        file_path="app/Jobs/SyncOrders.php",
        runtime_kind="laravel_job",
    )
    evidence = _collect_dispatch_evidence(
        {"app/Http/OrderController.php": "<?php\ndispatch(new App\\Jobs\\SyncOrders($order));\n"},
        {"app/Http/OrderController.php": "php"},
    )
    _link_runtime_evidence(RuntimeScan(tasks=[task]), evidence, [])
    assert task.producer_files == ["app/Http/OrderController.php"]


def test_unindexable_cron_trigger_does_not_restore_task_candidate_multiplier() -> None:
    """A non-word cron trigger must not unindex its otherwise linkable task."""
    task_count = 251
    marker_files = 257
    service = "src/jobs/cron.service.ts"
    body = "import { Cron } from '@nestjs/schedule';\n\nexport class CronService {\n"
    for index in range(task_count):
        body += f"  @Cron('* * * * *')\n  task_{index}() {{ return {index}; }}\n\n"
    body += "}\n"

    tasks = _discover_nestjs_runtime({service: body})
    assert len(tasks) == task_count
    assert (tasks[7].name, tasks[7].triggers) == ("task_7", ["* * * * *"])

    file_contents = {service: body}
    languages = {service: "typescript"}
    for index in range(marker_files):
        path = f"src/vs/editor/animation{index}.ts"
        file_contents[path] = (
            f"export function run{index}() {{ this.unrelated.delay(payload); }}\n"
        )
        languages[path] = "typescript"
    producer_path = "src/jobs/producer.py"
    file_contents[producer_path] = "task_7.delay(payload)\n"
    languages[producer_path] = "python"

    evidence = _collect_dispatch_evidence(file_contents, languages)
    runtime = RuntimeScan(tasks=tasks)
    _link_runtime_evidence(runtime, evidence, [])

    assert [item.file_path for item in evidence] == [producer_path]
    assert runtime.scan_stats["link_task_checks"] == 1
    assert {
        task.name: task.producer_files for task in runtime.tasks if task.producer_files
    } == {"task_7": [producer_path]}


def test_js_queue_worker_accepts_whitespace_before_process_call() -> None:
    """A real bound Bull call remains valid with whitespace before `(`."""
    source = (
        "const Bull = require('bull');\n"
        "const queue = new Bull('emails');\n"
        "queue.process ('send-digest', handler);\n"
    )
    parsed = parse_file(Path("workers/email.js"), source)
    assert parsed is not None

    runtime = discover_runtime_surfaces({"workers/email.js": parsed}, {"workers/email.js": source})

    assert [
        (task.name, task.runtime_kind, task.queue) for task in runtime.tasks
    ] == [("send-digest", "js_worker", "send-digest")]


def test_js_scheduler_and_realtime_require_bound_executable_calls() -> None:
    """JS template text is not runtime evidence; bound calls remain evidence."""
    template_source = (
        "const prompt = `\n"
        "const cron = require('node-cron');\n"
        "cron.schedule('* * * * *', work);\n"
        "const io = require('socket.io');\n"
        "io.on('connection', socket => socket.on('message', handler));\n"
        "`;\n"
    )
    template_parsed = parse_file(Path("src/prompt.ts"), template_source)
    assert template_parsed is not None
    template_runtime = discover_runtime_surfaces(
        {"src/prompt.ts": template_parsed}, {"src/prompt.ts": template_source}
    )
    assert template_runtime.schedulers == []
    assert template_runtime.realtime_consumers == []

    sources = {
        "jobs/cron.js": (
            "const cron = require('node-cron');\n"
            "cron.schedule('*/5 * * * *', syncInventory);\n"
        ),
        "realtime/server.js": (
            "const Server = require('socket.io').Server;\n"
            "const io = new Server(server);\n"
            "io.on('connection', handler);\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file
    runtime = discover_runtime_surfaces(parsed, sources)

    assert [(scheduler.scheduler_type, scheduler.cron) for scheduler in runtime.schedulers] == [
        ("node_cron", "*/5 * * * *")
    ]
    assert [(consumer.consumer_type, consumer.routes) for consumer in runtime.realtime_consumers] == [
        ("socket_io", ["connection"])
    ]


def test_js_node_cron_schedule_names_reset_per_file() -> None:
    """Structural node-cron discovery preserves the prior per-file name scope."""
    sources = {
        "jobs/first.js": (
            "const cron = require('node-cron');\n"
            "cron.schedule('* * * * *', first);\n"
        ),
        "jobs/second.js": (
            "const cron = require('node-cron');\n"
            "cron.schedule('*/2 * * * *', second);\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)

    assert [(scheduler.file_path, scheduler.name) for scheduler in runtime.schedulers] == [
        ("jobs/first.js", "node-cron-1"),
        ("jobs/second.js", "node-cron-1"),
    ]


def test_js_socketio_default_factory_has_bound_connection() -> None:
    """The documented Socket.IO default factory is structural evidence too."""
    source = (
        "const socketIO = require('socket.io');\n"
        "const io = socketIO(server);\n"
        "io.on('connection', handleConnection);\n"
    )
    parsed = parse_file(Path("realtime/default-factory.js"), source)
    assert parsed is not None

    runtime = discover_runtime_surfaces(
        {"realtime/default-factory.js": parsed},
        {"realtime/default-factory.js": source},
    )

    assert [(consumer.consumer_type, consumer.routes) for consumer in runtime.realtime_consumers] == [
        ("socket_io", ["connection"])
    ]


def test_js_socketio_direct_require_factory_has_bound_connection() -> None:
    """A direct `require('socket.io')(server)` factory remains bound evidence."""
    source = (
        "const io = require('socket.io')(server);\n"
        "io.on('connection', handleConnection);\n"
    )
    parsed = parse_file(Path("realtime/direct-factory.js"), source)
    assert parsed is not None

    runtime = discover_runtime_surfaces(
        {"realtime/direct-factory.js": parsed},
        {"realtime/direct-factory.js": source},
    )

    assert [(consumer.consumer_type, consumer.routes) for consumer in runtime.realtime_consumers] == [
        ("socket_io", ["connection"])
    ]


def test_js_shadowed_require_is_not_runtime_evidence() -> None:
    """A local parameter named require is not Node's module loader."""
    source = (
        "function configure(require) {\n"
        "  const io = require('socket.io')(server);\n"
        "  io.on('connection', handleConnection);\n"
        "}\n"
    )
    parsed = parse_file(Path("realtime/shadowed-require.js"), source)
    assert parsed is not None

    runtime = discover_runtime_surfaces(
        {"realtime/shadowed-require.js": parsed},
        {"realtime/shadowed-require.js": source},
    )

    assert runtime.realtime_consumers == []


def test_js_function_named_require_is_not_runtime_evidence() -> None:
    """A local hoisted function named require also shadows Node's loader."""
    source = (
        "function require(moduleName) { return () => moduleName; }\n"
        "const io = require('socket.io')(server);\n"
        "io.on('connection', handleConnection);\n"
    )
    parsed = parse_file(Path("realtime/function-require.js"), source)
    assert parsed is not None

    runtime = discover_runtime_surfaces(
        {"realtime/function-require.js": parsed},
        {"realtime/function-require.js": source},
    )

    assert runtime.realtime_consumers == []


def test_queue_add_preserves_punctuation_only_worker_queue_links() -> None:
    """Queue literals need an exact index even when their names have no word run."""
    files = {
        "workers/punctuation.js": (
            "const Worker = require('bullmq').Worker;\n"
            "new Worker('---', handler);\n"
        ),
        "src/producer.js": (
            "const Queue = require('bullmq').Queue;\n"
            "const queue = new Queue('---');\n"
            "queue.add('---', {});\n"
        ),
    }
    parsed = {}
    for path, content in files.items():
        parsed_file = parse_file(Path(path), content)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, files)

    worker = next(task for task in runtime.tasks if task.name == "---")
    assert worker.producer_files == ["src/producer.js"]


def test_direct_dispatch_evidence_rejects_ambiguous_duplicate_task_bucket() -> None:
    """One direct spelling never expands across every same-name task record."""
    tasks = [
        RuntimeTask(
            name="sync",
            file_path=f"workers/sync_{index}.py",
            runtime_kind="celery",
        )
        for index in range(251)
    ]
    evidence = [
        DispatchEvidence(
            file_path=f"producers/producer_{index}.py",
            language="python",
            relation="direct",
            target_aliases=("sync",),
        )
        for index in range(257)
    ]
    runtime = RuntimeScan(tasks=tasks)

    _link_runtime_evidence(runtime, evidence, [])

    assert runtime.scan_stats["link_task_checks"] == 0
    assert runtime.scan_stats["link_ambiguous_task_targets"] == len(evidence)
    assert runtime.scan_stats["link_index_probes"] == len(evidence)
    assert all(task.producer_files == [] for task in tasks)


def test_queue_evidence_rejects_ambiguous_duplicate_queue_bucket_in_constant_lookups() -> None:
    """A duplicate queue name cannot restore producer-evidence × worker work."""
    tasks = [
        RuntimeTask(
            name=f"worker_{index}",
            queue="orders",
            file_path=f"workers/{index}.js",
            runtime_kind="js_worker",
        )
        for index in range(251)
    ]
    evidence = [
        DispatchEvidence(
            file_path=f"producers/{index}.js",
            language="javascript",
            relation="queue",
            target_aliases=("orders",),
        )
        for index in range(257)
    ]
    runtime = RuntimeScan(tasks=tasks)

    _link_runtime_evidence(runtime, evidence, [])

    assert runtime.scan_stats["link_task_checks"] == 0
    assert runtime.scan_stats["link_ambiguous_task_targets"] == len(evidence)
    assert runtime.scan_stats["link_index_probes"] == len(evidence)
    assert all(task.producer_files == [] for task in tasks)


def test_scheduler_endpoint_links_require_matching_dispatch_evidence() -> None:
    """Endpoint-owning files do not sweep every scheduler without a target hit."""
    schedulers = [
        RuntimeScheduler(
            name=f"scheduler-{index}",
            file_path=f"schedules/{index}.py",
            scheduler_type="beat",
            invoked_targets=[f"task_{index}"],
        )
        for index in range(251)
    ]
    evidence = [
        DispatchEvidence(
            file_path=f"handlers/handler_{index}.py",
            language="python",
            relation="direct",
            target_aliases=("unrelated",),
        )
        for index in range(257)
    ]
    endpoints = [
        {
            "method": "POST",
            "path": f"/jobs/{index}",
            "file": f"handlers/handler_{index}.py",
        }
        for index in range(257)
    ]
    runtime = RuntimeScan(schedulers=schedulers)

    _link_runtime_evidence(runtime, evidence, endpoints)

    assert runtime.scan_stats["link_scheduler_checks"] == 0
    assert all(scheduler.linked_endpoints == [] for scheduler in schedulers)


def test_qualified_dispatch_does_not_link_schedulers_by_terminal_name() -> None:
    """A qualified dispatch may not fan out through unrelated `sync` suffixes."""
    schedulers = [
        RuntimeScheduler(
            name=f"scheduler-{index}",
            file_path=f"schedules/{index}.py",
            scheduler_type="beat",
            invoked_targets=[f"other_{index}.tasks.sync"],
        )
        for index in range(251)
    ]
    runtime = RuntimeScan(schedulers=schedulers)
    evidence = [
        DispatchEvidence(
            file_path="handlers/orders.py",
            language="python",
            relation="direct",
            target_aliases=("orders.tasks.sync", "sync"),
        )
    ]

    _link_runtime_evidence(
        runtime,
        evidence,
        [{"method": "POST", "path": "/orders", "file": "handlers/orders.py"}],
    )

    assert runtime.scan_stats["link_scheduler_checks"] == 0
    assert all(scheduler.linked_endpoints == [] for scheduler in schedulers)


def test_python_dispatch_evidence_uses_executable_ast_calls() -> None:
    """Whitespace-valid calls count; comments and strings never do."""
    path = "handlers/orders.py"
    source = (
        'example = "sync.delay(payload)"\n'
        "# post_save.send(sender=Order)\n"
        "sync . delay(payload)\n"
        "post_save . send(sender=Order)\n"
    )

    evidence = _collect_dispatch_evidence({path: source}, {path: "python"})

    assert [(item.relation, item.target_aliases) for item in evidence] == [
        ("direct", ("sync",)),
        ("signal", ("post_save",)),
    ]


def test_php_dispatch_evidence_links_fqcn_and_short_discovered_targets() -> None:
    """Structural PHP dispatches normalize leading-root and short-name aliases."""
    path = "app/Http/OrderController.php"
    source = """<?php
    \\App\\Jobs\\SyncOrders::dispatch($order);
    dispatch(\\App\\Jobs\\SyncOrders::class);
    dispatch(new App\\Jobs\\SyncOrders($order));
    event(new \\App\\Events\\OrderShipped($order));
    """
    runtime = RuntimeScan(
        tasks=[
            RuntimeTask(
                name="SyncOrders",
                file_path="app/Jobs/SyncOrders.php",
                runtime_kind="laravel_job",
            ),
            RuntimeTask(
                name="OrderShipped",
                file_path="app/Events/OrderShipped.php",
                runtime_kind="laravel_event",
            ),
        ]
    )

    evidence = _collect_dispatch_evidence({path: source}, {path: "php"})
    _link_runtime_evidence(runtime, evidence, [])

    assert [(item.relation, item.target_aliases) for item in evidence] == [
        ("direct", (r"App\Jobs\SyncOrders", "SyncOrders")),
        ("direct", (r"App\Jobs\SyncOrders", "SyncOrders")),
        ("direct", (r"App\Jobs\SyncOrders", "SyncOrders")),
        ("direct", (r"App\Events\OrderShipped", "OrderShipped")),
    ]
    assert runtime.tasks[0].producer_files == [path]
    assert runtime.tasks[1].producer_files == [path]


def test_php_dispatch_evidence_rejects_malformed_source() -> None:
    """Tree-sitter recovery nodes cannot authenticate executable dispatches."""
    path = "app/Http/BrokenController.php"
    source = "<?php\ndispatch(new SyncOrders($order);\n"

    assert _collect_dispatch_evidence({path: source}, {path: "php"}) == []


def test_php_dispatch_import_alias_resolves_to_its_actual_class() -> None:
    """A `use ... as Alias` dispatch cannot link an unrelated short-name task."""
    path = "app/Http/OrderController.php"
    source = """<?php
use App\\Other\\ExportJob as SyncOrders;
dispatch(new SyncOrders($order));
"""
    unrelated = RuntimeTask(
        name="SyncOrders",
        file_path="app/Jobs/SyncOrders.php",
        runtime_kind="laravel_job",
    )
    actual = RuntimeTask(
        name="ExportJob",
        file_path="app/Other/ExportJob.php",
        runtime_kind="laravel_job",
    )
    runtime = RuntimeScan(tasks=[unrelated, actual])

    evidence = _collect_dispatch_evidence({path: source}, {path: "php"})
    _link_runtime_evidence(runtime, evidence, [])

    assert [(item.relation, item.target_aliases) for item in evidence] == [
        ("direct", (r"App\Other\ExportJob", "ExportJob"))
    ]
    assert unrelated.producer_files == []
    assert actual.producer_files == [path]


def test_php_dispatch_plain_import_keeps_short_task_link() -> None:
    """A normal Laravel class import retains the valid short discovered target."""
    path = "app/Http/OrderController.php"
    source = """<?php
use App\\Jobs\\SyncOrders;
dispatch(new SyncOrders($order));
"""
    task = RuntimeTask(
        name="SyncOrders",
        file_path="app/Jobs/SyncOrders.php",
        runtime_kind="laravel_job",
    )

    evidence = _collect_dispatch_evidence({path: source}, {path: "php"})
    _link_runtime_evidence(RuntimeScan(tasks=[task]), evidence, [])

    assert evidence[0].target_aliases == (r"App\Jobs\SyncOrders", "SyncOrders")
    assert task.producer_files == [path]


def test_php_grouped_import_alias_resolves_to_its_actual_class() -> None:
    """Grouped `use` aliases receive the same canonical collision protection."""
    path = "app/Http/OrderController.php"
    source = """<?php
use App\\Other\\{ExportJob as SyncOrders, AnotherJob};
dispatch(new SyncOrders($order));
"""
    unrelated = RuntimeTask(
        name="SyncOrders",
        file_path="app/Jobs/SyncOrders.php",
        runtime_kind="laravel_job",
    )
    actual = RuntimeTask(
        name="ExportJob",
        file_path="app/Other/ExportJob.php",
        runtime_kind="laravel_job",
    )
    runtime = RuntimeScan(tasks=[unrelated, actual])

    evidence = _collect_dispatch_evidence({path: source}, {path: "php"})
    _link_runtime_evidence(runtime, evidence, [])

    assert evidence[0].target_aliases == (r"App\Other\ExportJob", "ExportJob")
    assert unrelated.producer_files == []
    assert actual.producer_files == [path]


def test_php_grouped_function_and_const_imports_do_not_alias_classes() -> None:
    """Non-class grouped imports cannot rebind a class dispatch target."""
    path = "app/Http/OrderController.php"
    source = """<?php
use App\\Jobs\\{function helper as SyncOrders, const FLAG as ExportJob};
dispatch(new SyncOrders());
event(new ExportJob());
"""

    evidence = _collect_dispatch_evidence({path: source}, {path: "php"})

    assert [item.target_aliases for item in evidence] == [
        ("SyncOrders",),
        ("ExportJob",),
    ]


def test_js_scope_forms_shadow_require_before_runtime_binding() -> None:
    """All lexical forms that bind `require` suppress CommonJS runtime evidence."""
    sources = {
        "realtime/var.js": (
            "function configure() {\n"
            "  if (flag) { var require = loader; }\n"
            "  const io = require('socket.io')(server);\n"
            "  io.on('connection', handler);\n"
            "}\n"
        ),
        "realtime/var-newline.js": (
            "function configure() {\n"
            "  if (flag) { var\nrequire = loader; }\n"
            "  const io = require('socket.io')(server);\n"
            "  io.on('connection', handler);\n"
            "}\n"
        ),
        "realtime/var-tab.js": (
            "function configure() {\n"
            "  if (flag) { var\trequire = loader; }\n"
            "  const io = require('socket.io')(server);\n"
            "  io.on('connection', handler);\n"
            "}\n"
        ),
        "realtime/function-expression.js": (
            "const configure = function require() {\n"
            "  const io = require('socket.io')(server);\n"
            "  io.on('connection', handler);\n"
            "};\n"
        ),
        "realtime/class-expression.js": (
            "const Configure = class require {\n"
            "  boot() {\n"
            "    const io = require('socket.io')(server);\n"
            "    io.on('connection', handler);\n"
            "  }\n"
            "};\n"
        ),
        "realtime/import-alias.ts": (
            "import require = shim.require;\n"
            "const io = require('socket.io')(server);\n"
            "io.on('connection', handler);\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)

    assert runtime.realtime_consumers == []


def test_js_member_alias_queue_add_requires_bound_queue_role() -> None:
    """A literal enqueue is evidence only through a proven queue API role."""
    bound_path = "producers/bound.js"
    generic_path = "producers/generic.js"
    sources = {
        bound_path: (
            "const Queue = require('bullmq').Queue;\n"
            "const queue = new Queue('---');\n"
            "queue . add('---', payload);\n"
        ),
        generic_path: "const queue = getQueue();\nqueue.add('---', payload);\n",
    }
    evidence = _collect_dispatch_evidence(
        sources, {path: "javascript" for path in sources}
    )
    task = RuntimeTask(
        name="---",
        queue="---",
        file_path="workers/punctuation.js",
        runtime_kind="js_worker",
    )
    runtime = RuntimeScan(tasks=[task])

    _link_runtime_evidence(runtime, evidence, [])

    assert [(item.file_path, item.relation, item.target_aliases) for item in evidence] == [
        (bound_path, "queue", ("---",)),
    ]
    assert task.producer_files == [bound_path]


def test_signal_dispatch_evidence_broadcasts_only_matching_handlers() -> None:
    """Signal delivery is explicit fan-out, not duplicate-name task ambiguity."""
    post_save = RuntimeTask(
        name="handle",
        file_path="handlers/save.py",
        runtime_kind="django_signal",
        triggers=["post_save"],
    )
    post_delete = RuntimeTask(
        name="handle",
        file_path="handlers/delete.py",
        runtime_kind="django_signal",
        triggers=["post_delete"],
    )
    runtime = RuntimeScan(tasks=[post_save, post_delete])
    evidence = [
        DispatchEvidence(
            file_path="orders/api.py",
            language="python",
            relation="signal",
            target_aliases=("post_save",),
        )
    ]

    _link_runtime_evidence(runtime, evidence, [])

    assert post_save.producer_files == ["orders/api.py"]
    assert post_delete.producer_files == []
    assert runtime.scan_stats["link_signal_broadcast_edges"] == 1


def test_scheduler_owner_evidence_links_only_owning_scheduler() -> None:
    """Scheduler declarations are direct evidence, not a global endpoint sweep."""
    schedulers = [
        RuntimeScheduler(
            name=f"scheduler-{index}",
            file_path=f"schedules/{index}.py",
            scheduler_type="beat",
            invoked_targets=[f"task_{index}"],
        )
        for index in range(251)
    ]
    runtime = RuntimeScan(schedulers=schedulers)
    evidence = [
        DispatchEvidence(
            file_path="schedules/7.py",
            language="python",
            relation="scheduler_owner",
            target_aliases=("scheduler-7",),
        )
    ]

    _link_runtime_evidence(
        runtime,
        evidence,
        [{"method": "POST", "path": "/jobs/7", "file": "schedules/7.py"}],
    )

    assert schedulers[7].linked_endpoints == ["POST /jobs/7"]
    assert all(
        scheduler.linked_endpoints == []
        for index, scheduler in enumerate(schedulers)
        if index != 7
    )
    assert runtime.scan_stats["link_scheduler_checks"] == 1


def test_runtime_scan_links_only_structural_dispatch_evidence() -> None:
    """Producer links come from real source grammar, never raw cross-language text."""
    files = {
        "workers/tasks.py": (
            "from celery import shared_task\n\n"
            "@shared_task\n"
            "def sync(order_id):\n"
            "    return order_id\n"
        ),
        "handlers/orders.py": "sync . delay(order_id)\n",
        "src/notes.ts": "const prompt = `sync.delay(order_id)`;\n",
        "src/generic.js": "const queue = getQueue();\nqueue.add('sync', {});\n",
        "src/comments.js": (
            "// const Queue = require('bullmq').Queue;\n"
            "// const queue = new Queue('sync');\n"
            "// queue.add('sync', {});\n"
        ),
    }
    parsed = {}
    for path, source in files.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, files)
    worker = next(
        task
        for task in runtime.tasks
        if task.file_path == "workers/tasks.py" and task.name == "sync"
    )

    assert worker.producer_files == ["handlers/orders.py"]
    assert [item.file_path for item in runtime.dispatch_evidence] == [
        "handlers/orders.py"
    ]
    assert runtime.scan_stats["link_candidate_files"] == 1


def test_python_qualified_dispatch_alias_links_short_task_name() -> None:
    """A dotted Python task reference keeps its full and terminal aliases."""
    path = "handlers/orders.py"
    task = RuntimeTask(
        name="sync",
        file_path="workers/tasks.py",
        runtime_kind="celery",
    )
    evidence = _collect_dispatch_evidence(
        {path: "tasks.sync . delay(order_id)\n"}, {path: "python"}
    )

    _link_runtime_evidence(RuntimeScan(tasks=[task]), evidence, [])

    assert evidence[0].target_aliases == ("tasks.sync", "sync")
    assert task.producer_files == [path]


def test_dotted_scheduler_target_links_short_dispatch_evidence() -> None:
    """A dotted scheduler target resolves a unique terminal task dispatch."""
    scheduler = RuntimeScheduler(
        name="nightly-sync",
        file_path="schedules/beat.py",
        scheduler_type="beat",
        invoked_targets=["orders.tasks.sync"],
    )
    runtime = RuntimeScan(schedulers=[scheduler])
    evidence = [
        DispatchEvidence(
            file_path="handlers/orders.py",
            language="python",
            relation="direct",
            target_aliases=("sync",),
        )
    ]

    _link_runtime_evidence(
        runtime,
        evidence,
        [{"method": "POST", "path": "/orders/sync", "file": "handlers/orders.py"}],
    )

    assert scheduler.linked_endpoints == ["POST /orders/sync"]
    assert runtime.scan_stats["link_scheduler_checks"] == 1


def test_queue_evidence_requires_an_explicit_worker_queue() -> None:
    """A queue literal cannot link an unrelated task merely by display name."""
    task = RuntimeTask(
        name="orders",
        file_path="workers/tasks.py",
        runtime_kind="celery",
    )
    runtime = RuntimeScan(tasks=[task])
    evidence = [
        DispatchEvidence(
            file_path="producers/orders.js",
            language="javascript",
            relation="queue",
            target_aliases=("orders",),
        )
    ]

    _link_runtime_evidence(runtime, evidence, [])

    assert task.producer_files == []
    assert runtime.scan_stats["link_task_checks"] == 0


def test_malformed_js_never_creates_runtime_evidence() -> None:
    """Tree-sitter recovery nodes cannot authenticate JS runtime APIs."""
    path = "workers/broken.js"
    source = (
        "const { Worker } = require('bullmq');\n"
        "new Worker('broken', handler;\n"
    )
    parsed = parse_file(Path(path), source)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: source})

    assert runtime.tasks == []


def test_type_only_typescript_imports_do_not_bind_runtime_apis() -> None:
    """Erased imports cannot authenticate queue or realtime values at runtime."""
    sources = {
        "workers/type-only.ts": (
            "import type { Queue, Worker } from 'bullmq';\n"
            "const queue = new Queue('orders');\n"
            "queue.add('send-order', {});\n"
            "new Worker('orders', handleOrder);\n"
        ),
        "realtime/type-only.ts": (
            "import type { Server } from 'socket.io';\n"
            "const io = new Server(server);\n"
            "io.on('connection', handleConnection);\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)

    assert runtime.tasks == []
    assert runtime.realtime_consumers == []
    assert runtime.dispatch_evidence == []


def test_mixed_type_and_value_imports_bind_only_runtime_values() -> None:
    """A `type Queue` specifier cannot piggyback on a real `Worker` import."""
    path = "workers/mixed.ts"
    source = (
        "import { type Queue, Worker } from 'bullmq';\n"
        "const queue = new Queue('orders');\n"
        "queue.add('send-order', {});\n"
        "new Worker('orders', handleOrder);\n"
    )
    parsed = parse_file(Path(path), source)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: source})

    assert [(task.name, task.queue) for task in runtime.tasks] == [("orders", "orders")]
    assert runtime.dispatch_evidence == []


def test_js_named_node_cron_schedule_bindings_are_discovered() -> None:
    """Named and CommonJS-member scheduler bindings survive prefiltering."""
    sources = {
        "jobs/named.ts": (
            "import { schedule } from 'node-cron';\n"
            "schedule('* * * * *', namedTask);\n"
        ),
        "jobs/member.js": (
            "const schedule = require('node-cron').schedule;\n"
            "schedule('*/5 * * * *', memberTask);\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)

    assert [
        (scheduler.file_path, scheduler.cron, scheduler.invoked_targets)
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "node_cron"
    ] == [
        ("jobs/named.ts", "* * * * *", ["namedTask"]),
        ("jobs/member.js", "*/5 * * * *", ["memberTask"]),
    ]


def test_js_runtime_bindings_follow_lexical_write_history() -> None:
    """Dynamic writes invalidate a binding without erasing valid sibling scopes."""
    sources = {
        "workers/reassigned.js": (
            "const Queue = require('bullmq').Queue;\n"
            "let queue = new Queue('orders');\n"
            "queue = getDynamicQueue();\n"
            "queue.add('send-order', {});\n"
        ),
        "realtime/reassigned.js": (
            "require = customLoader;\n"
            "const io = require('socket.io')(server);\n"
            "io.on('connection', handleConnection);\n"
        ),
        "workers/siblings.js": (
            "const Bull = require('bull');\n"
            "function first() {\n"
            "  var queue = new Bull('first');\n"
            "  queue.process('first', handleFirst);\n"
            "}\n"
            "function second() {\n"
            "  var queue = new Bull('second');\n"
            "  queue.process('second', handleSecond);\n"
            "}\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)

    assert [
        (task.file_path, task.name, task.queue)
        for task in runtime.tasks
        if task.runtime_kind == "js_worker"
    ] == [
        ("workers/siblings.js", "first", "first"),
        ("workers/siblings.js", "second", "second"),
    ]
    assert runtime.dispatch_evidence == []
    assert runtime.realtime_consumers == []


def test_js_dynamic_object_destructuring_invalidates_bound_receiver() -> None:
    """A destructuring assignment is a real write, not a safe Queue alias."""
    path = "jobs/object-reassignment.js"
    source = (
        "const Queue = require('bullmq').Queue;\n"
        "let queue = new Queue('orders');\n"
        "({ queue } = getDynamicQueue());\n"
        "queue.add('send-order', {});\n"
    )
    parsed = parse_file(Path(path), source)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: source})

    assert runtime.dispatch_evidence == []


def test_js_dynamic_array_destructuring_invalidates_bound_receiver() -> None:
    """Array destructuring writes likewise revoke a prior Queue binding."""
    path = "jobs/array-reassignment.js"
    source = (
        "const Queue = require('bullmq').Queue;\n"
        "let queue = new Queue('orders');\n"
        "[queue] = getDynamicQueues();\n"
        "queue.add('send-order', {});\n"
    )
    parsed = parse_file(Path(path), source)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: source})

    assert runtime.dispatch_evidence == []


def test_js_for_of_write_invalidates_bound_receiver() -> None:
    """A loop target is an assignment to the existing lexical receiver."""
    path = "jobs/for-of-reassignment.js"
    source = (
        "const Queue = require('bullmq').Queue;\n"
        "let queue = new Queue('orders');\n"
        "for (queue of values) { queue.add('send-order', {}); }\n"
    )
    parsed = parse_file(Path(path), source)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: source})

    assert runtime.dispatch_evidence == []


def test_js_for_of_local_declaration_shadows_without_erasing_outer_binding() -> None:
    """A loop-local `const` is not a write to the outer Queue variable."""
    path = "jobs/for-of-shadow.js"
    source = (
        "const Queue = require('bullmq').Queue;\n"
        "const queue = new Queue('outer');\n"
        "for (const queue of values) { queue.add('inner', {}); }\n"
        "queue.add('outer-job', {});\n"
    )
    parsed = parse_file(Path(path), source)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: source})

    assert [(item.relation, item.target_aliases) for item in runtime.dispatch_evidence] == [
        ("queue", ("outer",))
    ]


def test_js_update_expression_invalidates_bound_receiver() -> None:
    """An increment/decrement writes an unknown value to the local receiver."""
    path = "jobs/update-reassignment.js"
    source = (
        "const Queue = require('bullmq').Queue;\n"
        "let queue = new Queue('orders');\n"
        "queue++;\n"
        "queue.add('send-order', {});\n"
    )
    parsed = parse_file(Path(path), source)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: source})

    assert runtime.dispatch_evidence == []


def test_js_queue_evidence_uses_bound_constructor_queue_identity() -> None:
    """Queue producer evidence uses Queue's name, not BullMQ's job name."""
    producer = "producers/email.js"
    sources = {
        producer: (
            "const Queue = require('bullmq').Queue;\n"
            "const queue = new Queue('email-events');\n"
            "queue.add('send-digest', {});\n"
        ),
        "producers/dynamic.js": (
            "const Queue = require('bullmq').Queue;\n"
            "const queue = new Queue(queueName);\n"
            "queue.add('send-digest', {});\n"
        ),
        "workers/email.js": (
            "const Worker = require('bullmq').Worker;\n"
            "new Worker('email-events', handleEmail);\n"
        ),
        "workers/job.js": (
            "const Worker = require('bullmq').Worker;\n"
            "new Worker('send-digest', handleDigest);\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)
    workers = {task.queue: task for task in runtime.tasks if task.runtime_kind == "js_worker"}

    assert [(item.file_path, item.target_aliases) for item in runtime.dispatch_evidence] == [
        (producer, ("email-events",))
    ]
    assert workers["email-events"].producer_files == [producer]
    assert workers["send-digest"].producer_files == []
