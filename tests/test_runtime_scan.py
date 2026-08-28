from __future__ import annotations

from pathlib import Path

from deepdoc.parser.base import ParsedFile, Symbol
from deepdoc.parser import js_ts_parser
from deepdoc.scanner import runtime as runtime_parser
from deepdoc.parser.php_parser import php_dispatches
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
            "from celery import current_app as app\n"
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
        "app/Http/OrderController.php": _parsed_file(
            "app/Http/OrderController.php", language="php"
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
        "app/Http/OrderController.php": "<?php\nevent(new OrderShipped());\n",
        "app/Console/Kernel.php": (
            "<?php\n"
            "use Illuminate\\Console\\Scheduling\\Schedule;\n"
            "use Illuminate\\Foundation\\Console\\Kernel as ConsoleKernel;\n"
            "class Kernel extends ConsoleKernel\n"
            "{\n"
            "    protected function schedule(Schedule $schedule): void\n"
            "    {\n"
            "        $schedule->command('orders:sync')->dailyAt('02:00');\n"
            "        $schedule->job(new SyncOrders)->everyFiveMinutes();\n"
            "    }\n"
            "}\n"
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


def test_php_non_laravel_shouldqueue_interface_cannot_create_job() -> None:
    """A matching terminal interface name is not Laravel framework proof."""
    path = "app/Worker.php"
    source = (
        "<?php\n"
        "namespace Vendor;\n"
        "class Worker implements Contracts\\ShouldQueue {}\n"
    )
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="php")}, {path: source}
    )

    assert [task for task in runtime.tasks if task.runtime_kind == "laravel_job"] == []


def test_php_shouldqueue_job_with_typed_service_handle_is_not_listener() -> None:
    """A queued job dependency is not proof that its `handle()` receives an event."""
    path = "app/Jobs/Archive.php"
    source = (
        "<?php\n"
        "use Illuminate\\Contracts\\Queue\\ShouldQueue;\n"
        "class Archive implements ShouldQueue {\n"
        "    public function handle(Mailer $mailer) {}\n"
        "}\n"
    )
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="php")}, {path: source}
    )

    assert [
        (task.name, task.runtime_kind, task.triggers)
        for task in runtime.tasks
        if task.name == "Archive"
    ] == [("Archive", "laravel_job", [])]


def test_php_unbound_schedule_parameter_cannot_create_laravel_scheduler() -> None:
    """A generic PHP parameter named `$schedule` is not Laravel proof."""
    path = "app/Schedule.php"
    source = "<?php\nfunction run($schedule) { $schedule->command('not:laravel')->daily(); }\n"
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="php")}, {path: source}
    )

    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "laravel_schedule"
    ] == []


def test_php_reassigned_or_closure_shadowed_schedule_cannot_create_scheduler() -> None:
    """Only the original typed Laravel `$schedule` parameter is trusted."""
    sources = {
        "app/Console/ReassignedKernel.php": (
            "<?php\n"
            "use Illuminate\\Console\\Scheduling\\Schedule;\n"
            "use Illuminate\\Foundation\\Console\\Kernel as ConsoleKernel;\n"
            "class Kernel extends ConsoleKernel {\n"
            "    protected function schedule(Schedule $schedule): void {\n"
            "        $schedule = new FakeScheduler();\n"
            "        $schedule->command('forged:run')->daily();\n"
            "    }\n"
            "}\n"
        ),
        "app/Console/ClosureKernel.php": (
            "<?php\n"
            "use Illuminate\\Console\\Scheduling\\Schedule;\n"
            "use Illuminate\\Foundation\\Console\\Kernel as ConsoleKernel;\n"
            "class Kernel extends ConsoleKernel {\n"
            "    protected function schedule(Schedule $schedule): void {\n"
            "        (function ($schedule) {\n"
            "            $schedule->command('forged:closure')->daily();\n"
            "        })(new FakeScheduler());\n"
            "    }\n"
            "}\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="php") for path in sources}, sources
    )

    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "laravel_schedule"
    ] == []


def test_php_reference_rebound_schedule_cannot_create_scheduler() -> None:
    """A by-reference rebind replaces the trusted Schedule parameter binding."""
    path = "app/Console/ReferenceKernel.php"
    source = (
        "<?php\n"
        "use Illuminate\\Console\\Scheduling\\Schedule;\n"
        "use Illuminate\\Foundation\\Console\\Kernel as ConsoleKernel;\n"
        "class Kernel extends ConsoleKernel {\n"
        "    protected function schedule(Schedule $schedule): void {\n"
        "        $other = new FakeScheduler();\n"
        "        $schedule =& $other;\n"
        "        $schedule->command('forged:reference')->daily();\n"
        "    }\n"
        "}\n"
    )
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="php")}, {path: source}
    )

    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "laravel_schedule"
    ] == []


def test_php_by_reference_closure_invocation_revokes_schedule_binding() -> None:
    """An invoked closure capturing `&$schedule` mutates the outer binding."""
    path = "app/Console/IifeKernel.php"
    source = (
        "<?php\n"
        "use Illuminate\\Console\\Scheduling\\Schedule;\n"
        "use Illuminate\\Foundation\\Console\\Kernel as ConsoleKernel;\n"
        "class Kernel extends ConsoleKernel {\n"
        "    protected function schedule(Schedule $schedule): void {\n"
        "        (function () use (&$schedule) {\n"
        "            $schedule = new FakeScheduler();\n"
        "        })();\n"
        "        $schedule->command('forged:iife')->daily();\n"
        "    }\n"
        "}\n"
    )
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="php")}, {path: source}
    )

    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "laravel_schedule"
    ] == []


def test_php_by_value_closure_invocation_preserves_schedule_binding() -> None:
    """A by-value capture cannot rebind the caller's Schedule parameter."""
    path = "app/Console/ByValueKernel.php"
    source = (
        "<?php\n"
        "use Illuminate\\Console\\Scheduling\\Schedule;\n"
        "use Illuminate\\Foundation\\Console\\Kernel as ConsoleKernel;\n"
        "class Kernel extends ConsoleKernel {\n"
        "    protected function schedule(Schedule $schedule): void {\n"
        "        (function () use ($schedule) {\n"
        "            $schedule = new FakeScheduler();\n"
        "        })();\n"
        "        $schedule->command(\"orders:sync\")->daily();\n"
        "    }\n"
        "}\n"
    )
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="php")}, {path: source}
    )

    laravel = [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "laravel_schedule"
    ]
    assert len(laravel) == 1
    assert laravel[0].invoked_targets == ["orders:sync"]


def test_php_destructured_schedule_rebind_cannot_create_scheduler() -> None:
    """Destructuring assignment replaces the trusted Schedule parameter binding."""
    path = "app/Console/DestructuredKernel.php"
    source = (
        "<?php\n"
        "use Illuminate\\Console\\Scheduling\\Schedule;\n"
        "use Illuminate\\Foundation\\Console\\Kernel as ConsoleKernel;\n"
        "class Kernel extends ConsoleKernel {\n"
        "    protected function schedule(Schedule $schedule): void {\n"
        "        [$schedule] = [new FakeScheduler()];\n"
        "        $schedule->command('forged:destructure')->daily();\n"
        "    }\n"
        "}\n"
    )
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="php")}, {path: source}
    )

    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "laravel_schedule"
    ] == []


def test_php_foreach_schedule_rebind_cannot_create_scheduler() -> None:
    """A foreach value variable replaces the typed Schedule parameter binding."""
    path = "app/Console/ForeachKernel.php"
    source = (
        "<?php\n"
        "use Illuminate\\Console\\Scheduling\\Schedule;\n"
        "use Illuminate\\Foundation\\Console\\Kernel as ConsoleKernel;\n"
        "class Kernel extends ConsoleKernel {\n"
        "    protected function schedule(Schedule $schedule): void {\n"
        "        foreach ([new FakeScheduler()] as $schedule) {}\n"
        "        $schedule->command('forged:foreach')->daily();\n"
        "    }\n"
        "}\n"
    )
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="php")}, {path: source}
    )

    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "laravel_schedule"
    ] == []


def test_php_condition_only_schedule_chain_creates_no_scheduler() -> None:
    """A Laravel conditional modifier is not a scheduling cadence."""
    path = "app/Console/Kernel.php"
    source = (
        "<?php\n"
        "use Illuminate\\Console\\Scheduling\\Schedule;\n"
        "use Illuminate\\Foundation\\Console\\Kernel as ConsoleKernel;\n"
        "class Kernel extends ConsoleKernel {\n"
        "    protected function schedule(Schedule $schedule): void {\n"
        "        $schedule->command('orders:sync')->when(fn () => true);\n"
        "    }\n"
        "}\n"
    )
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="php")}, {path: source}
    )

    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "laravel_schedule"
    ] == []


def test_php_static_double_quoted_schedule_command_is_preserved() -> None:
    """A static double quote is evidence; interpolation remains dynamic and inert."""
    sources = {
        "app/Console/StaticKernel.php": (
            "<?php\n"
            "use Illuminate\\Console\\Scheduling\\Schedule;\n"
            "use Illuminate\\Foundation\\Console\\Kernel as ConsoleKernel;\n"
            "class Kernel extends ConsoleKernel {\n"
            "    protected function schedule(Schedule $schedule): void {\n"
            "        $schedule->command(\"orders:sync\")->daily();\n"
            "    }\n"
            "}\n"
        ),
        "app/Console/DynamicKernel.php": (
            "<?php\n"
            "use Illuminate\\Console\\Scheduling\\Schedule;\n"
            "use Illuminate\\Foundation\\Console\\Kernel as ConsoleKernel;\n"
            "class Kernel extends ConsoleKernel {\n"
            "    protected function schedule(Schedule $schedule): void {\n"
            "        $schedule->command(\"orders:$name\")->daily();\n"
            "    }\n"
            "}\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="php") for path in sources}, sources
    )

    assert [
        (scheduler.file_path, scheduler.invoked_targets, scheduler.cron)
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "laravel_schedule"
    ] == [("app/Console/StaticKernel.php", ["orders:sync"], "daily")]


def test_php_canonical_scheduled_job_target_links_its_endpoint() -> None:
    """Laravel job scheduling preserves the parser-proven FQCN for linking."""
    job_path = "app/Jobs/SyncOrders.php"
    kernel_path = "app/Console/Kernel.php"
    controller_path = "app/Http/OrderController.php"
    sources = {
        job_path: (
            "<?php\n"
            "namespace App\\Jobs;\n"
            "use Illuminate\\Contracts\\Queue\\ShouldQueue;\n"
            "class SyncOrders implements ShouldQueue {}\n"
        ),
        kernel_path: (
            "<?php\n"
            "namespace App\\Console;\n"
            "use App\\Jobs\\SyncOrders;\n"
            "use Illuminate\\Console\\Scheduling\\Schedule;\n"
            "use Illuminate\\Foundation\\Console\\Kernel as ConsoleKernel;\n"
            "class Kernel extends ConsoleKernel {\n"
            "    protected function schedule(Schedule $schedule): void {\n"
            "        $schedule->job(new SyncOrders())->daily();\n"
            "    }\n"
            "}\n"
        ),
        controller_path: (
            "<?php\n"
            "namespace App\\Http;\n"
            "use App\\Jobs\\SyncOrders;\n"
            "dispatch(new SyncOrders());\n"
        ),
    }
    parsed = {
        path: _parsed_file(path, language="php") for path in sources
    }
    runtime = discover_runtime_surfaces(
        parsed,
        sources,
        api_endpoints=[
            {
                "method": "POST",
                "path": "/orders/sync",
                "file": controller_path,
                "handler_file": controller_path,
                "route_file": controller_path,
            }
        ],
    )
    scheduler = next(
        item
        for item in runtime.schedulers
        if item.scheduler_type == "laravel_schedule"
    )

    assert scheduler.invoked_targets == [r"App\Jobs\SyncOrders"]
    assert scheduler.linked_endpoints == ["POST /orders/sync"]
    assert runtime.scan_stats["link_scheduler_checks"] == 1


def test_php_listener_path_and_handle_without_laravel_role_create_no_listener() -> None:
    """Directory conventions and a method spelling are not Laravel evidence."""
    path = "app/Listeners/Fake.php"
    source = "<?php\nclass Fake { public function handle(Event $event) {} }\n"
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="php")}, {path: source}
    )

    assert [task for task in runtime.tasks if task.runtime_kind == "laravel_listener"] == []


