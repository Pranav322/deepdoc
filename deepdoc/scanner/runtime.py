from .common import *


def discover_runtime_surfaces(
    parsed_files: dict[str, ParsedFile],
    file_contents: dict[str, str],
    api_endpoints: list[dict[str, Any]] | None = None,
) -> RuntimeScan:
    """Detect first-class background job, scheduler, and realtime surfaces."""
    runtime = RuntimeScan()
    celery_tasks, celery_schedulers = _discover_celery_tasks(file_contents)
    runtime.tasks.extend(celery_tasks)
    runtime.schedulers.extend(celery_schedulers)
    runtime.tasks.extend(_discover_django_runtime(file_contents))
    laravel_tasks, laravel_schedulers = _discover_laravel_runtime(file_contents)
    runtime.tasks.extend(laravel_tasks)
    runtime.schedulers.extend(laravel_schedulers)
    js_tasks, js_schedulers = _discover_js_runtime(file_contents)
    runtime.tasks.extend(js_tasks)
    runtime.schedulers.extend(js_schedulers)
    go_tasks, go_schedulers = _discover_go_runtime(file_contents)
    runtime.tasks.extend(go_tasks)
    runtime.schedulers.extend(go_schedulers)
    runtime.schedulers.extend(_discover_schedulers(file_contents))
    runtime.realtime_consumers.extend(_discover_realtime_consumers(file_contents))
    _link_runtime_workflows(runtime, file_contents, api_endpoints or [])
    runtime.tasks = _dedupe_runtime_tasks(runtime.tasks)
    runtime.schedulers = _dedupe_schedulers(runtime.schedulers)
    runtime.realtime_consumers = _dedupe_consumers(runtime.realtime_consumers)
    return runtime


def _link_runtime_workflows(
    runtime: RuntimeScan,
    file_contents: dict[str, str],
    api_endpoints: list[dict[str, Any]],
) -> None:
    endpoint_records = [
        (
            f"{str(ep.get('method', 'GET')).upper()} {ep.get('path', '')}",
            set(endpoint_owned_files(ep)),
        )
        for ep in api_endpoints
    ]

    task_patterns = {
        task.name: [
            re.compile(rf"""\b{re.escape(task.name)}\.(?:delay|apply_async)\s*\("""),
            re.compile(rf"""\b{re.escape(task.name)}::dispatch\s*\("""),
            re.compile(rf"""\bdispatch\s*\(\s*{re.escape(task.name)}\b"""),
            re.compile(rf"""\bdispatch\s*\(\s*new\s+{re.escape(task.name)}\b"""),
            re.compile(rf"""\bevent\s*\(\s*new\s+{re.escape(task.name)}\b"""),
            re.compile(rf"""\bqueue\.add\s*\(\s*['\"]{re.escape(task.name)}['\"]"""),
            *[
                re.compile(rf"""\b{re.escape(trigger)}\.send\s*\(""")
                for trigger in task.triggers
                if trigger
            ],
        ]
        for task in runtime.tasks
        if task.name
    }
    scheduler_patterns = {
        scheduler.name: [
            re.compile(rf"""\b{re.escape(target)}\b""")
            for target in scheduler.invoked_targets
            if target
        ]
        for scheduler in runtime.schedulers
    }

    for file_path, content in file_contents.items():
        if not content:
            continue
        endpoint_keys = sorted(
            key for key, owned_files in endpoint_records if file_path in owned_files
        )
        for task in runtime.tasks:
            patterns = task_patterns.get(task.name, [])
            if not patterns or not any(pattern.search(content) for pattern in patterns):
                continue
            if file_path not in task.producer_files:
                task.producer_files.append(file_path)
            if endpoint_keys:
                task.linked_endpoints = sorted(
                    set(task.linked_endpoints) | set(endpoint_keys)
                )
        for scheduler in runtime.schedulers:
            patterns = scheduler_patterns.get(scheduler.name, [])
            if not patterns or not any(pattern.search(content) for pattern in patterns):
                continue
            if endpoint_keys:
                scheduler.linked_endpoints = sorted(
                    set(scheduler.linked_endpoints) | set(endpoint_keys)
                )


