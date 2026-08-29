from __future__ import annotations

from pathlib import Path

from deepdoc.parser.base import ParsedFile
from deepdoc.parser.registry import parse_file
from deepdoc.planner.partitioning import PlanningUnit, make_sub_scan
from deepdoc.scanner.common import DispatchEvidence, FILE_EXT_RE, RuntimeScan, RuntimeTask
from deepdoc.scanner.runtime import discover_runtime_surfaces
from deepdoc.v2_models import RepoScan


def _parsed(path: str, language: str) -> ParsedFile:
    return ParsedFile(path=Path(path), language=language, imports=[], symbols=[])


def _scan(sources: dict[str, str], languages: dict[str, str]) -> RuntimeScan:
    parsed = {path: _parsed(path, languages[path]) for path in sources}
    return discover_runtime_surfaces(parsed, sources)


def _queue_aliases(runtime: RuntimeScan) -> list[tuple[str, tuple[str, ...]]]:
    return [
        (item.file_path, item.target_aliases)
        for item in runtime.dispatch_evidence
        if item.relation == "queue"
    ]


def _direct_aliases(runtime: RuntimeScan) -> list[tuple[str, tuple[str, ...]]]:
    return [
        (item.file_path, item.target_aliases)
        for item in runtime.dispatch_evidence
        if item.relation == "direct"
    ]


def _signal_aliases(runtime: RuntimeScan) -> list[tuple[str, tuple[str, ...]]]:
    return [
        (item.file_path, item.target_aliases)
        for item in runtime.dispatch_evidence
        if item.relation == "signal"
    ]


def test_js_uninvoked_object_assign_keeps_prior_queue_dispatch() -> None:
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/uninvoked.js": (
            "function poison() { Object.assign(queue, { add: fakeAdd }); }\n"
            "const { Queue } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "queue.add('prior', {});\n"
        ),
    }
    runtime = _scan(sources, {path: "javascript" for path in sources})
    assert _queue_aliases(runtime) == [("producers/uninvoked.js", ("orders",))]


def test_js_invoked_object_assign_orders_by_call_site_not_body_text() -> None:
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/before.js": (
            "function poison() { Object.assign(queue, { add: fakeAdd }); }\n"
            "const { Queue } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "queue.add('prior', {});\n"
            "poison();\n"
        ),
        "producers/after.js": (
            "function poison() { Object.assign(queue, { add: fakeAdd }); }\n"
            "const { Queue } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "poison();\n"
            "queue.add('forged', {});\n"
        ),
    }
    runtime = _scan(sources, {path: "javascript" for path in sources})
    assert _queue_aliases(runtime) == [("producers/before.js", ("orders",))]


def test_js_delete_and_define_property_taint_queue_receiver() -> None:
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/delete.js": (
            "const { Queue } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "delete queue.add;\n"
            "queue.add('forged', {});\n"
        ),
        "producers/define.js": (
            "const { Queue } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "Object.defineProperty(queue, 'add', { value: fakeAdd });\n"
            "queue.add('forged', {});\n"
        ),
        "producers/reflect.js": (
            "const { Queue } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "Reflect.set(queue, 'add', fakeAdd);\n"
            "queue.add('forged', {});\n"
        ),
    }
    runtime = _scan(sources, {path: "javascript" for path in sources})
    assert runtime.dispatch_evidence == []


def test_js_same_literal_queue_name_does_not_cross_taint() -> None:
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/clean.js": (
            "const { Queue } = require('bullmq');\n"
            "const clean = new Queue('orders');\n"
            "const dirty = new Queue('orders');\n"
            "Object.assign(dirty, { add: fakeAdd });\n"
            "clean.add('keep', {});\n"
        ),
    }
    runtime = _scan(sources, {path: "javascript" for path in sources})
    assert _queue_aliases(runtime) == [("producers/clean.js", ("orders",))]


def test_js_uninvoked_eval_does_not_taint_prior_dispatch() -> None:
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/uninvoked-eval.js": (
            "const { Queue } = require('bullmq');\n"
            "const queue = new Queue('orders');\n"
            "queue.add('prior', {});\n"
            "function poison() { eval('queue.add = fakeAdd'); }\n"
        ),
    }
    runtime = _scan(sources, {path: "javascript" for path in sources})
    assert _queue_aliases(runtime) == [("producers/uninvoked-eval.js", ("orders",))]


