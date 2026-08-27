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
from deepdoc.scanner.common import RuntimeScan
from deepdoc.scanner.runtime import _discover_nestjs_runtime, _link_runtime_workflows


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
    assert "send_invoice" in task_names
    assert "beat" in scheduler_types
    assert "node_cron" in scheduler_types

    celery_task = next(task for task in runtime.tasks if task.name == "sync_orders")
    assert celery_task.queue == "critical"
    assert "autoretry_for" in celery_task.retry_policy

    triggered_task = next(task for task in runtime.tasks if task.name == "send_invoice")
    assert triggered_task.triggers == ["delay"]
    assert triggered_task.producer_files == ["orders/tasks.py"]
    assert triggered_task.linked_endpoints == ["POST /api/orders/sync"]

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
            "new Worker('inventory-refresh', async refreshInventory);\n"
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
    assert stats["link_candidate_files"] == marker_files + 1
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
            "const queue = getQueue();\nqueue.add('orders-sync', {});\n"
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
    for index in range(marker_files):
        file_contents[f"src/vs/editor/animation{index}.ts"] = (
            f"export function run{index}() {{ this.unrelated.delay(payload); }}\n"
        )
    file_contents["src/jobs/producer.ts"] = "task_7.delay(payload);\n"

    runtime = RuntimeScan(tasks=tasks)
    candidate_files, task_checks = _link_runtime_workflows(runtime, file_contents, [])

    assert candidate_files == marker_files + 1
    assert task_checks <= 4
    assert {
        task.name: task.producer_files for task in runtime.tasks if task.producer_files
    } == {"task_7": ["src/jobs/producer.ts"]}


def test_queue_add_preserves_punctuation_only_worker_queue_links() -> None:
    """Queue literals need an exact index even when their names have no word run."""
    files = {
        "workers/punctuation.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('---', handler);\n"
        ),
        "src/producer.js": "const queue = getQueue();\nqueue.add('---', {});\n",
    }
    parsed = {}
    for path, content in files.items():
        parsed_file = parse_file(Path(path), content)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, files)

    worker = next(task for task in runtime.tasks if task.name == "---")
    assert worker.producer_files == ["src/producer.js"]