def _discover_celery_tasks(
    file_contents: dict[str, str],
) -> tuple[list[RuntimeTask], list[RuntimeScheduler]]:
    tasks: list[RuntimeTask] = []
    schedulers: list[RuntimeScheduler] = []
    task_pattern = re.compile(
        r"@(?P<decorator>(?:\w+\.)?(?:task|shared_task))(?P<args>\([^\n]*\))?\s*\n(?:async\s+)?def\s+(?P<name>\w+)\s*\(",
        re.MULTILINE,
    )
    queue_pattern = re.compile(r"(?:queue|routing_key)\s*=\s*['\"]([^'\"]+)['\"]")
    trigger_pattern = re.compile(
        r"([A-Za-z_][A-Za-z0-9_]*)\s*\.(delay|apply_async)\s*\("
    )
    beat_dict_pattern = re.compile(
        r"['\"]task['\"]\s*:\s*['\"]([^'\"]+)['\"].*?['\"]schedule['\"]\s*:\s*([^,}\n]+)",
        re.DOTALL,
    )

    for file_path, content in file_contents.items():
        if (
            "celery" not in content
            and "@shared_task" not in content
            and ".delay(" not in content
            and ".apply_async(" not in content
        ):
            continue

        for match in task_pattern.finditer(content):
            args = match.group("args") or ""
            queue_match = queue_pattern.search(args)
            retry_values = [
                key
                for key in (
                    "autoretry_for",
                    "max_retries",
                    "retry_backoff",
                    "default_retry_delay",
                )
                if key in args
            ]
            tasks.append(
                RuntimeTask(
                    name=match.group("name"),
                    file_path=file_path,
                    runtime_kind="celery",
                    decorator=match.group("decorator"),
                    queue=queue_match.group(1) if queue_match else "",
                    retry_policy=", ".join(retry_values[:4]),
                )
            )

        for trigger in trigger_pattern.finditer(content):
            tasks.append(
                RuntimeTask(
                    name=trigger.group(1),
                    file_path=file_path,
                    runtime_kind="celery",
                    triggers=[trigger.group(2)],
                )
            )

        for beat_task, schedule in beat_dict_pattern.findall(content):
            runtime_name = beat_task.split(".")[-1]
            tasks.append(
                RuntimeTask(
                    name=runtime_name,
                    file_path=file_path,
                    runtime_kind="celery",
                    schedule_sources=[schedule.strip()[:120]],
                )
            )
            schedulers.append(
                RuntimeScheduler(
                    name=runtime_name,
                    file_path=file_path,
                    scheduler_type="beat",
                    cron=schedule.strip()[:120],
                    invoked_targets=[beat_task],
                )
            )

    return _dedupe_runtime_tasks(tasks), _dedupe_schedulers(schedulers)


def _discover_schedulers(file_contents: dict[str, str]) -> list[RuntimeScheduler]:
    schedulers: list[RuntimeScheduler] = []
    node_cron_pattern = re.compile(r"cron\.schedule\s*\(\s*['\"]([^'\"]+)['\"]")
    function_call_pattern = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    crontab_pattern = re.compile(r"crontab\s*\(([^)]*)\)")

    for file_path, content in file_contents.items():
        if "cron.schedule" in content or "node-cron" in content:
            for idx, match in enumerate(node_cron_pattern.finditer(content), start=1):
                snippet = content[match.end() : match.end() + 300]
                invoked = []
                for call in function_call_pattern.findall(snippet):
                    if call not in {"if", "for", "while", "switch", "setTimeout"}:
                        invoked.append(call)
                schedulers.append(
                    RuntimeScheduler(
                        name=f"node-cron-{idx}",
                        file_path=file_path,
                        scheduler_type="node_cron",
                        cron=match.group(1),
                        invoked_targets=invoked[:6],
                    )
                )
        if "crontab(" in content:
            for idx, match in enumerate(crontab_pattern.finditer(content), start=1):
                schedulers.append(
                    RuntimeScheduler(
                        name=f"crontab-{idx}",
                        file_path=file_path,
                        scheduler_type="crontab",
                        cron=match.group(1).strip()[:120],
                    )
                )
    return _dedupe_schedulers(schedulers)