def test_js_deep_member_chain_does_not_abort_runtime_scan() -> None:
    chain = "require('bullmq')" + ".Queue" * 2000
    sources = {
        "workers/orders.js": (
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
        ),
        "producers/deep.js": f"const Queue = {chain};\nnew Queue('orders');\n",
    }
    runtime = _scan(sources, {path: "javascript" for path in sources})
    worker = next(task for task in runtime.tasks if task.file_path == "workers/orders.js")
    assert worker.name == "orders"


def test_python_task_module_rejects_inserted_attributes() -> None:
    sources = {
        "jobs/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual():\n"
            "    return 1\n"
        ),
        "jobs/producer.py": (
            "import jobs.tasks as task_module\n"
            "task_module.other.actual.delay()\n"
        ),
    }
    runtime = _scan(sources, {path: "python" for path in sources})
    task = next(item for item in runtime.tasks if item.name == "actual")
    assert task.producer_files == []
    assert _direct_aliases(runtime) == []


def test_python_signal_module_rejects_inserted_attributes() -> None:
    sources = {
        "handlers/signals.py": (
            "import django.db.models.signals as signals\n"
            "signals.fake.post_save.send(sender=Order)\n"
        ),
    }
    runtime = _scan(sources, {path: "python" for path in sources})
    assert _signal_aliases(runtime) == []


def test_python_globals_update_fails_closed() -> None:
    sources = {
        "jobs/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual():\n"
            "    return 1\n"
        ),
        "jobs/producer.py": (
            "from jobs.tasks import actual\n"
            "globals().update({'actual': fake})\n"
            "actual.delay()\n"
        ),
    }
    runtime = _scan(sources, {path: "python" for path in sources})
    task = next(item for item in runtime.tasks if item.name == "actual")
    assert task.producer_files == []


def test_python_invoked_global_assignment_invalidates_task_binding() -> None:
    sources = {
        "jobs/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual():\n"
            "    return 1\n"
        ),
        "jobs/producer.py": (
            "from jobs.tasks import actual\n"
            "def rebind():\n"
            "    global actual\n"
            "    actual = fake\n"
            "rebind()\n"
            "actual.delay()\n"
        ),
    }
    runtime = _scan(sources, {path: "python" for path in sources})
    task = next(item for item in runtime.tasks if item.name == "actual")
    assert task.producer_files == []


def test_python_crontab_before_later_rebind_is_kept() -> None:
    sources = {
        "jobs/beat.py": (
            "from celery.schedules import crontab\n"
            "crontab(minute=0)\n"
            "crontab = None\n"
        ),
    }
    runtime = _scan(sources, {path: "python" for path in sources})
    assert any(scheduler.scheduler_type == "crontab" for scheduler in runtime.schedulers)


def test_python_holder_app_assignment_does_not_authenticate_holder_task() -> None:
    sources = {
        "jobs/app.py": (
            "from celery import Celery\n"
            "holder = object()\n"
            "holder.app = Celery('jobs')\n"
            "@holder.task\n"
            "def forged():\n"
            "    return 1\n"
        ),
    }
    runtime = _scan(sources, {path: "python" for path in sources})
    assert [task.name for task in runtime.tasks] == []


def test_python_beat_schedule_write_does_not_revoke_app() -> None:
    sources = {
        "jobs/app.py": (
            "from celery import Celery\n"
            "app = Celery('jobs')\n"
            "app.conf.beat_schedule = {}\n"
            "@app.task\n"
            "def later():\n"
            "    return 1\n"
        ),
    }
    runtime = _scan(sources, {path: "python" for path in sources})
    assert [task.name for task in runtime.tasks] == ["later"]


