from __future__ import annotations

from pathlib import Path

from deepdoc.parser.routes.base import RouteResolverContext
from deepdoc.parser.routes.laravel import detect_laravel
from deepdoc.parser.routes.nestjs import detect_nestjs
from deepdoc.parser.routes.repo_resolver import resolve_repo_endpoints


def test_nestjs_composes_global_prefix_with_controller_and_handler() -> None:
    controller_content = (
        "@Controller('users')\n"
        "export class UsersController {\n"
        "  @Get(':id')\n"
        "  findOne() {}\n"
        "}\n"
    )
    main_content = (
        "async function bootstrap() {\n"
        "  const app = await NestFactory.create(AppModule);\n"
        "  app.setGlobalPrefix('api');\n"
        "}\n"
    )
    ctx = RouteResolverContext(
        path=Path("src/users.controller.ts"),
        content=controller_content,
        language="typescript",
    )
    endpoints = detect_nestjs(ctx)
    for ep in endpoints:
        ep.route_file = str(ctx.path)
        ep.framework = "nestjs"

    file_contents = {
        "src/users.controller.ts": controller_content,
        "src/main.ts": main_content,
    }
    resolved = resolve_repo_endpoints(Path("."), endpoints, file_contents)

    assert len(resolved) == 1
    assert resolved[0].path == "/api/users/:id"


def test_nestjs_skips_global_prefix_when_ambiguous() -> None:
    controller_content = "@Controller('users')\nexport class UsersController {\n  @Get()\n  findAll() {}\n}\n"
    conflicting_main = (
        "app.setGlobalPrefix('api');\n"
        "if (env) { app.setGlobalPrefix('v2'); }\n"
    )
    ctx = RouteResolverContext(
        path=Path("src/users.controller.ts"),
        content=controller_content,
        language="typescript",
    )
    endpoints = detect_nestjs(ctx)
    for ep in endpoints:
        ep.route_file = str(ctx.path)
        ep.framework = "nestjs"

    file_contents = {
        "src/users.controller.ts": controller_content,
        "src/main.ts": conflicting_main,
    }
    resolved = resolve_repo_endpoints(Path("."), endpoints, file_contents)

    assert resolved[0].path == "/users"


def test_laravel_fluent_prefix_group_composes_correctly() -> None:
    content = (
        "Route::prefix('api')->group(function () {\n"
        "    Route::get('/users', 'UserController@index');\n"
        "});\n"
    )
    ctx = RouteResolverContext(
        path=Path("routes/web.php"), content=content, language="php"
    )

    endpoints = detect_laravel(ctx)

    assert len(endpoints) == 1
    assert endpoints[0].path == "/api/users"


def test_laravel_array_style_group_still_composes() -> None:
    content = (
        "Route::group(['prefix' => 'admin'], function () {\n"
        "    Route::get('/dashboard', 'DashboardController@index');\n"
        "});\n"
    )
    ctx = RouteResolverContext(
        path=Path("routes/web.php"), content=content, language="php"
    )

    endpoints = detect_laravel(ctx)

    assert len(endpoints) == 1
    assert endpoints[0].path == "/admin/dashboard"