def _discover_django_runtime(file_contents: dict[str, str]) -> list[RuntimeTask]:
    tasks: list[RuntimeTask] = []
    command_pattern = re.compile(r"class\s+Command\s*\([^)]*BaseCommand[^)]*\)\s*:")
    receiver_pattern = re.compile(
        r"@receiver\s*\(\s*([A-Za-z_][A-Za-z0-9_.]*)[^\)]*\)\s*\n(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        re.MULTILINE,
    )
    connect_pattern = re.compile(
        r"\b([A-Za-z_][A-Za-z0-9_.]*)\.connect\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)",
    )

    for file_path, content in file_contents.items():
        if "BaseCommand" in content and command_pattern.search(content):
            tasks.append(
                RuntimeTask(
                    name=Path(file_path).stem.replace("_", "-"),
                    file_path=file_path,
                    runtime_kind="django_command",
                    decorator="BaseCommand",
                    triggers=["manage.py"],
                )
            )

        if "@receiver" in content:
            for signal_name, handler_name in receiver_pattern.findall(content):
                tasks.append(
                    RuntimeTask(
                        name=handler_name,
                        file_path=file_path,
                        runtime_kind="django_signal",
                        decorator="receiver",
                        triggers=[signal_name.split(".")[-1]],
                    )
                )

        if ".connect(" in content:
            for signal_name, handler_name in connect_pattern.findall(content):
                tasks.append(
                    RuntimeTask(
                        name=handler_name,
                        file_path=file_path,
                        runtime_kind="django_signal",
                        decorator="connect",
                        triggers=[signal_name.split(".")[-1]],
                    )
                )

    return _dedupe_runtime_tasks(tasks)