def test_python_exact_imports_of_same_task_name_are_not_ambiguous() -> None:
    sources = {
        "alpha/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def send():\n"
            "    return 'a'\n"
        ),
        "beta/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def send():\n"
            "    return 'b'\n"
        ),
        "alpha/producer.py": (
            "from alpha.tasks import send\n"
            "send.delay()\n"
        ),
    }
    runtime = _scan(sources, {path: "python" for path in sources})
    alpha = next(task for task in runtime.tasks if task.file_path == "alpha/tasks.py")
    beta = next(task for task in runtime.tasks if task.file_path == "beta/tasks.py")
    assert alpha.producer_files == ["alpha/producer.py"]
    assert beta.producer_files == []


def test_python_unbound_signal_connect_creates_no_task() -> None:
    sources = {
        "handlers/signals.py": (
            "from django.db.models.signals import post_save\n"
            "post_save.connect(missing_handler)\n"
        ),
    }
    runtime = _scan(sources, {path: "python" for path in sources})
    assert runtime.tasks == []


def test_python_channels_routing_resolves_imported_consumer() -> None:
    sources = {
        "chat/consumers.py": (
            "from channels.generic.websocket import AsyncWebsocketConsumer\n"
            "class ChatConsumer(AsyncWebsocketConsumer):\n"
            "    pass\n"
        ),
        "chat/routing.py": (
            "from django.urls import path\n"
            "from chat.consumers import ChatConsumer\n"
            "urlpatterns = [path('ws/chat/', ChatConsumer.as_asgi())]\n"
        ),
    }
    runtime = _scan(sources, {path: "python" for path in sources})
    consumer = next(item for item in runtime.realtime_consumers if item.name == "ChatConsumer")
    assert "ws/chat/" in consumer.routes


def test_python_dotted_django_signal_import_is_proven() -> None:
    sources = {
        "handlers/signals.py": (
            "import django.db.models.signals\n"
            "django.db.models.signals.post_save.send(sender=Order)\n"
        ),
    }
    runtime = _scan(sources, {path: "python" for path in sources})
    assert _signal_aliases(runtime) == [
        ("handlers/signals.py", ("post_save",))
    ]


def _laravel_kernel(body: str) -> str:
    return (
        "<?php\n"
        "use Illuminate\\Console\\Scheduling\\Schedule;\n"
        "use Illuminate\\Foundation\\Console\\Kernel as ConsoleKernel;\n"
        "class Kernel extends ConsoleKernel {\n"
        "    protected function schedule(Schedule $schedule): void {\n"
        f"{body}"
        "    }\n"
        "}\n"
    )


def test_php_nested_and_assigned_by_ref_closures_revoke_schedule() -> None:
    sources = {
        "app/Console/NestedKernel.php": _laravel_kernel(
            "        ((function () use (&$schedule) { $schedule = new FakeScheduler(); })());\n"
            "        $schedule->command('forged:nested')->daily();\n"
        ),
        "app/Console/AssignedKernel.php": _laravel_kernel(
            "        $fn = function () use (&$schedule) { $schedule = new FakeScheduler(); };\n"
            "        $fn();\n"
            "        $schedule->command('forged:assigned')->daily();\n"
        ),
        "app/Console/CallUserFuncKernel.php": _laravel_kernel(
            "        call_user_func(function () use (&$schedule) { $schedule = new FakeScheduler(); });\n"
            "        $schedule->command('forged:call')->daily();\n"
        ),
    }
    runtime = _scan(sources, {path: "php" for path in sources})
    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "laravel_schedule"
    ] == []


def test_php_catch_global_unset_revoke_schedule() -> None:
    sources = {
        "app/Console/CatchKernel.php": _laravel_kernel(
            "        try { throw new Exception(); } catch (Exception $schedule) {}\n"
            "        $schedule->command('forged:catch')->daily();\n"
        ),
        "app/Console/UnsetKernel.php": _laravel_kernel(
            "        unset($schedule);\n"
            "        $schedule->command('forged:unset')->daily();\n"
        ),
    }
    runtime = _scan(sources, {path: "php" for path in sources})
    assert [
        scheduler
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "laravel_schedule"
    ] == []