def test_php_event_path_without_role_proof_creates_no_event() -> None:
    """A class in an Events directory is not itself Laravel event evidence."""
    path = "app/Events/Fake.php"
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="php")},
        {path: "<?php\nclass Fake {}\n"},
    )

    assert [task for task in runtime.tasks if task.runtime_kind == "laravel_event"] == []


def test_laravel_comments_strings_and_invalid_php_never_create_runtime_surfaces() -> None:
    """Laravel facts require complete PHP syntax nodes, never raw source text."""
    sources = {
        "app/Jobs/comment.php": "<?php\n// class CommentJob implements ShouldQueue\n",
        "app/Jobs/string.php": (
            "<?php\n$example = 'class StringJob implements ShouldQueue';\n"
        ),
        "app/Jobs/broken.php": "<?php\nclass BrokenJob implements ShouldQueue {\n",
        "app/Console/Kernel.php": (
            "<?php\n// $schedule->command('fake:run')->daily();\n"
        ),
    }
    parsed = {
        path: _parsed_file(path, language="php") for path in sources
    }

    runtime = discover_runtime_surfaces(
        parsed,
        sources,
        api_endpoints=[
            {"method": "POST", "path": "/fake", "file": "app/Console/Kernel.php"}
        ],
    )

    assert [task for task in runtime.tasks if task.runtime_kind.startswith("laravel_")] == []
    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "laravel_schedule"
    ] == []


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
            "package main\n\n"
            "import (\n"
            "    \"time\"\n"
            "    cron \"github.com/robfig/cron/v3\"\n"
            "    gocron \"github.com/go-co-op/gocron\"\n"
            ")\n\n"
            "func syncLoop() {}\nfunc cleanup() {}\n\n"
            "func main() {\n"
            "    c := cron.New()\n"
            "    scheduler := gocron.NewScheduler(time.UTC)\n"
            "    go syncLoop()\n"
            "    c.AddFunc(\"@every 5m\", cleanup)\n"
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


def test_go_comments_strings_and_invalid_syntax_never_create_runtime_surfaces() -> None:
    """Go runtime facts require complete Go AST nodes, never source text markers."""
    path = "cmd/worker/main.go"
    source = (
        "package main\n\n"
        "// go forgedComment()\n"
        'var prompt = "go forgedString()"\n'
        "func broken( {\n"
    )
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="go")}, {path: source}
    )

    assert [task for task in runtime.tasks if task.runtime_kind == "go_worker"] == []
    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type in {"go_cron", "go_schedule"}
    ] == []


def test_go_generic_scheduler_method_names_create_no_runtime_surfaces() -> None:
    """Local APIs named `AddFunc`/`Every().Do()` are not scheduler proof."""
    path = "internal/faux.go"
    source = (
        "package internal\n\n"
        "type Faux struct{}\n"
        "func (Faux) AddFunc(string, func()) {}\n"
        "func (Faux) Every(int) Faux { return Faux{} }\n"
        "func (Faux) Do(func()) {}\n"
        "func task() {}\n"
        "func boot() {\n"
        "    var fake Faux\n"
        "    fake.AddFunc(\"* * * * *\", task)\n"
        "    fake.Every(5).Do(task)\n"
        "}\n"
    )
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="go")}, {path: source}
    )

    assert [task for task in runtime.tasks if task.runtime_kind == "go_worker"] == []
    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type in {"go_cron", "go_schedule"}
    ] == []


def test_go_shadowed_or_reassigned_scheduler_bindings_create_no_facts() -> None:
    """A local import shadow or later receiver write revokes scheduler proof."""
    sources = {
        "internal/shadow.go": (
            "package internal\n"
            "import cron \"github.com/robfig/cron/v3\"\n"
            "type Faux struct{}\n"
            "func (Faux) AddFunc(string, func()) {}\n"
            "func task() {}\n"
            "func boot() {\n"
            "    cron := Faux{}\n"
            "    cron.AddFunc(\"@every 1m\", task)\n"
            "}\n"
        ),
        "internal/reassigned.go": (
            "package internal\n"
            "import cron \"github.com/robfig/cron/v3\"\n"
            "type Scheduler interface { AddFunc(string, func()) }\n"
            "type Faux struct{}\n"
            "func (Faux) AddFunc(string, func()) {}\n"
            "func task() {}\n"
            "func boot() {\n"
            "    var c Scheduler = cron.New()\n"
            "    c = Faux{}\n"
            "    c.AddFunc(\"@every 1m\", task)\n"
            "}\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="go") for path in sources}, sources
    )

    assert [task for task in runtime.tasks if task.runtime_kind == "go_worker"] == []
    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type in {"go_cron", "go_schedule"}
    ] == []


def test_go_inner_block_scheduler_binding_cannot_escape_its_scope() -> None:
    """A scheduler receiver declared in an inner block is undefined outside it."""
    path = "internal/escaped_scope.go"
    source = (
        "package internal\n"
        "import cron \"github.com/robfig/cron/v3\"\n"
        "func task() {}\n"
        "func boot() {\n"
        "    { c := cron.New(); _ = c }\n"
        "    c.AddFunc(\"@every 1m\", task)\n"
        "}\n"
    )
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="go")}, {path: source}
    )

    assert [task for task in runtime.tasks if task.runtime_kind == "go_worker"] == []
    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type in {"go_cron", "go_schedule"}
    ] == []


def test_go_nested_assignment_revokes_outer_scheduler_receiver() -> None:
    """An ordinary nested assignment mutates, rather than shadows, an outer receiver."""
    sources = {
        "internal/block_assignment.go": (
            "package internal\n"
            "import cron \"github.com/robfig/cron/v3\"\n"
            "type Scheduler interface { AddFunc(string, func()) }\n"
            "type Faux struct{}\n"
            "func (Faux) AddFunc(string, func()) {}\n"
            "func task() {}\n"
            "func boot() {\n"
            "    var c Scheduler = cron.New()\n"
            "    { c = Faux{} }\n"
            "    c.AddFunc(\"@every 1m\", task)\n"
            "}\n"
        ),
        "internal/closure_assignment.go": (
            "package internal\n"
            "import cron \"github.com/robfig/cron/v3\"\n"
            "type Scheduler interface { AddFunc(string, func()) }\n"
            "type Faux struct{}\n"
            "func (Faux) AddFunc(string, func()) {}\n"
            "func task() {}\n"
            "func boot() {\n"
            "    var c Scheduler = cron.New()\n"
            "    func() { c = Faux{} }()\n"
            "    c.AddFunc(\"@every 1m\", task)\n"
            "}\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="go") for path in sources}, sources
    )

    assert [task for task in runtime.tasks if task.runtime_kind == "go_worker"] == []
    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type in {"go_cron", "go_schedule"}
    ] == []


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


def test_uninvoked_broker_function_cannot_create_worker() -> None:
    """An uninvoked exported broker function is not runtime execution evidence."""
    path = "src/jobs/orderChannel.ts"
    content = (
        'import amqplib from "amqplib";\n'
        "export async function boot() {\n"
        "    const channel = await (await amqplib.connect(url)).createChannel();\n"
        '    channel.consume("orders-sync", handleOrder);\n'
        "}\n"
        "export function drain(channel: LocalChannel) {\n"
        '    channel.consume("not-a-broker-queue", noop);\n'
        "}\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: content})

    assert [
        task.name for task in runtime.tasks if task.runtime_kind == "js_worker"
    ] == []


def test_js_short_circuit_rhs_cannot_create_runtime_evidence() -> None:
    """Lazy RHS calls and constructors are not module-initialization evidence."""
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/short.js": (
            "const { Queue, Worker } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "const trustedQueue = new Queue('orders');\n"
            "let conditionalQueue;\n"
            "false && queue.add('job', {});\n"
            "true || new Worker('or-never', handle);\n"
            "value ?? new Worker('nullish-never', handle);\n"
            "value ?? (conditionalQueue = trustedQueue);\n"
            "conditionalQueue.add('lazy-alias-job', {});\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="javascript") for path in sources}, sources
    )

    assert runtime.dispatch_evidence == []
    assert [
        task.name
        for task in runtime.tasks
        if task.runtime_kind == "js_worker" and task.file_path == "producers/short.js"
    ] == []
    worker = next(task for task in runtime.tasks if task.file_path == "workers/orders.js")
    assert worker.producer_files == []


def test_js_computed_or_aliased_object_assign_taints_queue_receiver() -> None:
    """Static Object.assign spellings cannot leave a mutated queue trusted."""
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/computed.js": (
            "const { Queue } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "Object['assign'](queue, { add: fakeAdd });\n"
            "queue.add('job', {});\n"
        ),
        "producers/alias.js": (
            "const { Queue } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "const merge = Object.assign;\n"
            "merge(queue, { add: fakeAdd });\n"
            "queue.add('job', {});\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="javascript") for path in sources}, sources
    )

    assert runtime.dispatch_evidence == []
    worker = next(task for task in runtime.tasks if task.file_path == "workers/orders.js")
    assert worker.producer_files == []


def test_js_destructured_or_transitive_object_assign_alias_taints_queue() -> None:
    """Static Object.assign aliases remain tainted through destructuring and copies."""
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/destructured.js": (
            "const { Queue } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "const { assign: merge } = Object;\n"
            "merge(queue, { add: fakeAdd });\n"
            "queue.add('forged-destructure', {});\n"
        ),
        "producers/transitive.js": (
            "const { Queue } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "const merge = Object.assign;\n"
            "const mergeAgain = merge;\n"
            "mergeAgain(queue, { add: fakeAdd });\n"
            "queue.add('forged-transitive', {});\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="javascript") for path in sources}, sources
    )

    assert runtime.dispatch_evidence == []
    worker = next(task for task in runtime.tasks if task.file_path == "workers/orders.js")
    assert worker.producer_files == []


def test_js_nested_direct_eval_revokes_later_outer_queue_proof() -> None:
    """An invoked nested direct eval can mutate a captured queue receiver."""
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/eval.js": (
            "const { Queue } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "function poison() { eval('queue.add = fakeAdd'); }\n"
            "poison();\n"
            "queue.add('job', {});\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="javascript") for path in sources}, sources
    )

    assert runtime.dispatch_evidence == []
    worker = next(task for task in runtime.tasks if task.file_path == "workers/orders.js")
    assert worker.producer_files == []


def test_js_hoisted_direct_eval_revokes_later_outer_queue_proof() -> None:
    """A called function declaration executes before its later textual eval body."""
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/hoisted-eval.js": (
            "const { Queue } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "poison();\n"
            "queue.add('forged', {});\n"
            "function poison() { eval('queue.add = fakeAdd'); }\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="javascript") for path in sources}, sources
    )

    assert runtime.dispatch_evidence == []
    worker = next(task for task in runtime.tasks if task.file_path == "workers/orders.js")
    assert worker.producer_files == []