def _discover_laravel_runtime(
    file_contents: dict[str, str],
) -> tuple[list[RuntimeTask], list[RuntimeScheduler]]:
    tasks: list[RuntimeTask] = []
    schedulers: list[RuntimeScheduler] = []
    class_pattern = re.compile(r"class\s+([A-Za-z_][A-Za-z0-9_]*)")
    should_queue_pattern = re.compile(
        r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s+implements\s+ShouldQueue"
    )
    handle_event_pattern = re.compile(
        r"function\s+handle\s*\(\s*([\\A-Za-z_][\\A-Za-z0-9_]*)",
    )
    queue_pattern = re.compile(
        r"(?:public|protected)\s+\$queue\s*=\s*['\"]([^'\"]+)['\"]"
    )
    command_schedule_pattern = re.compile(
        r"\$schedule->command\(\s*['\"]([^'\"]+)['\"][^\)]*\)(?P<chain>(?:\s*->\s*[A-Za-z_][A-Za-z0-9_]*\([^\)]*\))+)",
    )
    job_schedule_pattern = re.compile(
        r"\$schedule->job\(\s*(?:new\s+)?([\\A-Za-z_][\\A-Za-z0-9_]*)[^\)]*\)(?P<chain>(?:\s*->\s*[A-Za-z_][A-Za-z0-9_]*\([^\)]*\))+)",
    )
    call_schedule_pattern = re.compile(
        r"\$schedule->call\([^\)]*\)(?P<chain>(?:\s*->\s*[A-Za-z_][A-Za-z0-9_]*\([^\)]*\))+)",
    )

    for file_path, content in file_contents.items():
        lower_file = file_path.lower()
        queue_match = queue_pattern.search(content)

        if "shouldqueue" in content.lower() or "/jobs/" in lower_file:
            for job_name in should_queue_pattern.findall(content):
                tasks.append(
                    RuntimeTask(
                        name=job_name,
                        file_path=file_path,
                        runtime_kind="laravel_job",
                        decorator="ShouldQueue",
                        queue=queue_match.group(1) if queue_match else "",
                    )
                )

        if "/listeners/" in lower_file and "function handle(" in content:
            class_match = class_pattern.search(content)
            event_match = handle_event_pattern.search(content)
            if class_match:
                tasks.append(
                    RuntimeTask(
                        name=class_match.group(1),
                        file_path=file_path,
                        runtime_kind="laravel_listener",
                        decorator="listener",
                        queue=queue_match.group(1) if queue_match else "",
                        triggers=[event_match.group(1).split("\\")[-1]]
                        if event_match
                        else [],
                    )
                )

        if "/events/" in lower_file:
            class_match = class_pattern.search(content)
            if class_match:
                tasks.append(
                    RuntimeTask(
                        name=class_match.group(1),
                        file_path=file_path,
                        runtime_kind="laravel_event",
                        decorator="event",
                    )
                )

        for idx, match in enumerate(
            command_schedule_pattern.finditer(content), start=1
        ):
            command_name = match.group(1)
            schedulers.append(
                RuntimeScheduler(
                    name=f"laravel-command-{idx}",
                    file_path=file_path,
                    scheduler_type="laravel_schedule",
                    cron=_schedule_chain_summary(match.group("chain")),
                    invoked_targets=[command_name],
                )
            )

        for idx, match in enumerate(job_schedule_pattern.finditer(content), start=1):
            job_name = match.group(1).split("\\")[-1]
            schedulers.append(
                RuntimeScheduler(
                    name=f"laravel-job-{idx}",
                    file_path=file_path,
                    scheduler_type="laravel_schedule",
                    cron=_schedule_chain_summary(match.group("chain")),
                    invoked_targets=[job_name],
                )
            )

        for idx, match in enumerate(call_schedule_pattern.finditer(content), start=1):
            schedulers.append(
                RuntimeScheduler(
                    name=f"laravel-call-{idx}",
                    file_path=file_path,
                    scheduler_type="laravel_schedule",
                    cron=_schedule_chain_summary(match.group("chain")),
                    invoked_targets=["closure"],
                )
            )

    return _dedupe_runtime_tasks(tasks), _dedupe_schedulers(schedulers)


def _schedule_chain_summary(chain: str) -> str:
    method_match = re.search(r"->\s*([A-Za-z_][A-Za-z0-9_]*)\(([^\)]*)\)", chain)
    cron_match = re.search(r"->\s*cron\(\s*['\"]([^'\"]+)['\"]\s*\)", chain)
    if cron_match:
        return cron_match.group(1)
    if method_match:
        method = method_match.group(1)
        args = method_match.group(2).strip()
        return f"{method}({args})" if args else method
    return chain.strip()[:120]