def test_php_assignment_rhs_schedule_call_is_kept() -> None:
    sources = {
        "app/Console/RhsKernel.php": _laravel_kernel(
            "        $schedule = $schedule->command('ok:run')->daily();\n"
        ),
    }
    runtime = _scan(sources, {path: "php" for path in sources})
    assert [
        (scheduler.invoked_targets, scheduler.cron)
        for scheduler in runtime.schedulers
        if scheduler.scheduler_type == "laravel_schedule"
    ] == [(["ok:run"], "daily")]


def test_php_static_event_dispatch_is_an_event_relation() -> None:
    sources = {
        "app/Events/OrderPlaced.php": (
            "<?php\n"
            "namespace App\\Events;\n"
            "use Illuminate\\Foundation\\Events\\Dispatchable;\n"
            "class OrderPlaced { use Dispatchable; }\n"
        ),
        "app/Http/OrderController.php": (
            "<?php\n"
            "use App\\Events\\OrderPlaced;\n"
            "class OrderController {\n"
            "    public function store() { OrderPlaced::dispatch(); }\n"
            "}\n"
        ),
        "app/Listeners/SendReceipt.php": (
            "<?php\n"
            "namespace App\\Listeners;\n"
            "use App\\Events\\OrderPlaced;\n"
            "use Illuminate\\Contracts\\Queue\\ShouldQueue;\n"
            "class SendReceipt implements ShouldQueue {\n"
            "    public function handle(OrderPlaced $event) {}\n"
            "}\n"
        ),
    }
    runtime = _scan(sources, {path: "php" for path in sources})
    kinds = {task.runtime_kind for task in runtime.tasks}
    assert "laravel_event" in kinds
    assert "laravel_listener" in kinds


def test_php_shouldqueue_job_with_matching_handle_is_not_listener() -> None:
    sources = {
        "app/Events/OrderPlaced.php": (
            "<?php\n"
            "namespace App\\Events;\n"
            "use Illuminate\\Foundation\\Events\\Dispatchable;\n"
            "class OrderPlaced { use Dispatchable; }\n"
        ),
        "app/Http/OrderController.php": (
            "<?php\n"
            "event(new \\App\\Events\\OrderPlaced());\n"
        ),
        "app/Jobs/ChargeOrder.php": (
            "<?php\n"
            "namespace App\\Jobs;\n"
            "use App\\Events\\OrderPlaced;\n"
            "use Illuminate\\Contracts\\Queue\\ShouldQueue;\n"
            "class ChargeOrder implements ShouldQueue {\n"
            "    public function handle(OrderPlaced $event) {}\n"
            "}\n"
        ),
    }
    runtime = _scan(sources, {path: "php" for path in sources})
    assert [
        task.runtime_kind for task in runtime.tasks if task.name == "ChargeOrder"
    ] != ["laravel_listener"]


def test_go_grouped_parameter_named_cron_does_not_emit_scheduler() -> None:
    sources = {
        "cmd/worker/main.go": (
            "package main\n\n"
            "import cron \"github.com/robfig/cron/v3\"\n\n"
            "func runJob() {}\n"
            "func setup(a, cron int) {\n"
            "    c := cron.New()\n"
            "    c.AddFunc(\"@every 1s\", runJob)\n"
            "    c.Start()\n"
            "}\n"
        ),
    }
    runtime = _scan(sources, {path: "go" for path in sources})
    assert runtime.schedulers == []


def test_go_range_assignment_revokes_outer_scheduler() -> None:
    sources = {
        "cmd/worker/main.go": (
            "package main\n\n"
            "import cron \"github.com/robfig/cron/v3\"\n\n"
            "func runJob() {}\n"
            "func main() {\n"
            "    c := cron.New()\n"
            "    for c = range xs {\n"
            "    }\n"
            "    c.AddFunc(\"@every 1s\", runJob)\n"
            "    c.Start()\n"
            "}\n"
        ),
    }
    runtime = _scan(sources, {path: "go" for path in sources})
    assert runtime.schedulers == []


