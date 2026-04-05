from __future__ import annotations

from pathlib import Path

from deepdoc.parser.base import ParsedFile, Symbol
from deepdoc.scan_v2 import discover_database_schema, discover_runtime_surfaces


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


def test_runtime_and_database_discovery_extracts_runtime_graphql_and_knex_surfaces() -> None:
    parsed_files = {
        "orders/models.py": _parsed_file(
            "orders/models.py",
            imports=["import catalog.models"],
            symbols=[
                Symbol(name="Order", kind="class", signature="class Order(models.Model):"),
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
        "orders/scheduler.js": _parsed_file("orders/scheduler.js", language="javascript"),
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

    runtime = discover_runtime_surfaces(parsed_files, file_contents)

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
