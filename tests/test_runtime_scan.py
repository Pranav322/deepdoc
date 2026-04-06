from __future__ import annotations

from pathlib import Path

from deepdoc.parser.base import ParsedFile, Symbol
from deepdoc.scanner import (
    discover_config_impacts,
    discover_database_schema,
    discover_debug_signals,
    discover_runtime_surfaces,
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
            "const { Worker } = require('bullmq');\n"
            "const agenda = new Agenda();\n"
            "new Worker('orders-sync', async job => syncOrders(job));\n"
            "queue.process('inventory-refresh', async refreshInventory);\n"
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