def test_typescript_import_equals_requires_prior_source_position() -> None:
    """`import = require` executes in source order, not as an ESM-hoisted binding."""
    sources = {
        "schedules/before.ts": (
            "cron.schedule('* * * * *', beforeJob);\n"
            "import cron = require('node-cron');\n"
        ),
        "schedules/after.ts": (
            "import cron = require('node-cron');\n"
            "cron.schedule('* * * * *', afterJob);\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path, language="typescript") for path in sources}, sources
    )

    assert [(item.file_path, item.scheduler_type) for item in runtime.schedulers] == [
        ("schedules/after.ts", "node_cron")
    ]


def test_uninvoked_exported_initializer_cannot_bind_an_outer_queue() -> None:
    """Export/await syntax does not prove a nested initializer ever ran."""
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/never.js": (
            "import { Queue } from 'bullmq';\n"
            "let queue;\n"
            "export async function neverCalled() {\n"
            "  queue = await new Queue('orders');\n"
            "}\n"
            "queue.add('not-an-orders-job', {});\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)

    assert runtime.dispatch_evidence == []
    worker = next(task for task in runtime.tasks if task.file_path == "workers/orders.js")
    assert worker.producer_files == []


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


def test_vue_nonexecutable_script_type_never_creates_runtime_evidence() -> None:
    """A data/plain-text SFC script is not executable JavaScript."""
    path = "src/components/DataOnly.vue"
    content = (
        '<script type="text/plain">\n'
        "const { Worker } = require('bullmq');\n"
        "new Worker('fake-worker', handleFake);\n"
        "</script>\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None and parsed.language == "vue"

    runtime = discover_runtime_surfaces({path: parsed}, {path: content})

    assert [task for task in runtime.tasks if task.runtime_kind == "js_worker"] == []


def test_vue_data_lang_cannot_authenticate_nonexecutable_typescript() -> None:
    """Only the exact SFC `lang` attribute changes an inline script grammar."""
    path = "src/components/DataLangOnly.vue"
    content = (
        '<script data-lang="ts">\n'
        'import { Worker } from "bullmq";\n'
        "const marker: number = 1;\n"
        'new Worker("fake-worker", handleFake);\n'
        "</script>\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None and parsed.language == "vue"

    runtime = discover_runtime_surfaces({path: parsed}, {path: content})

    assert [task for task in runtime.tasks if task.runtime_kind == "js_worker"] == []


def test_vue_runtime_scans_every_top_level_executable_script_block() -> None:
    """A valid normal script and script setup both contribute runtime evidence."""
    path = "src/components/JobsPanel.vue"
    content = (
        "<script>\n"
        "const { Worker } = require('bullmq');\n"
        "new Worker('normal-worker', handleNormal);\n"
        "</script>\n"
        "<script setup>\n"
        "const { Worker } = require('bullmq');\n"
        "new Worker('setup-worker', handleSetup);\n"
        "</script>\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None and parsed.language == "vue"

    runtime = discover_runtime_surfaces({path: parsed}, {path: content})

    assert [
        task.name for task in runtime.tasks if task.runtime_kind == "js_worker"
    ] == ["normal-worker", "setup-worker"]


def test_vue_invalid_executable_companion_script_revokes_all_runtime_evidence() -> None:
    """A Vue SFC with any invalid executable script cannot execute either block."""
    path = "src/components/InvalidJobs.vue"
    content = (
        "<script>\n"
        "const { Worker } = require('bullmq');\n"
        "new Worker('orders', handleOrders);\n"
        "</script>\n"
        "<script setup lang='ts'>\n"
        "const broken = ;\n"
        "</script>\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None and parsed.language == "vue"

    runtime = discover_runtime_surfaces({path: parsed}, {path: content})

    assert [task for task in runtime.tasks if task.runtime_kind == "js_worker"] == []


def test_commented_vue_script_never_creates_runtime_evidence() -> None:
    """A literal `<script>` inside an HTML comment is not an SFC script block."""
    path = "src/components/Comment.vue"
    content = (
        "<template><!-- <script>\n"
        "const Queue = require('bullmq').Queue;\n"
        "const queue = new Queue('fake');\n"
        "queue.add('job', {});\n"
        "</script> --></template>\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None and parsed.language == "vue"

    runtime = discover_runtime_surfaces({path: parsed}, {path: content})

    assert runtime.dispatch_evidence == []


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
            "from celery import current_app as app\n"
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

    def __contains__(self, other: str) -> bool:
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

    # Doubling the task count must not scale the per-file probing with it. A
    # parser-only implementation may remove those raw string probes entirely;
    # when the baseline is zero, the larger corpus must stay zero too.
    if probes_small == 0:
        assert probes_large == 0, (probes_small, probes_large)
    else:
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
        "app/Listeners/OrderListener.php": "php",
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
        "app/Listeners/OrderListener.php": (
            "<?php\n"
            "use Illuminate\\Contracts\\Queue\\ShouldQueue;\n"
            "class OrderListener implements ShouldQueue\n{\n"
            "    public function handle(OrderShipped $event) {}\n"
            "}\n"
        ),
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
            {
                "producer.py": (
                    "from django.db.models.signals import post_save\n"
                    "post_save.send(sender=Order)\n"
                )
            },
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
        target_identities=(r"App\Jobs\SyncOrders",),
    )
    evidence = _collect_dispatch_evidence(
        {"app/Http/OrderController.php": "<?php\ndispatch(new App\\Jobs\\SyncOrders($order));\n"},
        {"app/Http/OrderController.php": "php"},
    )
    _link_runtime_evidence(RuntimeScan(tasks=[task]), evidence, [])
    assert task.producer_files == ["app/Http/OrderController.php"]


def test_php_same_file_duplicate_short_names_keep_distinct_canonical_tasks() -> None:
    """Laravel task dedupe must never collapse parser-proven FQCN identities."""
    task_path = "app/Jobs/MultipleSends.php"
    producer_path = "app/Http/SendController.php"
    sources = {
        task_path: (
            "<?php\n"
            "namespace App\\Jobs;\n"
            "use Illuminate\\Contracts\\Queue\\ShouldQueue;\n"
            "class Send implements ShouldQueue {}\n"
            "namespace Billing\\Events;\n"
            "use Illuminate\\Contracts\\Queue\\ShouldQueue;\n"
            "class Send implements ShouldQueue {}\n"
        ),
        producer_path: "<?php\n\\Billing\\Events\\Send::dispatch($event);\n",
    }
    parsed = {
        task_path: _parsed_file(task_path, language="php"),
        producer_path: _parsed_file(producer_path, language="php"),
    }

    runtime = discover_runtime_surfaces(parsed, sources)
    jobs = [task for task in runtime.tasks if task.runtime_kind == "laravel_job"]
    by_identity = {task.target_identities[0]: task for task in jobs}

    assert sorted(by_identity) == [r"App\Jobs\Send", r"Billing\Events\Send"]
    assert by_identity[r"App\Jobs\Send"].producer_files == []
    assert by_identity[r"Billing\Events\Send"].producer_files == [producer_path]


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
    file_contents[producer_path] = (
        "from .tasks import task_7\n\n"
        "task_7.delay(payload)\n"
    )
    languages[producer_path] = "python"

    evidence = _collect_dispatch_evidence(
        file_contents,
        languages,
        {"src/jobs/tasks.py": {"task_7"}},
    )
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
        "from .tasks import sync\n"
        "from django.db.models.signals import post_save\n"
        "sync . delay(payload)\n"
        "post_save . send(sender=Order)\n"
    )

    evidence = _collect_dispatch_evidence(
        {path: source},
        {path: "python"},
        {"handlers/tasks.py": {"sync"}},
    )

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
                target_identities=(r"App\Jobs\SyncOrders",),
            ),
            RuntimeTask(
                name="OrderShipped",
                file_path="app/Events/OrderShipped.php",
                runtime_kind="laravel_event",
                target_identities=(r"App\Events\OrderShipped",),
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
        target_identities=(r"App\Jobs\SyncOrders",),
    )
    actual = RuntimeTask(
        name="ExportJob",
        file_path="app/Other/ExportJob.php",
        runtime_kind="laravel_job",
        target_identities=(r"App\Other\ExportJob",),
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
        target_identities=(r"App\Jobs\SyncOrders",),
    )

    evidence = _collect_dispatch_evidence({path: source}, {path: "php"})
    _link_runtime_evidence(RuntimeScan(tasks=[task]), evidence, [])

    assert evidence[0].target_aliases == (r"App\Jobs\SyncOrders", "SyncOrders")
    assert task.producer_files == [path]


def test_php_dispatch_class_aliases_are_case_insensitive() -> None:
    """PHP class imports resolve regardless of the call site's alias casing."""
    source = """<?php
use App\\Jobs\\ActualJob as JobAlias;
dispatch(new jobalias());
"""

    assert [item.target for item in php_dispatches(source)] == [
        r"App\Jobs\ActualJob"
    ]


def test_php_static_dispatch_and_global_helper_preserve_valid_case_forms() -> None:
    """PHP static methods are case-insensitive and global helpers may be rooted."""
    static_source = """<?php
namespace App\\Jobs;
Real::DISPATCH($payload);
"""
    global_source = """<?php
\\dispatch(new \\App\\Jobs\\Real($payload));
"""

    assert [item.target for item in php_dispatches(static_source)] == [
        r"App\Jobs\Real"
    ]
    assert [item.target for item in php_dispatches(global_source)] == [
        r"App\Jobs\Real"
    ]


def test_php_shadowed_laravel_helpers_never_emit_dispatch_evidence() -> None:
    """Imported or local helper names must not impersonate Laravel dispatch APIs."""
    imported = """<?php
use function Vendor\\Helpers\\dispatch;
dispatch(new \\App\\Jobs\\Real());
"""
    local = """<?php
function event($value) {}
event(new \\App\\Events\\Real());
"""

    assert php_dispatches(imported) == ()
    assert php_dispatches(local) == ()


def test_php_dispatch_aliases_are_namespace_scoped() -> None:
    """The same local PHP alias may resolve differently in separate namespaces."""
    source = """<?php
namespace A {
    use App\\One\\First as Job;
    dispatch(new Job());
}
namespace B {
    use App\\Two\\Second as Job;
    dispatch(new Job());
}
"""

    assert [item.target for item in php_dispatches(source)] == [
        r"App\One\First",
        r"App\Two\Second",
    ]


def test_php_dispatch_aliases_are_semicolon_namespace_scoped() -> None:
    """Semicolon namespaces own aliases until the next namespace declaration."""
    source = """<?php
namespace A;
use App\\One\\First as Job;
dispatch(new Job());
namespace B;
use App\\Two\\Second as Job;
dispatch(new Job());
"""

    assert [item.target for item in php_dispatches(source)] == [
        r"App\One\First",
        r"App\Two\Second",
    ]


def test_php_static_dispatch_requires_a_canonical_discovered_runtime_identity() -> None:
    """A local static method cannot impersonate a Laravel job by short name."""
    sources = {
        "app/Jobs/Real.php": """<?php
namespace App\\Jobs;
use Illuminate\\Contracts\\Queue\\ShouldQueue;
class Real implements ShouldQueue {}
""",
        "app/Http/Controller.php": """<?php
namespace App\\Http;
class Real { public static function dispatch($payload) {} }
Real::dispatch($payload);
""",
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)
    task = next(item for item in runtime.tasks if item.file_path == "app/Jobs/Real.php")

    assert runtime.dispatch_evidence == []
    assert task.producer_files == []


def test_php_canonical_identity_links_one_of_duplicate_short_names() -> None:
    """A proven FQCN wins even when unrelated Laravel tasks share its short name."""
    first = RuntimeTask(
        name="Send",
        file_path="app/Jobs/Send.php",
        runtime_kind="laravel_job",
        target_identities=(r"App\Jobs\Send",),
    )
    second = RuntimeTask(
        name="Send",
        file_path="app/Billing/Jobs/Send.php",
        runtime_kind="laravel_job",
        target_identities=(r"Billing\Jobs\Send",),
    )
    runtime = RuntimeScan(tasks=[first, second])
    evidence = [
        DispatchEvidence(
            file_path="app/Http/SendController.php",
            language="php",
            relation="direct",
            target_aliases=(r"App\Jobs\Send", "Send"),
        )
    ]

    _link_runtime_evidence(runtime, evidence, [])

    assert first.producer_files == ["app/Http/SendController.php"]
    assert second.producer_files == []


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
        target_identities=(r"App\Jobs\SyncOrders",),
    )
    actual = RuntimeTask(
        name="ExportJob",
        file_path="app/Other/ExportJob.php",
        runtime_kind="laravel_job",
        target_identities=(r"App\Other\ExportJob",),
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


def test_signal_dispatch_rejects_overbound_handler_fanout() -> None:
    """A signal broadcast above the retained fanout cap fails closed as a whole."""
    handlers = [
        RuntimeTask(
            name=f"handler_{index}",
            file_path=f"handlers/{index}.py",
            runtime_kind="django_signal",
            triggers=["post_save"],
        )
        for index in range(33)
    ]
    runtime = RuntimeScan(tasks=handlers)
    evidence = [
        DispatchEvidence(
            file_path="orders/api.py",
            language="python",
            relation="signal",
            target_aliases=("post_save",),
        )
    ]

    _link_runtime_evidence(runtime, evidence, [])

    assert all(task.producer_files == [] for task in handlers)
    assert runtime.scan_stats["link_signal_broadcast_edges"] == 0
    assert runtime.scan_stats["link_signal_fanout_rejections"] == 1
    assert runtime.scan_stats["link_index_probes"] == 1


def test_runtime_links_retain_bounded_unique_producers_and_endpoints() -> None:
    """Planner-facing runtime relationship lists have fixed, deterministic caps."""
    task = RuntimeTask(
        name="sync",
        file_path="workers/sync.py",
        runtime_kind="celery",
    )
    runtime = RuntimeScan(tasks=[task])
    evidence = [
        DispatchEvidence(
            file_path=f"api/{index}.py",
            language="python",
            relation="direct",
            target_aliases=("sync",),
        )
        for index in range(65)
    ]
    endpoints = [
        {
            "method": "POST",
            "path": f"/sync/{index}",
            "file": f"api/{index}.py",
        }
        for index in range(65)
    ]

    _link_runtime_evidence(runtime, evidence, endpoints)

    assert len(task.producer_files) == 64
    assert len(task.linked_endpoints) == 64
    assert len(set(task.producer_files)) == 64
    assert len(set(task.linked_endpoints)) == 64
    assert runtime.scan_stats["link_producer_cap_rejections"] == 1
    assert runtime.scan_stats["link_endpoint_cap_rejections"] == 1


def test_endpoint_attachment_bounds_work_for_endpoint_heavy_files(monkeypatch) -> None:
    """Endpoint caps bound attachment work, not merely the stored output list."""
    sorted_input_sizes: list[int] = []
    original_sorted = sorted

    def counted_sorted(values, *args, **kwargs):
        items = list(values)
        sorted_input_sizes.append(len(items))
        return original_sorted(items, *args, **kwargs)

    monkeypatch.setattr(runtime_parser, "sorted", counted_sorted, raising=False)
    endpoint_count = 256
    file_path = "api/orders.py"
    task = RuntimeTask(
        name="sync",
        file_path="workers/sync.py",
        runtime_kind="celery",
    )
    runtime = RuntimeScan(tasks=[task])
    evidence = [
        DispatchEvidence(
            file_path=file_path,
            language="python",
            relation="direct",
            target_aliases=("sync",),
        )
        for _ in range(endpoint_count)
    ]
    endpoints = [
        {"method": "POST", "path": f"/orders/{index}", "file": file_path}
        for index in range(endpoint_count)
    ]

    _link_runtime_evidence(runtime, evidence, endpoints)

    assert len(task.linked_endpoints) == 64
    assert max(sorted_input_sizes) <= 64
    assert runtime.scan_stats["link_endpoint_cap_rejections"] == endpoint_count - 64


def test_repeated_endpoint_evidence_counts_downstream_cap_once_per_source_batch() -> None:
    """Repeated evidence cannot multiply one destination/source cap rejection."""
    task = RuntimeTask(
        name="sync",
        file_path="workers/sync.py",
        runtime_kind="celery",
    )
    runtime = RuntimeScan(tasks=[task])
    first_file = "api/first.py"
    repeated_file = "api/repeated.py"
    evidence = [
        DispatchEvidence(
            file_path=first_file,
            language="python",
            relation="direct",
            target_aliases=("sync",),
        )
    ] + [
        DispatchEvidence(
            file_path=repeated_file,
            language="python",
            relation="direct",
            target_aliases=("sync",),
        )
        for _ in range(256)
    ]
    endpoints = [
        {"method": "POST", "path": f"/first/{index}", "file": first_file}
        for index in range(64)
    ] + [
        {"method": "POST", "path": f"/repeated/{index}", "file": repeated_file}
        for index in range(256)
    ]

    _link_runtime_evidence(runtime, evidence, endpoints)

    assert len(task.linked_endpoints) == 64
    assert runtime.scan_stats["link_endpoint_cap_rejections"] == 256


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


def test_duplicate_scheduler_declarations_keep_their_own_source_endpoint() -> None:
    """Distinct same-name beat declarations receive their own owner evidence."""
    path = "orders/schedules.py"
    content = (
        "from celery import current_app as app\n"
        "from celery.schedules import crontab\n"
        "app.conf.beat_schedule = {\n"
        "    'early-sync': {\n"
        "        'task': 'orders.tasks.sync',\n"
        "        'schedule': crontab(hour='1'),\n"
        "    },\n"
        "    'late-sync': {\n"
        "        'task': 'orders.tasks.sync',\n"
        "        'schedule': crontab(hour='2'),\n"
        "    },\n"
        "}\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None

    runtime = discover_runtime_surfaces(
        {path: parsed},
        {path: content},
        api_endpoints=[
            {
                "method": "POST",
                "path": "/orders/reconcile",
                "file": path,
            }
        ],
    )
    schedulers = [
        item for item in runtime.schedulers if item.scheduler_type == "beat"
    ]

    assert len(schedulers) == 2
    assert all(
        item.linked_endpoints == ["POST /orders/reconcile"]
        for item in schedulers
    )


def test_generated_scheduler_owner_keys_do_not_collide_with_legacy_names() -> None:
    """Generated declaration identities occupy a namespace separate from names."""
    path = "orders/schedules.py"
    colliding_name = "owner:beat|sync|cron-2|sync|1"
    first = RuntimeScheduler(
        name=colliding_name,
        file_path=path,
        scheduler_type="beat",
        cron="cron-1",
        invoked_targets=["sync"],
    )
    second = RuntimeScheduler(
        name="sync",
        file_path=path,
        scheduler_type="beat",
        cron="cron-2",
        invoked_targets=["sync"],
    )
    runtime = RuntimeScan(schedulers=[first, second])
    evidence = runtime_parser._scheduler_owner_evidence(runtime.schedulers)

    _link_runtime_evidence(
        runtime,
        evidence,
        [{"method": "POST", "path": "/orders/reconcile", "file": path}],
    )

    assert first.linked_endpoints == ["POST /orders/reconcile"]
    assert second.linked_endpoints == ["POST /orders/reconcile"]


def test_runtime_scan_links_only_structural_dispatch_evidence() -> None:
    """Producer links come from real source grammar, never raw cross-language text."""
    files = {
        "workers/tasks.py": (
            "from celery import shared_task\n\n"
            "@shared_task\n"
            "def sync(order_id):\n"
            "    return order_id\n"
        ),
        "handlers/orders.py": (
            "from workers.tasks import sync\n\n"
            "sync . delay(order_id)\n"
        ),
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


def test_python_runtime_discovery_requires_framework_bound_ast_declarations() -> None:
    """Raw decorator/connect text and malformed Python cannot create runtime facts."""
    sources = {
        "workers/faux.py": (
            "@faux.task\n"
            "def unrelated(value):\n"
            "    return value\n"
            "unrelated.delay(value)\n"
        ),
        "workers/quoted.py": (
            'example = """\n'
            "@shared_task\n"
            "def ghost(value):\n"
            "    return value\n"
            '"""\n'
        ),
        "workers/broken.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def broken(\n"
        ),
        "signals/generic.py": "socket.connect(callback)\n",
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)

    assert runtime.tasks == []
    assert runtime.dispatch_evidence == []


def test_python_channels_comments_strings_and_invalid_source_create_no_consumers() -> None:
    """Channels consumers require a valid AST and a bound framework base class."""
    sources = {
        "realtime/comment.py": "# class CommentGhost(AsyncWebsocketConsumer):\n",
        "realtime/string.py": 'example = "class StringGhost(WebsocketConsumer):"\n',
        "realtime/broken.py": "class BrokenGhost(WebsocketConsumer):\n",
        "realtime/faux.py": "class Faux(AsyncWebsocketConsumer):\n    pass\n",
    }
    parsed = {path: _parsed_file(path) for path in sources}

    runtime = discover_runtime_surfaces(parsed, sources)

    assert runtime.realtime_consumers == []


def test_python_only_the_decorated_same_name_declaration_authenticates_delay() -> None:
    """Task proof follows the exact AST declaration, not a name-wide set."""
    path = "orders/tasks.py"
    source = (
        "from celery import shared_task\n"
        "def actual():\n"
        "    return None\n"
        "actual.delay()\n"
        "@shared_task\n"
        "def actual():\n"
        "    return None\n"
        "actual.delay()\n"
        "def actual():\n"
        "    return None\n"
        "actual.delay()\n"
    )
    parsed = parse_file(Path(path), source)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: source})

    assert [(item.file_path, item.target_aliases) for item in runtime.dispatch_evidence] == [
        (path, ("actual",))
    ]


def test_python_exception_and_match_captures_revoke_imported_task_proof() -> None:
    """Post-scope captures cannot retain an imported task binding."""
    sources = {
        "pkg/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual():\n"
            "    pass\n"
        ),
        "pkg/except_api.py": (
            "from .tasks import actual\n"
            "try:\n"
            "    raise RuntimeError()\n"
            "except RuntimeError as actual:\n"
            "    pass\n"
            "actual.delay()\n"
        ),
        "pkg/match_api.py": (
            "from .tasks import actual\n"
            "subject = object()\n"
            "match subject:\n"
            "    case actual:\n"
            "        pass\n"
            "actual.delay()\n"
        ),
    }
    parsed = {path: _parsed_file(path) for path in sources}
    runtime = discover_runtime_surfaces(parsed, sources)

    assert runtime.dispatch_evidence == []


def test_python_function_exception_and_match_captures_shadow_imported_task() -> None:
    """Function-local captures cannot authenticate an imported task receiver."""
    sources = {
        "pkg/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual():\n"
            "    pass\n"
        ),
        "pkg/except_api.py": (
            "from .tasks import actual\n"
            "def run():\n"
            "    try:\n"
            "        raise RuntimeError()\n"
            "    except RuntimeError as actual:\n"
            "        pass\n"
            "    actual.delay()\n"
        ),
        "pkg/match_api.py": (
            "from .tasks import actual\n"
            "def run(subject):\n"
            "    match subject:\n"
            "        case actual:\n"
            "            pass\n"
            "    actual.delay()\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path) for path in sources}, sources
    )

    assert runtime.dispatch_evidence == []


def test_python_task_receiver_mutation_or_globals_rebind_revokes_dispatch_proof() -> None:
    """Task receiver authority cannot survive direct or reflective mutation."""
    sources = {
        "pkg/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual():\n"
            "    pass\n"
        ),
        "pkg/local_api.py": (
            "from .tasks import actual\n"
            "def run():\n"
            "    actual.delay = lambda *args: None\n"
            "    actual.delay()\n"
        ),
        "pkg/global_api.py": (
            "from .tasks import actual\n"
            "globals()['actual'] = object()\n"
            "actual.delay()\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path) for path in sources}, sources
    )

    assert runtime.dispatch_evidence == []


def test_python_dispatch_before_later_receiver_mutation_remains_evidence() -> None:
    """Later reflective/member mutation cannot erase an already-run dispatch."""
    sources = {
        "pkg/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual():\n"
            "    pass\n"
        ),
        "pkg/member_api.py": (
            "from .tasks import actual\n"
            "actual.delay()\n"
            "actual.delay = lambda *args: None\n"
        ),
        "pkg/global_api.py": (
            "from .tasks import actual\n"
            "actual.delay()\n"
            "globals()['actual'] = object()\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path) for path in sources}, sources
    )

    assert [(item.file_path, item.target_aliases) for item in runtime.dispatch_evidence] == [
        ("pkg/member_api.py", ("actual",)),
        ("pkg/global_api.py", ("actual",)),
    ]


def test_python_framework_member_writes_revoke_celery_and_signal_proof() -> None:
    """Mutated framework APIs cannot authenticate decorators or `.connect()` calls."""
    sources = {
        "workers/faux.py": (
            "import celery\n"
            "celery.shared_task = fake_decorator\n"
            "@celery.shared_task\n"
            "def ghost():\n"
            "    return None\n"
        ),
        "signals/faux.py": (
            "from django.db.models.signals import post_save\n"
            "post_save.connect = fake_connect\n"
            "post_save.connect(handler)\n"
        ),
    }
    parsed = {path: _parsed_file(path) for path in sources}

    runtime = discover_runtime_surfaces(parsed, sources)

    assert [task for task in runtime.tasks if task.name in {"ghost", "handler"}] == []


def test_python_literal_setattr_revokes_celery_decorator_proof() -> None:
    """A literal reflective mutation cannot leave `celery.shared_task` trusted."""
    path = "workers/faux.py"
    source = (
        "import celery\n"
        "setattr(celery, 'shared_task', lambda fn: fn)\n"
        "@celery.shared_task\n"
        "def forged():\n"
        "    return None\n"
    )
    runtime = discover_runtime_surfaces({path: _parsed_file(path)}, {path: source})

    assert [task for task in runtime.tasks if task.name == "forged"] == []


def test_python_dynamic_setattr_revokes_all_framework_runtime_proof() -> None:
    """Unknown reflective member writes invalidate their framework roots."""
    sources = {
        "workers/faux.py": (
            "import celery\n"
            "member = 'shared_task'\n"
            "setattr(celery, member, object())\n"
            "@celery.shared_task\n"
            "def forged():\n"
            "    return None\n"
        ),
        "signals/faux.py": (
            "from django.db.models import signals\n"
            "member = 'post_save'\n"
            "setattr(signals, member, object())\n"
            "def forged(*args):\n"
            "    return None\n"
            "signals.post_save.connect(forged)\n"
        ),
        "realtime/consumers.py": (
            "from channels.generic.websocket import AsyncWebsocketConsumer\n"
            "member = 'forged'\n"
            "setattr(AsyncWebsocketConsumer, member, object())\n"
            "class Forged(AsyncWebsocketConsumer):\n"
            "    pass\n"
        ),
        "schedules/faux.py": (
            "from celery.schedules import crontab\n"
            "member = '__call__'\n"
            "setattr(crontab, member, object())\n"
            "SCHEDULE = crontab(minute='*')\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path) for path in sources}, sources
    )

    assert [task for task in runtime.tasks if task.name == "forged"] == []
    assert runtime.realtime_consumers == []
    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "crontab"
    ] == []


def test_python_nested_dynamic_setattr_revokes_all_framework_runtime_proof() -> None:
    """A nested bare setattr still mutates its framework root."""
    sources = {
        "workers/faux.py": (
            "import celery\n"
            "def consume(value):\n"
            "    return None\n"
            "member = 'shared_task'\n"
            "consume(setattr(celery, member, object()))\n"
            "@celery.shared_task\n"
            "def forged():\n"
            "    return None\n"
        ),
        "signals/faux.py": (
            "from django.db.models import signals\n"
            "def consume(value):\n"
            "    return None\n"
            "member = 'post_save'\n"
            "consume(setattr(signals, member, object()))\n"
            "def forged(*args):\n"
            "    return None\n"
            "signals.post_save.connect(forged)\n"
        ),
        "realtime/consumers.py": (
            "from channels.generic.websocket import AsyncWebsocketConsumer\n"
            "def consume(value):\n"
            "    return None\n"
            "member = 'forged'\n"
            "consume(setattr(AsyncWebsocketConsumer, member, object()))\n"
            "class Forged(AsyncWebsocketConsumer):\n"
            "    pass\n"
        ),
        "schedules/faux.py": (
            "from celery.schedules import crontab\n"
            "def consume(value):\n"
            "    return None\n"
            "member = '__call__'\n"
            "consume(setattr(crontab, member, object()))\n"
            "SCHEDULE = crontab(minute='*')\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path) for path in sources}, sources
    )

    assert [task for task in runtime.tasks if task.name == "forged"] == []
    assert runtime.realtime_consumers == []
    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "crontab"
    ] == []


def test_python_assignment_wrapped_nested_setattr_revokes_framework_proof() -> None:
    """A nested setattr in an assignment RHS still executes and taints its root."""
    sources = {
        "workers/faux.py": (
            "import celery\n"
            "def consume(value):\n"
            "    return None\n"
            "member = 'shared_task'\n"
            "sink = consume(setattr(celery, member, object()))\n"
            "@celery.shared_task\n"
            "def forged():\n"
            "    return None\n"
        ),
        "signals/faux.py": (
            "from django.db.models import signals\n"
            "def consume(value):\n"
            "    return None\n"
            "member = 'post_save'\n"
            "sink = consume(setattr(signals, member, object()))\n"
            "def forged(*args):\n"
            "    return None\n"
            "signals.post_save.connect(forged)\n"
        ),
        "realtime/consumers.py": (
            "from channels.generic.websocket import AsyncWebsocketConsumer\n"
            "def consume(value):\n"
            "    return None\n"
            "member = 'forged'\n"
            "sink = consume(setattr(AsyncWebsocketConsumer, member, object()))\n"
            "class Forged(AsyncWebsocketConsumer):\n"
            "    pass\n"
        ),
        "schedules/faux.py": (
            "from celery.schedules import crontab\n"
            "def consume(value):\n"
            "    return None\n"
            "member = '__call__'\n"
            "sink = consume(setattr(crontab, member, object()))\n"
            "SCHEDULE = crontab(minute='*')\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path) for path in sources}, sources
    )

    assert [task for task in runtime.tasks if task.name == "forged"] == []
    assert runtime.realtime_consumers == []
    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "crontab"
    ] == []


def test_python_reflected_global_writes_revoke_all_framework_runtime_proof() -> None:
    """`setattr(globals(), ...)` replaces the named module binding it targets."""
    sources = {
        "workers/faux.py": (
            "import celery\n"
            "setattr(globals(), 'celery', object())\n"
            "@celery.shared_task\n"
            "def forged():\n"
            "    return None\n"
        ),
        "signals/faux.py": (
            "from django.db.models import signals\n"
            "setattr(globals(), 'signals', object())\n"
            "def forged(*args):\n"
            "    return None\n"
            "signals.post_save.connect(forged)\n"
        ),
        "realtime/consumers.py": (
            "from channels.generic.websocket import AsyncWebsocketConsumer\n"
            "setattr(globals(), 'AsyncWebsocketConsumer', object())\n"
            "class Forged(AsyncWebsocketConsumer):\n"
            "    pass\n"
        ),
        "schedules/faux.py": (
            "from celery.schedules import crontab\n"
            "setattr(globals(), 'crontab', object())\n"
            "SCHEDULE = crontab(minute='*')\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path) for path in sources}, sources
    )

    assert [task for task in runtime.tasks if task.name == "forged"] == []
    assert runtime.realtime_consumers == []
    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "crontab"
    ] == []


def test_python_nested_reflected_global_write_revokes_framework_proof() -> None:
    """A reflected global write nested in an assignment RHS still executes."""
    path = "workers/faux.py"
    source = (
        "import celery\n"
        "def consume(value):\n"
        "    return None\n"
        "sink = consume(setattr(globals(), 'celery', object()))\n"
        "@celery.shared_task\n"
        "def forged():\n"
        "    return None\n"
    )
    runtime = discover_runtime_surfaces({path: _parsed_file(path)}, {path: source})

    assert [task for task in runtime.tasks if task.name == "forged"] == []


def test_python_reflected_global_write_keeps_earlier_dispatch_evidence() -> None:
    """Only dispatches after the reflected global write lose their receiver."""
    sources = {
        "pkg/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual():\n"
            "    pass\n"
        ),
        "pkg/api.py": (
            "from .tasks import actual\n"
            "actual.delay('before')\n"
            "setattr(globals(), 'actual', object())\n"
            "actual.delay('after')\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path) for path in sources}, sources
    )

    assert [
        (item.file_path, item.target_aliases) for item in runtime.dispatch_evidence
    ] == [("pkg/api.py", ("actual",))]


def test_python_nested_reflected_global_rebind_revokes_django_command() -> None:
    """A nested `globals()['Command']` write replaces the final command binding."""
    path = "app/management/commands/nested.py"
    source = (
        "from django.core.management.base import BaseCommand\n"
        "class Command(BaseCommand):\n"
        "    pass\n"
        "if True:\n"
        "    globals()['Command'] = object()\n"
    )
    runtime = discover_runtime_surfaces({path: _parsed_file(path)}, {path: source})

    assert [task for task in runtime.tasks if task.runtime_kind == "django_command"] == []


def test_python_dynamic_reflected_global_write_suppresses_framework_proof() -> None:
    """An unknown reflected global key can rebind any name, so the module fails closed."""
    sources = {
        "workers/subscript.py": (
            "import celery\n"
            "member = 'celery'\n"
            "globals()[member] = object()\n"
            "@celery.shared_task\n"
            "def forged():\n"
            "    return None\n"
        ),
        "workers/setattr.py": (
            "import celery\n"
            "member = 'celery'\n"
            "setattr(globals(), member, object())\n"
            "@celery.shared_task\n"
            "def forged():\n"
            "    return None\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path) for path in sources}, sources
    )

    assert [task for task in runtime.tasks if task.name == "forged"] == []


def test_python_plain_module_import_cannot_shorten_runtime_receivers() -> None:
    """`import a.b.c` binds only `a`; a shortened receiver proves nothing."""
    sources = {
        "realtime/consumers.py": (
            "import channels.generic.websocket\n"
            "class Forged(channels.AsyncWebsocketConsumer):\n"
            "    pass\n"
        ),
        "schedules/faux.py": (
            "import celery.schedules\n"
            "SCHEDULE = celery.crontab(hour=1)\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path) for path in sources}, sources
    )

    assert runtime.realtime_consumers == []
    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "crontab"
    ] == []


def test_python_exact_module_import_receivers_are_preserved() -> None:
    """The full dotted path and an explicit alias both stay valid receivers."""
    sources = {
        "realtime/dotted.py": (
            "import channels.generic.websocket\n"
            "class Dotted(channels.generic.websocket.AsyncWebsocketConsumer):\n"
            "    pass\n"
        ),
        "realtime/aliased.py": (
            "import channels.generic.websocket as websocket\n"
            "class Aliased(websocket.AsyncWebsocketConsumer):\n"
            "    pass\n"
        ),
        "schedules/dotted.py": (
            "import celery.schedules\n"
            "SCHEDULE = celery.schedules.crontab(hour=1)\n"
        ),
        "schedules/aliased.py": (
            "import celery.schedules as schedules\n"
            "SCHEDULE = schedules.crontab(hour=1)\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path) for path in sources}, sources
    )

    assert sorted(item.name for item in runtime.realtime_consumers) == [
        "Aliased",
        "Dotted",
    ]
    assert sorted(
        scheduler.file_path
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "crontab"
    ) == ["schedules/aliased.py", "schedules/dotted.py"]


def test_python_direct_exec_suppresses_celery_runtime_proof() -> None:
    """Unknown direct execution makes the module's framework bindings unsafe."""
    path = "workers/faux.py"
    source = (
        "import celery\n"
        "exec(\"celery.shared_task = fake\")\n"
        "@celery.shared_task\n"
        "def forged():\n"
        "    return None\n"
    )
    runtime = discover_runtime_surfaces({path: _parsed_file(path)}, {path: source})

    assert [task for task in runtime.tasks if task.name == "forged"] == []


def test_python_celery_submodules_cannot_authenticate_task_roles_or_factories() -> None:
    """Only canonical `celery` imports may establish task API authority."""
    sources = {
        "workers/submodule.py": (
            "from celery.schedules import task\n"
            "@task\n"
            "def forged():\n"
            "    pass\n"
        ),
        "workers/factory.py": (
            "import celery.schedules as sched\n"
            "app = sched.Celery('x')\n"
            "@app.task\n"
            "def forged_factory():\n"
            "    pass\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path) for path in sources}, sources
    )

    assert [
        task
        for task in runtime.tasks
        if task.name in {"forged", "forged_factory"}
    ] == []


def test_python_unbound_beat_schedule_cannot_create_celery_surfaces() -> None:
    """A lookalike config object cannot authenticate Celery beat metadata."""
    path = "config/schedule.py"
    source = (
        "class Fake:\n"
        "    pass\n"
        "app = Fake()\n"
        "app.conf = Fake()\n"
        "app.conf.beat_schedule = {\n"
        "    'nightly': {'task': 'forged.task', 'schedule': 1},\n"
        "}\n"
    )
    runtime = discover_runtime_surfaces({path: _parsed_file(path)}, {path: source})

    assert [task for task in runtime.tasks if task.runtime_kind == "celery"] == []
    assert [scheduler for scheduler in runtime.schedulers if scheduler.scheduler_type == "beat"] == []


def test_python_channels_plain_redefinition_revokes_prior_consumer() -> None:
    """Only the latest AST class binding can establish a Channels consumer."""
    sources = {
        "app/consumers.py": (
            "from channels.generic.websocket import AsyncWebsocketConsumer\n\n"
            "class OrdersConsumer(AsyncWebsocketConsumer):\n"
            "    pass\n\n"
            "class OrdersConsumer:\n"
            "    pass\n"
        )
    }
    parsed = {path: _parsed_file(path) for path in sources}

    runtime = discover_runtime_surfaces(parsed, sources)

    assert runtime.realtime_consumers == []


def test_python_channels_base_class_redefinition_cannot_authenticate_consumer() -> None:
    """A same-name plain class cannot retain an imported Channels base role."""
    path = "realtime/consumers.py"
    source = (
        "from channels.generic.websocket import AsyncWebsocketConsumer\n"
        "class AsyncWebsocketConsumer:\n"
        "    pass\n"
        "class Forged(AsyncWebsocketConsumer):\n"
        "    pass\n"
    )
    runtime = discover_runtime_surfaces({path: _parsed_file(path)}, {path: source})

    assert runtime.realtime_consumers == []


def test_python_plain_command_redefinition_revokes_django_command() -> None:
    """Only the final module class binding may establish a Django command."""
    path = "app/management/commands/demo.py"
    source = (
        "from django.core.management.base import BaseCommand\n"
        "class Command(BaseCommand):\n"
        "    pass\n"
        "class Command:\n"
        "    pass\n"
    )
    runtime = discover_runtime_surfaces({path: _parsed_file(path)}, {path: source})

    assert [task for task in runtime.tasks if task.runtime_kind == "django_command"] == []


def test_python_command_assignment_or_delete_revokes_django_command() -> None:
    """Only the final module `Command` binding can be a Django command."""
    sources = {
        "app/management/commands/reassigned.py": (
            "from django.core.management.base import BaseCommand\n"
            "class Command(BaseCommand):\n"
            "    pass\n"
            "Command = object\n"
        ),
        "app/management/commands/deleted.py": (
            "from django.core.management.base import BaseCommand\n"
            "class Command(BaseCommand):\n"
            "    pass\n"
            "del Command\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path) for path in sources}, sources
    )

    assert [task for task in runtime.tasks if task.runtime_kind == "django_command"] == []


def test_python_control_flow_command_rebind_revokes_django_command() -> None:
    """Any nested module write can replace the final Django `Command` binding."""
    prefix = (
        "from django.core.management.base import BaseCommand\n"
        "class Command(BaseCommand):\n"
        "    pass\n"
    )
    sources = {
        "app/management/commands/assigned.py": prefix + "if True:\n    Command = object\n",
        "app/management/commands/deleted.py": prefix + "if True:\n    del Command\n",
        "app/management/commands/imported.py": prefix + "if True:\n    from somewhere import Command\n",
        "app/management/commands/function.py": prefix + "if True:\n    def Command():\n        pass\n",
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path) for path in sources}, sources
    )

    assert [task for task in runtime.tasks if task.runtime_kind == "django_command"] == []


def test_python_channels_local_route_and_auth_shadows_create_no_metadata() -> None:
    """Function-local lookalikes cannot add Channels routes or auth evidence."""
    path = "realtime/consumers.py"
    source = (
        "from channels.generic.websocket import AsyncWebsocketConsumer\n"
        "from channels.auth import AuthMiddlewareStack\n"
        "from django.urls import path\n"
        "class RealConsumer(AsyncWebsocketConsumer):\n"
        "    pass\n"
        "def configure(path, AuthMiddlewareStack):\n"
        "    path('forged/', RealConsumer.as_asgi())\n"
        "    AuthMiddlewareStack(None)\n"
    )
    runtime = discover_runtime_surfaces({path: _parsed_file(path)}, {path: source})

    assert [(item.routes, item.auth_hints) for item in runtime.realtime_consumers] == [([], [])]


def test_python_channels_route_and_auth_imports_require_prior_source_position() -> None:
    """Later framework imports cannot authenticate earlier route/auth calls."""
    path = "realtime/consumers.py"
    source = (
        "from channels.generic.websocket import AsyncWebsocketConsumer\n"
        "class Valid(AsyncWebsocketConsumer):\n"
        "    pass\n"
        "path('bad/', Valid.as_asgi())\n"
        "AuthMiddlewareStack(None)\n"
        "from django.urls import path\n"
        "from channels.auth import AuthMiddlewareStack\n"
    )
    runtime = discover_runtime_surfaces({path: _parsed_file(path)}, {path: source})

    assert [(item.name, item.routes, item.auth_hints) for item in runtime.realtime_consumers] == [
        ("Valid", [], [])
    ]


def test_python_channels_auth_requires_imported_receiver_identity() -> None:
    """An unrelated `.AuthMiddlewareStack` spelling is not Channels auth proof."""
    path = "realtime/consumers.py"
    source = (
        "from channels.auth import AuthMiddlewareStack\n"
        "from channels.generic.websocket import AsyncWebsocketConsumer\n"
        "class Valid(AsyncWebsocketConsumer):\n"
        "    pass\n"
        "bogus.AuthMiddlewareStack(None)\n"
    )
    runtime = discover_runtime_surfaces({path: _parsed_file(path)}, {path: source})

    consumer = next(item for item in runtime.realtime_consumers if item.name == "Valid")
    assert "AuthMiddlewareStack" not in consumer.auth_hints


def test_python_crontab_parameter_shadow_cannot_create_scheduler() -> None:
    """A local parameter cannot authenticate the imported `crontab` factory."""
    path = "schedules/config.py"
    source = (
        "from celery.schedules import crontab\n"
        "def configure(crontab):\n"
        "    return crontab(hour=1)\n"
    )
    runtime = discover_runtime_surfaces({path: _parsed_file(path)}, {path: source})

    assert [scheduler for scheduler in runtime.schedulers if scheduler.scheduler_type == "crontab"] == []


def test_python_literal_setattr_revokes_django_signal_proof() -> None:
    """A literal reflective mutation cannot leave a Django signal trusted."""
    path = "signals/faux.py"
    source = (
        "from django.db.models.signals import post_save\n"
        "setattr(post_save, 'connect', lambda fn: fn)\n"
        "post_save.connect(forged)\n"
    )
    runtime = discover_runtime_surfaces({path: _parsed_file(path)}, {path: source})

    assert [task for task in runtime.tasks if task.name == "forged"] == []


def test_python_direct_exec_suppresses_django_signal_proof() -> None:
    """Unknown direct execution makes Django signal bindings unsafe."""
    path = "signals/faux.py"
    source = (
        "from django.db.models.signals import post_save\n"
        "exec(\"post_save.connect = fake\")\n"
        "post_save.connect(forged)\n"
    )
    runtime = discover_runtime_surfaces({path: _parsed_file(path)}, {path: source})

    assert [task for task in runtime.tasks if task.name == "forged"] == []


def test_python_direct_exec_suppresses_scheduler_proof() -> None:
    """Unknown direct execution makes scheduler factory bindings unsafe."""
    path = "schedules/faux.py"
    source = (
        "from celery.schedules import crontab\n"
        "exec('crontab = fake')\n"
        "crontab(hour=1)\n"
    )
    runtime = discover_runtime_surfaces({path: _parsed_file(path)}, {path: source})

    assert [scheduler for scheduler in runtime.schedulers if scheduler.scheduler_type == "crontab"] == []


def test_python_direct_exec_suppresses_channels_consumer_proof() -> None:
    """Unknown direct execution makes Channels inheritance bindings unsafe."""
    path = "realtime/consumers.py"
    source = (
        "from channels.generic.websocket import AsyncWebsocketConsumer\n"
        "exec('AsyncWebsocketConsumer = Fake')\n"
        "class Forged(AsyncWebsocketConsumer):\n"
        "    pass\n"
    )
    runtime = discover_runtime_surfaces({path: _parsed_file(path)}, {path: source})

    assert runtime.realtime_consumers == []


def test_python_direct_exec_suppresses_imported_task_dispatch_proof() -> None:
    """Unknown direct execution makes imported task values unsafe at call sites."""
    sources = {
        "pkg/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual():\n"
            "    pass\n"
        ),
        "pkg/api.py": (
            "from .tasks import actual\n"
            "exec('actual = fake')\n"
            "actual.delay(1)\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        item = parse_file(Path(path), source)
        assert item is not None
        parsed[path] = item
    runtime = discover_runtime_surfaces(parsed, sources)

    assert runtime.dispatch_evidence == []
    assert next(task for task in runtime.tasks if task.name == "actual").producer_files == []


def test_python_framework_member_deletes_revoke_runtime_proof() -> None:
    """Deleting a framework member revokes the root's runtime authority."""
    sources = {
        "workers/deleted.py": (
            "import celery\n"
            "del celery.shared_task\n\n"
            "@celery.shared_task\n"
            "def ghost():\n"
            "    return None\n"
        ),
        "signals/deleted.py": (
            "from django.db.models.signals import post_save\n"
            "del post_save.connect\n"
            "post_save.connect(handler)\n"
        ),
    }
    parsed = {path: _parsed_file(path) for path in sources}

    runtime = discover_runtime_surfaces(parsed, sources)

    assert runtime.tasks == []


def test_python_celery_aliases_multiline_decorators_and_bound_app_are_discovered() -> None:
    """Valid AST-bound Celery forms remain surfaces without raw decorator matching."""
    path = "workers/tasks.py"
    source = (
        "from celery import shared_task as background\n"
        "import celery as celery_lib\n"
        "app = celery_lib.Celery('workers')\n\n"
        "@background(\n"
        "    queue='critical',\n"
        "    retry_backoff=True,\n"
        ")\n"
        "def aliased(value):\n"
        "    return value\n\n"
        "@app.task\n"
        "def app_task(value):\n"
        "    return value\n"
    )
    parsed = parse_file(Path(path), source)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: source})
    tasks = {task.name: task for task in runtime.tasks}

    assert sorted(tasks) == ["aliased", "app_task"]
    assert tasks["aliased"].queue == "critical"
    assert tasks["aliased"].retry_policy == "retry_backoff"
    assert tasks["app_task"].decorator == "app.task"


def test_python_dispatch_binding_obeys_exact_statement_order() -> None:
    """Imports bind only after their exact statement position, not their line."""
    sources = {
        "pkg/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual(value):\n"
            "    return value\n"
        ),
        "pkg/before.py": "actual.delay(1); from .tasks import actual\n",
        "pkg/after.py": "from .tasks import actual; actual.delay(1)\n",
        "pkg/rebound.py": (
            "from .tasks import actual; actual = dynamic_task(); actual.delay(1)\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)
    task = next(item for item in runtime.tasks if item.name == "actual")

    assert [(item.file_path, item.relation) for item in runtime.dispatch_evidence] == [
        ("pkg/after.py", "direct")
    ]
    assert task.producer_files == ["pkg/after.py"]


def test_python_comprehension_binding_cannot_authenticate_imported_task() -> None:
    """A comprehension target shadows an imported task in its own expression."""
    sources = {
        "pkg/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual():\n"
            "    return None\n"
        ),
        "pkg/api.py": (
            "from .tasks import actual\n"
            "[actual.delay(1) for actual in values]\n"
        ),
    }
    parsed = {path: _parsed_file(path) for path in sources}

    runtime = discover_runtime_surfaces(parsed, sources)

    assert [item for item in runtime.dispatch_evidence if item.file_path == "pkg/api.py"] == []


def test_python_exception_target_cannot_authenticate_imported_task() -> None:
    """An exception target shadows an imported task in its handler body."""
    sources = {
        "pkg/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual():\n"
            "    return None\n"
        ),
        "pkg/api.py": (
            "from .tasks import actual\n"
            "try:\n"
            "    raise RuntimeError()\n"
            "except Exception as actual:\n"
            "    actual.delay(1)\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path) for path in sources}, sources
    )

    assert [item for item in runtime.dispatch_evidence if item.file_path == "pkg/api.py"] == []


def test_python_match_capture_cannot_authenticate_imported_task() -> None:
    """A structural pattern capture shadows an imported task in its case body."""
    sources = {
        "pkg/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual():\n"
            "    return None\n"
        ),
        "pkg/api.py": (
            "from .tasks import actual\n"
            "match subject:\n"
            "    case actual:\n"
            "        actual.delay(1)\n"
        ),
    }
    runtime = discover_runtime_surfaces(
        {path: _parsed_file(path) for path in sources}, sources
    )

    assert [item for item in runtime.dispatch_evidence if item.file_path == "pkg/api.py"] == []


def test_python_signal_binding_obeys_exact_statement_order() -> None:
    """A signal send before its same-line import cannot establish evidence."""
    sources = {
        "signals/before.py": (
            "post_save.send(sender=object); "
            "from django.db.models.signals import post_save\n"
        ),
        "signals/after.py": (
            "from django.db.models.signals import post_save; "
            "post_save.send(sender=object)\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)

    assert [(item.file_path, item.relation, item.target_aliases) for item in runtime.dispatch_evidence] == [
        ("signals/after.py", "signal", ("post_save",)),
    ]


def test_python_module_imports_and_bare_annotations_preserve_task_bindings() -> None:
    """Normal dotted imports and annotations do not erase proven task values."""
    sources = {
        "pkg/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual(value):\n"
            "    return value\n"
        ),
        "pkg/module_import.py": "import pkg.tasks\npkg.tasks.actual.delay(1)\n",
        "pkg/annotation.py": (
            "from .tasks import actual\n"
            "actual: object\n"
            "actual.delay(1)\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)
    task = next(item for item in runtime.tasks if item.name == "actual")

    assert [(item.file_path, item.target_aliases) for item in runtime.dispatch_evidence] == [
        ("pkg/module_import.py", ("pkg.tasks.actual", "actual")),
        ("pkg/annotation.py", ("actual",)),
    ]
    assert task.producer_files == ["pkg/module_import.py", "pkg/annotation.py"]


def test_python_bare_annotation_does_not_revoke_decorated_task_export() -> None:
    """`task: Type` annotates without rebinding the exported Celery callable."""
    sources = {
        "orders/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual():\n"
            "    return None\n"
            "actual: object\n"
        ),
        "orders/api.py": "from .tasks import actual\nactual.delay()\n",
    }
    parsed = {path: _parsed_file(path) for path in sources}

    runtime = discover_runtime_surfaces(parsed, sources)
    task = next(item for item in runtime.tasks if item.name == "actual")

    assert [(item.file_path, item.target_aliases) for item in runtime.dispatch_evidence] == [
        ("orders/api.py", ("actual",))
    ]
    assert task.producer_files == ["orders/api.py"]


def test_python_rebound_task_export_cannot_authenticate_cross_file_dispatch() -> None:
    """A later top-level rebinding revokes a previously decorated task export."""
    sources = {
        "stale/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual():\n"
            "    return None\n"
            "actual = object()\n"
        ),
        "stale/api.py": "from .tasks import actual\nactual.delay()\n",
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)
    task = next(item for item in runtime.tasks if item.name == "actual")

    assert runtime.dispatch_evidence == []
    assert task.producer_files == []


def test_python_local_task_binding_remains_valid_before_a_later_rebind() -> None:
    """A module-local call uses its source-position binding, not final exports."""
    path = "stale/tasks.py"
    source = (
        "from celery import shared_task\n"
        "@shared_task\n"
        "def actual():\n"
        "    return None\n"
        "actual.delay()\n"
        "actual = object()\n"
        "actual.delay()\n"
    )
    parsed = parse_file(Path(path), source)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: source})
    task = next(item for item in runtime.tasks if item.name == "actual")

    assert [(item.file_path, item.target_aliases) for item in runtime.dispatch_evidence] == [
        (path, ("actual",))
    ]
    assert task.producer_files == [path]