def test_go_scheduler_alias_keeps_receiver_role() -> None:
    sources = {
        "cmd/worker/main.go": (
            "package main\n\n"
            "import cron \"github.com/robfig/cron/v3\"\n\n"
            "func runJob() {}\n"
            "func main() {\n"
            "    scheduler := cron.New()\n"
            "    alias := scheduler\n"
            "    alias.AddFunc(\"@every 1s\", runJob)\n"
            "    alias.Start()\n"
            "}\n"
        ),
    }
    runtime = _scan(sources, {path: "go" for path in sources})
    assert any(scheduler.scheduler_type == "go_cron" for scheduler in runtime.schedulers)


def test_go_addfunc_without_start_is_not_scheduled_execution() -> None:
    sources = {
        "cmd/worker/main.go": (
            "package main\n\n"
            "import cron \"github.com/robfig/cron/v3\"\n\n"
            "func cleanup() {}\n"
            "func main() {\n"
            "    c := cron.New()\n"
            "    c.AddFunc(\"@every 5m\", cleanup)\n"
            "}\n"
        ),
    }
    runtime = _scan(sources, {path: "go" for path in sources})
    assert runtime.schedulers == []
    assert [
        task
        for task in runtime.tasks
        if task.schedule_sources
    ] == []


def test_vue_interpolation_less_than_does_not_drop_script() -> None:
    sources = {
        "components/Queue.vue": (
            "<template>\n"
            "  <p>{{ count < limit }}</p>\n"
            "</template>\n"
            "<script>\n"
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
            "</script>\n"
        ),
    }
    runtime = _scan(sources, {path: "vue" for path in sources})
    assert any(task.runtime_kind == "js_worker" for task in runtime.tasks)


def test_vue_tsx_script_uses_tsx_grammar() -> None:
    sources = {
        "components/Queue.vue": (
            "<script lang=\"tsx\">\n"
            "const { Worker } = require('bullmq');\n"
            "const node = <div />;\n"
            "new Worker('orders', handleOrders);\n"
            "</script>\n"
        ),
    }
    runtime = _scan(sources, {path: "vue" for path in sources})
    assert any(task.queue == "orders" for task in runtime.tasks)


def test_vue_data_src_is_not_an_external_script() -> None:
    sources = {
        "components/Queue.vue": (
            "<script data-src=\"ignored.js\">\n"
            "const { Worker } = require('bullmq');\n"
            "new Worker('orders', handleOrders);\n"
            "</script>\n"
        ),
    }
    runtime = _scan(sources, {path: "vue" for path in sources})
    assert any(task.runtime_kind == "js_worker" for task in runtime.tasks)


def test_sub_scan_filters_dispatch_evidence_to_unit_files() -> None:
    orders = "services/orders/app.py"
    payments = "services/payments/app.py"
    scan = RepoScan(
        file_tree={},
        file_summaries={orders: "s", payments: "s"},
        api_endpoints=[],
        languages={"python": 2},
        has_openapi=False,
        openapi_paths=[],
        total_files=2,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_services={orders: "orders", payments: "payments"},
        runtime_scan=RuntimeScan(
            tasks=[
                RuntimeTask(name="sync", file_path=orders, runtime_kind="celery"),
            ],
            dispatch_evidence=[
                DispatchEvidence(
                    file_path=orders,
                    language="python",
                    relation="direct",
                    target_aliases=("sync",),
                ),
                DispatchEvidence(
                    file_path=payments,
                    language="python",
                    relation="direct",
                    target_aliases=("charge",),
                ),
            ],
        ),
    )
    unit = PlanningUnit(slug="orders", label="orders", files=(orders,), coarse=False)
    sub = make_sub_scan(scan, unit)
    assert [item.file_path for item in sub.runtime_scan.dispatch_evidence] == [orders]


def test_empty_product_files_are_not_counted_as_low_trust() -> None:
    sources = {
        "jobs/tasks.py": (
            "from celery import shared_task\n"
            "@shared_task\n"
            "def actual():\n"
            "    return 1\n"
        ),
        "jobs/empty.py": "",
    }
    runtime = _scan(sources, {path: "python" for path in sources})
    assert runtime.scan_stats["low_trust_files_skipped"] == 0
    assert runtime.scan_stats["eligible_files"] == 1


def test_file_ext_re_includes_vue() -> None:
    assert FILE_EXT_RE.search("components/Queue.vue")