def _discover_js_runtime(
    file_contents: dict[str, str],
) -> tuple[list[RuntimeTask], list[RuntimeScheduler]]:
    tasks: list[RuntimeTask] = []
    schedulers: list[RuntimeScheduler] = []
    worker_pattern = re.compile(
        r"new\s+Worker\(\s*['\"]([^'\"]+)['\"]",
    )
    process_pattern = re.compile(
        r"\.(?:process|consume)\s*\(\s*(?:['\"]([^'\"]+)['\"]\s*,)?\s*(?:async\s+)?(?:function\s+([A-Za-z_][A-Za-z0-9_]*)|([A-Za-z_][A-Za-z0-9_]*))",
    )
    agenda_define_pattern = re.compile(
        r"agenda\.define\(\s*['\"]([^'\"]+)['\"]",
    )
    agenda_every_pattern = re.compile(
        r"agenda\.every\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]",
    )

    for file_path, content in file_contents.items():
        lowered = content.lower()
        if not any(
            token in lowered
            for token in (
                "new worker(",
                ".process(",
                ".consume(",
                "agenda.define",
                "agenda.every",
            )
        ):
            continue

        for queue_name in worker_pattern.findall(content):
            tasks.append(
                RuntimeTask(
                    name=queue_name,
                    file_path=file_path,
                    runtime_kind="js_worker",
                    decorator="Worker",
                    queue=queue_name,
                )
            )

        for queue_name, named_handler, bare_handler in process_pattern.findall(content):
            task_name = queue_name or named_handler or bare_handler or "queue-worker"
            tasks.append(
                RuntimeTask(
                    name=task_name,
                    file_path=file_path,
                    runtime_kind="js_worker",
                    decorator="queue_process",
                    queue=queue_name or "",
                )
            )

        for job_name in agenda_define_pattern.findall(content):
            tasks.append(
                RuntimeTask(
                    name=job_name,
                    file_path=file_path,
                    runtime_kind="js_worker",
                    decorator="agenda.define",
                    queue=job_name,
                )
            )

        for cadence, job_name in agenda_every_pattern.findall(content):
            schedulers.append(
                RuntimeScheduler(
                    name=f"agenda-{job_name}",
                    file_path=file_path,
                    scheduler_type="agenda",
                    cron=cadence,
                    invoked_targets=[job_name],
                )
            )

    return _dedupe_runtime_tasks(tasks), _dedupe_schedulers(schedulers)


def _discover_go_runtime(
    file_contents: dict[str, str],
) -> tuple[list[RuntimeTask], list[RuntimeScheduler]]:
    tasks: list[RuntimeTask] = []
    schedulers: list[RuntimeScheduler] = []
    goroutine_pattern = re.compile(r"\bgo\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    add_func_pattern = re.compile(
        r"\.AddFunc\(\s*['\"]([^'\"]+)['\"]\s*,\s*([A-Za-z_][A-Za-z0-9_]*)",
    )
    every_pattern = re.compile(
        r"\.Every\(\s*([0-9]+\s*\*\s*time\.[A-Za-z_]+)\s*\)\.Do\(\s*([A-Za-z_][A-Za-z0-9_]*)",
    )

    for file_path, content in file_contents.items():
        if not file_path.endswith(".go"):
            continue

        for worker_name in goroutine_pattern.findall(content):
            tasks.append(
                RuntimeTask(
                    name=worker_name,
                    file_path=file_path,
                    runtime_kind="go_worker",
                    decorator="goroutine",
                )
            )

        for cron_expr, target in add_func_pattern.findall(content):
            schedulers.append(
                RuntimeScheduler(
                    name=target,
                    file_path=file_path,
                    scheduler_type="go_cron",
                    cron=cron_expr,
                    invoked_targets=[target],
                )
            )
            tasks.append(
                RuntimeTask(
                    name=target,
                    file_path=file_path,
                    runtime_kind="go_worker",
                    decorator="cron.AddFunc",
                    schedule_sources=[cron_expr],
                )
            )

        for cadence, target in every_pattern.findall(content):
            schedulers.append(
                RuntimeScheduler(
                    name=target,
                    file_path=file_path,
                    scheduler_type="go_schedule",
                    cron=cadence,
                    invoked_targets=[target],
                )
            )
            tasks.append(
                RuntimeTask(
                    name=target,
                    file_path=file_path,
                    runtime_kind="go_worker",
                    decorator="Every.Do",
                    schedule_sources=[cadence],
                )
            )

    return _dedupe_runtime_tasks(tasks), _dedupe_schedulers(schedulers)