def test_python_schedule_entry_cannot_prove_a_same_name_plain_function() -> None:
    """A beat target is runtime metadata, not a local decorated task binding."""
    path = "orders/schedules.py"
    source = (
        "from celery.schedules import crontab\n"
        "app.conf.beat_schedule = {\n"
        "  'nightly': {\n"
        "    'task': 'orders.tasks.actual',\n"
        "    'schedule': crontab(hour='2'),\n"
        "  },\n"
        "}\n"
        "def actual():\n"
        "    return None\n"
        "actual.delay()\n"
    )
    parsed = parse_file(Path(path), source)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: source})

    assert [
        item for item in runtime.dispatch_evidence if item.relation == "direct"
    ] == []


def test_python_binding_history_uses_one_indexed_probe_per_dispatch(monkeypatch) -> None:
    """Large rebinding histories do not trigger a linear scan for each call."""
    calls: list[tuple[int, tuple[int, int]]] = []
    original_bisect = runtime_parser.bisect_right

    def counted_bisect(
        positions: tuple[tuple[int, int], ...], position: tuple[int, int]
    ) -> int:
        calls.append((len(positions), position))
        return original_bisect(positions, position)

    monkeypatch.setattr(runtime_parser, "bisect_right", counted_bisect)
    source_lines = ["from .tasks import actual"]
    for index in range(64):
        source_lines.extend(
            [
                f"actual.delay({index})",
                "actual = dynamic_task()",
                "from .tasks import actual",
            ]
        )
    sources = {
        "pkg/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual(value):\n"
            "    return value\n"
        ),
        "pkg/api.py": "\n".join(source_lines) + "\n",
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)

    assert len(runtime.dispatch_evidence) == 64
    assert len(calls) == 64
    assert max(history_length for history_length, _ in calls) >= 129