def _discover_realtime_consumers(
    file_contents: dict[str, str],
) -> list[RealtimeConsumer]:
    consumers: list[RealtimeConsumer] = []
    consumer_pattern = re.compile(
        r"class\s+(\w+)\((AsyncWebsocketConsumer|WebsocketConsumer)\)\s*:"
    )
    route_pattern = re.compile(
        r"re_path\s*\(\s*r?['\"]([^'\"]+)['\"]|path\s*\(\s*['\"]([^'\"]+)['\"]"
    )
    group_pattern = re.compile(r"group_(?:add|discard|send)\s*\(\s*['\"]([^'\"]+)['\"]")
    socket_route_pattern = re.compile(r"\b(?:io|socket)\.on\(\s*['\"]([^'\"]+)['\"]")

    for file_path, content in file_contents.items():
        if (
            "WebsocketConsumer" not in content
            and "AsyncWebsocketConsumer" not in content
            and "ProtocolTypeRouter" not in content
            and "socket.io" not in content.lower()
            and "new WebSocketServer" not in content
            and ".on('connection'" not in content
            and '.on("connection"' not in content
        ):
            continue

        routes = []
        for match in route_pattern.finditer(content):
            route = match.group(1) or match.group(2)
            if route:
                routes.append(route)
        groups = group_pattern.findall(content)
        auth_hints = []
        if "AuthMiddlewareStack" in content:
            auth_hints.append("AuthMiddlewareStack")
        if "scope['user']" in content or 'scope["user"]' in content:
            auth_hints.append("scope_user")

        for match in consumer_pattern.finditer(content):
            consumers.append(
                RealtimeConsumer(
                    name=match.group(1),
                    file_path=file_path,
                    consumer_type=match.group(2),
                    routes=sorted(set(routes))[:10],
                    groups=sorted(set(groups))[:10],
                    auth_hints=auth_hints,
                )
            )
        if not list(consumer_pattern.finditer(content)) and socket_route_pattern.search(
            content
        ):
            routes = sorted(
                {route for route in socket_route_pattern.findall(content) if route}
            )[:10]
            consumer_type = (
                "socket_io" if "socket.io" in content.lower() else "websocket"
            )
            consumers.append(
                RealtimeConsumer(
                    name=Path(file_path).stem,
                    file_path=file_path,
                    consumer_type=consumer_type,
                    routes=routes,
                    groups=[],
                    auth_hints=["socket_connection"] if "connection" in routes else [],
                )
            )
    return _dedupe_consumers(consumers)


def _dedupe_runtime_tasks(tasks: list[RuntimeTask]) -> list[RuntimeTask]:
    by_key: dict[tuple[str, str, str], RuntimeTask] = {}
    for task in tasks:
        key = (task.file_path, task.name, task.runtime_kind)
        existing = by_key.get(key)
        if not existing:
            by_key[key] = task
            continue
        existing.schedule_sources = sorted(
            set(existing.schedule_sources + task.schedule_sources)
        )
        existing.triggers = sorted(set(existing.triggers + task.triggers))
        existing.producer_files = sorted(
            set(existing.producer_files + task.producer_files)
        )
        existing.linked_endpoints = sorted(
            set(existing.linked_endpoints + task.linked_endpoints)
        )
        if not existing.queue:
            existing.queue = task.queue
        if not existing.retry_policy:
            existing.retry_policy = task.retry_policy
        if not existing.decorator:
            existing.decorator = task.decorator
    return list(by_key.values())


def _dedupe_schedulers(schedulers: list[RuntimeScheduler]) -> list[RuntimeScheduler]:
    seen: dict[tuple[str, str, str, str], RuntimeScheduler] = {}
    for scheduler in schedulers:
        key = (
            scheduler.file_path,
            scheduler.name,
            scheduler.scheduler_type,
            scheduler.cron,
        )
        existing = seen.get(key)
        if not existing:
            seen[key] = scheduler
            continue
        existing.invoked_targets = sorted(
            set(existing.invoked_targets + scheduler.invoked_targets)
        )
        existing.linked_endpoints = sorted(
            set(existing.linked_endpoints + scheduler.linked_endpoints)
        )
    return list(seen.values())


def _dedupe_consumers(consumers: list[RealtimeConsumer]) -> list[RealtimeConsumer]:
    seen: dict[tuple[str, str], RealtimeConsumer] = {}
    for consumer in consumers:
        seen[(consumer.file_path, consumer.name)] = consumer
    return list(seen.values())


from .utils import endpoint_owned_files