def test_python_dispatch_requires_a_resolved_task_binding() -> None:
    """An ordinary object's `.delay` cannot impersonate a discovered Celery task."""
    sources = {
        "orders/tasks.py": (
            "from celery import shared_task\n\n"
            "@shared_task\n"
            "def actual(order_id):\n"
            "    return order_id\n"
        ),
        "orders/api.py": (
            "from .tasks import actual\n\n"
            "def enqueue(order_id):\n"
            "    actual.delay(order_id)\n"
            "    ordinary.delay(order_id)\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)
    task = next(item for item in runtime.tasks if item.name == "actual")

    assert [(item.relation, item.target_aliases) for item in runtime.dispatch_evidence] == [
        ("direct", ("actual",))
    ]
    assert task.producer_files == ["orders/api.py"]


def test_python_imported_task_survives_unrelated_inner_shadow() -> None:
    """A parameter in one function cannot erase an import used by another."""
    sources = {
        "orders/tasks.py": (
            "from celery import shared_task\n\n"
            "@shared_task\n"
            "def actual(order_id):\n"
            "    return order_id\n"
        ),
        "orders/api.py": (
            "from .tasks import actual\n\n"
            "def enqueue(order_id):\n"
            "    actual.delay(order_id)\n\n"
            "def unrelated(actual):\n"
            "    return actual\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)
    task = next(item for item in runtime.tasks if item.name == "actual")

    assert [(item.relation, item.target_aliases) for item in runtime.dispatch_evidence] == [
        ("direct", ("actual",))
    ]
    assert task.producer_files == ["orders/api.py"]


def test_python_dispatch_before_later_module_rebind_remains_evidence() -> None:
    """A later module assignment cannot erase a prior executable task call."""
    sources = {
        "orders/tasks.py": (
            "from celery import shared_task\n\n"
            "@shared_task\n"
            "def actual(order_id):\n"
            "    return order_id\n"
        ),
        "orders/api.py": (
            "from .tasks import actual\n\n"
            "actual.delay(1)\n"
            "actual = make_dynamic_task()\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)
    task = next(item for item in runtime.tasks if item.name == "actual")

    assert [(item.relation, item.target_aliases) for item in runtime.dispatch_evidence] == [
        ("direct", ("actual",))
    ]
    assert task.producer_files == ["orders/api.py"]


def test_python_local_rebind_does_not_reuse_imported_task() -> None:
    """A function-local write shadows an imported task before `.delay` is called."""
    sources = {
        "orders/tasks.py": (
            "from celery import shared_task\n\n"
            "@shared_task\n"
            "def actual(order_id):\n"
            "    return order_id\n"
        ),
        "orders/api.py": (
            "from .tasks import actual\n\n"
            "def enqueue(order_id):\n"
            "    actual = make_dynamic_task()\n"
            "    actual.delay(order_id)\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)
    task = next(item for item in runtime.tasks if item.name == "actual")

    assert runtime.dispatch_evidence == []
    assert task.producer_files == []


def test_python_qualified_dispatch_alias_links_short_task_name() -> None:
    """A dotted Python task reference keeps its full and terminal aliases."""
    path = "handlers/orders.py"
    task = RuntimeTask(
        name="sync",
        file_path="workers/tasks.py",
        runtime_kind="celery",
    )
    evidence = _collect_dispatch_evidence(
        {path: "import tasks as tasks\ntasks.sync . delay(order_id)\n"},
        {path: "python"},
        {"tasks.py": {"sync"}},
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


def test_queue_evidence_never_uses_terminal_queue_aliases() -> None:
    """Queue identities are literals, not namespace-like task target aliases."""
    task = RuntimeTask(
        name="display",
        file_path="workers/qualified.js",
        runtime_kind="js_worker",
        queue=r"tenant\critical",
    )
    runtime = RuntimeScan(tasks=[task])
    evidence = [
        DispatchEvidence(
            file_path="producers/plain.js",
            language="javascript",
            relation="queue",
            target_aliases=("critical",),
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


def test_js_aliased_node_cron_schedule_bindings_are_discovered() -> None:
    """A proven node-cron schedule export may be renamed at its binding site."""
    sources = {
        "jobs/import-alias.ts": (
            "import { schedule as later } from 'node-cron';\n"
            "later('* * * * *', importedTask);\n"
        ),
        "jobs/member-alias.js": (
            "const later = require('node-cron').schedule;\n"
            "later('*/5 * * * *', memberTask);\n"
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
        ("jobs/import-alias.ts", "* * * * *", ["importedTask"]),
        ("jobs/member-alias.js", "*/5 * * * *", ["memberTask"]),
    ]


def test_js_destructuring_from_a_proven_default_module_binds_runtime_exports() -> None:
    """A default module binding can safely feed a renamed local export binding."""
    path = "jobs/cron-alias.ts"
    content = (
        "import cron from 'node-cron';\n"
        "const { schedule: later } = cron;\n"
        "later('* * * * *', syncReports);\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: content})

    assert [(item.scheduler_type, item.invoked_targets) for item in runtime.schedulers] == [
        ("node_cron", ["syncReports"])
    ]


def test_js_static_import_bindings_are_hoisted_for_runtime_calls() -> None:
    """Static ES imports exist for the whole module, not only after their text."""
    path = "jobs/hoisted-schedule.ts"
    content = (
        "schedule('* * * * *', syncReports);\n"
        "import { schedule } from 'node-cron';\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: content})

    assert [(item.scheduler_type, item.invoked_targets) for item in runtime.schedulers] == [
        ("node_cron", ["syncReports"])
    ]


def test_typescript_import_equals_require_binds_runtime_module_exports() -> None:
    """TypeScript `import x = require()` is a runtime module binding, not only a shadow."""
    path = "jobs/import-equals.ts"
    content = (
        "import cron = require('node-cron');\n"
        "cron.schedule('* * * * *', syncReports);\n"
    )
    parsed = parse_file(Path(path), content)
    assert parsed is not None

    runtime = discover_runtime_surfaces({path: parsed}, {path: content})

    assert [(item.scheduler_type, item.invoked_targets) for item in runtime.schedulers] == [
        ("node_cron", ["syncReports"])
    ]


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


def test_js_runtime_bindings_do_not_assume_uninvoked_sibling_functions() -> None:
    """Dynamic writes and uninvoked nested functions create no runtime facts."""
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
        task
        for task in runtime.tasks
        if task.runtime_kind == "js_worker"
    ] == []
    assert runtime.dispatch_evidence == []
    assert runtime.realtime_consumers == []


def test_js_augmented_assignments_invalidate_runtime_bindings() -> None:
    """Logical/compound writes revoke Queue and global require proof."""
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/augmented.js": (
            "const { Queue } = require('bullmq');\n"
            "let queue = new Queue('orders');\n"
            "queue &&= getDynamicQueue();\n"
            "queue.add('not-an-orders-job', {});\n"
        ),
        "realtime/augmented.js": (
            "require &&= customLoader;\n"
            "const io = require('socket.io')(server);\n"
            "io.on('connection', handleConnection);\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)

    assert runtime.dispatch_evidence == []
    worker = next(task for task in runtime.tasks if task.file_path == "workers/orders.js")
    assert worker.producer_files == []
    assert runtime.realtime_consumers == []


def test_js_with_scope_cannot_authenticate_queue_producer() -> None:
    """A dynamic `with` receiver cannot reuse a lexical Queue binding."""
    path = "producers/orders.js"
    source = (
        "const { Queue } = require('bullmq');\n"
        "const q = new Queue('orders');\n"
        "with ({ q: { add() {} } }) q.add('job', {});\n"
    )
    parsed = parse_file(Path(path), source)
    assert parsed is not None
    runtime = discover_runtime_surfaces({path: parsed}, {path: source})

    assert runtime.dispatch_evidence == []


def test_js_object_assign_cannot_preserve_mutated_module_role() -> None:
    """An unshadowed `Object.assign` mutation taints the module export value."""
    worker_path = "workers/orders.js"
    producer_path = "producers/orders.js"
    sources = {
        worker_path: (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        producer_path: (
            "const bull = require('bullmq');\n"
            "Object.assign(bull, { Queue: FakeQueue });\n"
            "const q = new bull.Queue('orders');\n"
            "q.add('job', {});\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file
    runtime = discover_runtime_surfaces(parsed, sources)

    assert runtime.dispatch_evidence == []
    assert next(task for task in runtime.tasks if task.file_path == worker_path).producer_files == []


def test_js_destructuring_member_target_cannot_preserve_queue_role() -> None:
    """A member write nested in a destructuring target taints the queue value."""
    path = "producers/orders.js"
    source = (
        "const { Queue } = require('bullmq');\n"
        "const q = new Queue('orders');\n"
        "({ add: q.add } = { add() {} });\n"
        "q.add('job', {});\n"
    )
    parsed = parse_file(Path(path), source)
    assert parsed is not None
    runtime = discover_runtime_surfaces({path: parsed}, {path: source})

    assert runtime.dispatch_evidence == []


def test_js_static_import_is_available_before_its_source_position() -> None:
    """A hoisted ESM import can prove a top-level preceding initializer."""
    path = "producers/orders.ts"
    source = (
        "const q = new Queue('orders');\n"
        "q.add('job', {});\n"
        "import { Queue } from 'bullmq';\n"
    )
    parsed = parse_file(Path(path), source)
    assert parsed is not None
    runtime = discover_runtime_surfaces({path: parsed}, {path: source})

    assert [(item.relation, item.target_aliases) for item in runtime.dispatch_evidence] == [
        ("queue", ("orders",))
    ]


def test_js_uninvoked_function_body_cannot_create_worker() -> None:
    """A worker constructor inside an exported function is not executed evidence."""
    path = "workers/dead.js"
    source = (
        "const { Worker } = require('bullmq');\n"
        "export function never() {\n"
        "  return;\n"
        "  new Worker('orders', handleOrders);\n"
        "}\n"
    )
    parsed = parse_file(Path(path), source)
    assert parsed is not None
    runtime = discover_runtime_surfaces({path: parsed}, {path: source})

    assert [task for task in runtime.tasks if task.runtime_kind == "js_worker"] == []


def test_js_member_writes_invalidate_runtime_receivers_and_exports() -> None:
    """Mutating a trusted API method or module export revokes its role proof."""
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/method.js": (
            "const { Queue } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "queue.add = fakeAdd;\n"
            "queue.add('not-an-orders-job', {});\n"
        ),
        "producers/export.js": (
            "const bull = require('bullmq');\n"
            "bull.Queue = FakeQueue;\n"
            "const queue = new bull.Queue('orders');\n"
            "queue.add('not-an-orders-job', {});\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)

    assert runtime.dispatch_evidence == []
    worker = next(task for task in runtime.tasks if task.file_path == "workers/orders.js")
    assert worker.producer_files == []


def test_js_alias_member_writes_revoke_original_runtime_values() -> None:
    """A member write through an alias taints every spelling of that value."""
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/queue-alias.js": (
            "const { Queue } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "const alias = queue;\n"
            "alias.add = fakeAdd;\n"
            "queue.add('forged', {});\n"
        ),
        "producers/module-alias.js": (
            "const bull = require('bullmq');\n"
            "const alias = bull;\n"
            "alias.Queue = FakeQueue;\n"
            "const queue = new bull.Queue('orders');\n"
            "queue.add('forged', {});\n"
        ),
    }
    parsed = {
        path: _parsed_file(path, language="javascript") for path in sources
    }

    runtime = discover_runtime_surfaces(parsed, sources)
    worker = next(task for task in runtime.tasks if task.file_path == "workers/orders.js")

    assert runtime.dispatch_evidence == []
    assert worker.producer_files == []


def test_js_nested_mutator_revokes_outer_runtime_bindings() -> None:
    """A nested function can mutate an outer receiver before its later use."""
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/hoisted.js": (
            "const { Queue } = require('bullmq');\n"
            "let queue = new Queue('orders');\n"
            "replace();\n"
            "queue.add('not-an-orders-job', {});\n"
            "function replace() { queue = getDynamicQueue(); }\n"
        ),
        "realtime/hoisted.js": (
            "poison();\n"
            "const io = require('socket.io')(server);\n"
            "io.on('connection', handleConnection);\n"
            "function poison() { require = customLoader; }\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)

    assert runtime.dispatch_evidence == []
    worker = next(task for task in runtime.tasks if task.file_path == "workers/orders.js")
    assert worker.producer_files == []
    assert runtime.realtime_consumers == []


def test_js_eval_and_with_scope_cannot_authenticate_runtime_evidence() -> None:
    """Dynamic scope operations revoke otherwise trusted queue/realtime roles."""
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/eval.js": (
            "const { Queue } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "eval('queue.add = fakeAdd');\n"
            "queue.add('forged', {});\n"
        ),
        "producers/with.js": (
            "const { Queue } = require('bullmq');\n"
            "let queue;\n"
            "with ({ Queue: FakeQueue }) { queue = new Queue('orders'); }\n"
            "queue.add('forged', {});\n"
        ),
        "realtime/eval.js": (
            "eval('require = fakeLoader');\n"
            "const io = require('socket.io')(server);\n"
            "io.on('connection', handler);\n"
        ),
    }
    parsed = {
        path: _parsed_file(path, language="javascript") for path in sources
    }

    runtime = discover_runtime_surfaces(parsed, sources)
    worker = next(task for task in runtime.tasks if task.file_path == "workers/orders.js")

    assert runtime.dispatch_evidence == []
    assert worker.producer_files == []
    assert runtime.realtime_consumers == []


def test_js_binding_history_uses_one_indexed_probe_per_lookup() -> None:
    """Large rebinding histories never cause a per-lookup linear scan."""
    writes = "\n".join(
        f"queue = new Queue('orders-{index}'); queue.add('job-{index}', {{}});"
        for index in range(128)
    )
    source = (
        "const { Queue } = require('bullmq');\n"
        "let queue = new Queue('orders-initial');\n"
        f"{writes}\n"
    )
    tree = js_ts_parser.Parser(js_ts_parser.JS_LANGUAGE).parse(source.encode())
    binder = js_ts_parser._Binder(frozenset({"bullmq"}))

    calls = binder.run(tree.root_node)

    assert len([call for call in calls if call.symbol == "add"]) == 128
    assert binder._binding_history_steps == binder._binding_lookup_probes
    assert binder._binding_lookup_probes <= len(calls) * 2


def test_js_non_guaranteed_writes_do_not_prove_queue_receivers() -> None:
    """Nested or conditional Queue writes cannot authenticate an outer `.add()`."""
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/uninvoked.js": (
            "const { Queue } = require('bullmq');\n"
            "let queue = { add() {} };\n"
            "function configure() { queue = new Queue('orders'); }\n"
            "queue.add('not-an-orders-job', {});\n"
        ),
        "producers/conditional.js": (
            "const { Queue } = require('bullmq');\n"
            "let queue = { add() {} };\n"
            "if (enabled) { queue = new Queue('orders'); }\n"
            "queue.add('not-an-orders-job', {});\n"
        ),
    }
    parsed = {}
    for path, source in sources.items():
        parsed_file = parse_file(Path(path), source)
        assert parsed_file is not None
        parsed[path] = parsed_file

    runtime = discover_runtime_surfaces(parsed, sources)

    assert runtime.dispatch_evidence == []
    worker = next(item for item in runtime.tasks if item.file_path == "workers/orders.js")
    assert worker.producer_files == []


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
