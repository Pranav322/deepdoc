"""Framework-specific parser and scan regression tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from codewiki.config import DEFAULT_CONFIG
from codewiki.parser.api_detector import detect_endpoints
from codewiki.planner_v2 import scan_repo


def test_django_detects_class_views_and_drf_router_actions():
    content = """
from django.urls import include, path, re_path
from django.views import View
from rest_framework.decorators import action, api_view
from rest_framework.routers import DefaultRouter
from rest_framework.viewsets import ModelViewSet


@api_view(["GET", "POST"])
def health(request):
    pass


class ReportView(View):
    def get(self, request, slug):
        pass


class UserViewSet(ModelViewSet):
    def list(self, request):
        pass

    def retrieve(self, request, pk=None):
        pass

    def create(self, request):
        pass

    def destroy(self, request, pk=None):
        pass

    @action(detail=True, methods=["GET"], url_path="stats")
    def stats(self, request, pk=None):
        pass


router = DefaultRouter()
router.register("users", UserViewSet, basename="user")

urlpatterns = [
    path("health/", health),
    re_path(r"^reports/(?P<slug>[-\\w]+)/$", ReportView.as_view()),
    path("api/", include(router.urls)),
]
"""

    endpoints = detect_endpoints(Path("urls.py"), content, "python")
    method_paths = {(ep.method, ep.path, ep.handler) for ep in endpoints}

    assert ("GET", "/health", "health") in method_paths
    assert ("POST", "/health", "health") in method_paths
    assert ("GET", "/reports/{slug}", "ReportView") in method_paths
    assert ("GET", "/api/users", "UserViewSet.list") in method_paths
    assert ("POST", "/api/users", "UserViewSet.create") in method_paths
    assert ("GET", "/api/users/{id}", "UserViewSet.retrieve") in method_paths
    assert ("DELETE", "/api/users/{id}", "UserViewSet.destroy") in method_paths
    assert ("GET", "/api/users/{id}/stats", "UserViewSet.stats") in method_paths


def test_django_detects_sync_to_async_wrapped_async_and_generic_views():
    content = """
from django.urls import path
from django.views.generic import View, ListView
from POSAdmin.connection_handler import sync_to_async


class StoresDataView(ListView):
    model = object


class OrderNotificationView(View):
    async def post(self, request):
        pass


urlpatterns = [
    path("", sync_to_async(StoresDataView.as_view(), thread_sensitive=False)),
    path("order-notification/", sync_to_async(OrderNotificationView.as_view(), thread_sensitive=False)),
]
"""

    endpoints = detect_endpoints(Path("urls.py"), content, "python")
    method_paths = {(ep.method, ep.path, ep.handler) for ep in endpoints}

    assert ("GET", "/", "StoresDataView") in method_paths
    assert ("POST", "/order-notification", "OrderNotificationView") in method_paths


def test_django_infers_function_view_methods_from_request_usage():
    content = """
from django.urls import path


def add_machine(request):
    if request.method == "POST":
        return None
    return None


def list_records(request):
    value = request.GET.get("q")
    return value


urlpatterns = [
    path("add-machine/", add_machine),
    path("records/", list_records),
]
"""

    endpoints = detect_endpoints(Path("urls.py"), content, "python")
    method_paths = {(ep.method, ep.path, ep.handler) for ep in endpoints}

    assert ("POST", "/add-machine", "add_machine") in method_paths
    assert ("GET", "/records", "list_records") in method_paths


def test_express_detects_mounted_router_prefixes_and_chained_routes():
    content = """
const express = require('express')
const app = express()
const router = express.Router()
const adminRouter = express.Router()

router.route('/users').get(auth, listUsers).post(createUser)
adminRouter.get('/stats', requireAdmin, statsHandler)
router.use('/admin', adminRouter)
app.use('/api/v1', router)
"""

    endpoints = detect_endpoints(Path("server.js"), content, "javascript")
    method_paths = {(ep.method, ep.path, ep.handler) for ep in endpoints}

    assert ("GET", "/api/v1/users", "listUsers") in method_paths
    assert ("POST", "/api/v1/users", "createUser") in method_paths
    assert ("GET", "/api/v1/admin/stats", "statsHandler") in method_paths


def test_fastify_detects_registered_plugin_prefixes_and_schema():
    content = """
const fastify = require('fastify')()

async function apiRoutes(instance) {
  instance.get('/users', {
    schema: {
      body: { type: 'object' },
      response: { 200: { type: 'object' } },
    },
  }, listUsers)

  instance.route({
    method: 'POST',
    url: '/users',
    schema: {
      body: { type: 'object' },
      response: { 201: { type: 'object' } },
    },
    handler: createUser,
  })
}

fastify.register(apiRoutes, { prefix: '/api/v1' })
"""

    endpoints = detect_endpoints(Path("server.js"), content, "javascript")
    by_key = {(ep.method, ep.path): ep for ep in endpoints}

    assert ("GET", "/api/v1/users") in by_key
    assert ("POST", "/api/v1/users") in by_key
    assert by_key[("GET", "/api/v1/users")].request_body
    assert by_key[("GET", "/api/v1/users")].response_type
    assert by_key[("POST", "/api/v1/users")].handler == "createUser"


def test_scan_repo_detects_vue_projects_and_sfc_signals(tmp_path):
    repo_root = tmp_path / "vue-app"
    component_dir = repo_root / "src" / "components"
    component_dir.mkdir(parents=True)

    (repo_root / "package.json").write_text(
        '{"dependencies": {"vue": "^3.4.0", "vue-router": "^4.3.0", "pinia": "^2.1.0"}}',
        encoding="utf-8",
    )
    (component_dir / "UserList.vue").write_text(
        """
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useUsersStore } from '@/stores/users'
import { useFeatureFlag } from '@/composables/feature'

defineOptions({ name: 'UserList' })
const props = defineProps<{ teamId: string }>()
const emit = defineEmits(['select'])
const model = defineModel<string>('selectedId')
defineSlots<{ default: (props: { active: boolean }) => any }>()

const route = useRoute()
const router = useRouter()
const usersStore = useUsersStore()
const userRefs = storeToRefs(usersStore)
const users = computed(() => [])
</script>

<template>
  <UserCard />
  <slot name="default" />
</template>
""",
        encoding="utf-8",
    )

    cfg = deepcopy(DEFAULT_CONFIG)
    scan = scan_repo(repo_root, cfg)

    assert "vue" in scan.frameworks_detected
    assert scan.languages.get("vue") == 1

    parsed = scan.parsed_files["src/components/UserList.vue"]
    symbol_names = {symbol.name for symbol in parsed.symbols}

    assert "UserList" in symbol_names
    assert "props" in symbol_names
    assert "emit" in symbol_names
    assert "model" in symbol_names
    assert "slots" in symbol_names
    assert "components" in symbol_names
    assert "router" in symbol_names
    assert "route" in symbol_names
    assert "pinia" in symbol_names


def test_scan_repo_resolves_express_mounts_across_files(tmp_path):
    repo_root = tmp_path / "sync-app"
    routes_dir = repo_root / "src" / "api" / "routes"
    controllers_dir = repo_root / "src" / "api" / "controllers"
    routes_dir.mkdir(parents=True)
    controllers_dir.mkdir(parents=True)

    (repo_root / "index.js").write_text(
        """
const express = require('express');
const apiRoutes = require('./src/api/routes');
const app = express();

app.use('/api/v1', apiRoutes);
""",
        encoding="utf-8",
    )
    (routes_dir / "index.js").write_text(
        """
const express = require('express');
const webhookRoutes = require('./webhookRoutes');
const router = express.Router();

router.use('/webhook', webhookRoutes);
module.exports = router;
""",
        encoding="utf-8",
    )
    (routes_dir / "webhookRoutes.js").write_text(
        """
const express = require('express');
const webhookController = require('../controllers/webhookController');
const router = express.Router();

router.post('/orderstatus', webhookController.handleOrderStatus);
module.exports = router;
""",
        encoding="utf-8",
    )
    (controllers_dir / "webhookController.js").write_text(
        """
exports.handleOrderStatus = (req, res) => res.json({ ok: true });
""",
        encoding="utf-8",
    )

    scan = scan_repo(repo_root, deepcopy(DEFAULT_CONFIG))
    endpoint = next(
        ep for ep in scan.api_endpoints if ep["handler"] == "webhookController.handleOrderStatus"
    )

    assert endpoint["method"] == "POST"
    assert endpoint["path"] == "/api/v1/webhook/orderstatus"
    assert endpoint["route_file"] == "src/api/routes/webhookRoutes.js"
    assert endpoint["handler_file"] == "src/api/controllers/webhookController.js"
    assert endpoint["file"] == "src/api/controllers/webhookController.js"


def test_scan_repo_resolves_falcon_prefixes_and_imported_resources(tmp_path):
    repo_root = tmp_path / "falcon-app"
    controllers_dir = repo_root / "controllers"
    controllers_dir.mkdir(parents=True)

    (repo_root / "settings.py").write_text(
        """
API_PREFIX = '/api/v2'
NEW_API_PREFIX = '/api/v3'
""",
        encoding="utf-8",
    )
    (repo_root / "main.py").write_text(
        """
import falcon
import settings
from controllers import AuthController

app = falcon.App()
app.add_route(settings.API_PREFIX + '/login', AuthController.Login())
app.add_route(settings.NEW_API_PREFIX + '/login', AuthController.RecaptchaLogin())
""",
        encoding="utf-8",
    )
    (controllers_dir / "AuthController.py").write_text(
        """
class Login:
    def on_get(self, req, res):
        pass

    def on_post(self, req, res):
        pass


class RecaptchaLogin:
    def on_post(self, req, res):
        pass
""",
        encoding="utf-8",
    )

    scan = scan_repo(repo_root, deepcopy(DEFAULT_CONFIG))
    method_paths = {
        (ep["method"], ep["path"], ep["handler"], ep["handler_file"]) for ep in scan.api_endpoints
    }

    assert (
        "GET",
        "/api/v2/login",
        "AuthController.Login.on_get",
        "controllers/AuthController.py",
    ) in method_paths
    assert (
        "POST",
        "/api/v2/login",
        "AuthController.Login.on_post",
        "controllers/AuthController.py",
    ) in method_paths
    assert (
        "POST",
        "/api/v3/login",
        "AuthController.RecaptchaLogin.on_post",
        "controllers/AuthController.py",
    ) in method_paths


def test_scan_repo_ignores_commented_falcon_routes(tmp_path):
    repo_root = tmp_path / "falcon-comments"
    controllers_dir = repo_root / "controllers"
    controllers_dir.mkdir(parents=True)

    (repo_root / "settings.py").write_text(
        """
API_PREFIX = '/api/v2'
""",
        encoding="utf-8",
    )
    (repo_root / "main.py").write_text(
        """
import falcon
import settings
from controllers import AuthController

app = falcon.App()
app.add_route(settings.API_PREFIX + '/login', AuthController.Login())
# app.add_route(settings.API_PREFIX + '/logout', AuthController.Logout())
""",
        encoding="utf-8",
    )
    (controllers_dir / "AuthController.py").write_text(
        """
class Login:
    def on_post(self, req, res):
        pass


class Logout:
    def on_post(self, req, res):
        pass
""",
        encoding="utf-8",
    )

    scan = scan_repo(repo_root, deepcopy(DEFAULT_CONFIG))
    method_paths = {(ep["method"], ep["path"]) for ep in scan.api_endpoints}

    assert ("POST", "/api/v2/login") in method_paths
    assert ("POST", "/api/v2/logout") not in method_paths


def test_scan_repo_resolves_django_nested_includes_and_settings_prefixes(tmp_path):
    repo_root = tmp_path / "django-app"
    project_dir = repo_root / "project"
    refund_dir = repo_root / "OrderRefund"
    status_dir = repo_root / "OrderReturnStatus"
    project_dir.mkdir(parents=True)
    refund_dir.mkdir(parents=True)
    status_dir.mkdir(parents=True)

    (project_dir / "settings.py").write_text(
        """
APP_URL = "api/v2/"
ROOT_URLCONF = "project.urls"
""",
        encoding="utf-8",
    )
    (project_dir / "urls.py").write_text(
        '''
"""Example docs:
path("blog/", include("blog.urls"))
path("", views.home)
"""
from django.conf import settings
from django.urls import path, include
app_url = settings.APP_URL

urlpatterns = [
    path(app_url, include([
        path("orderrefund/", include("OrderRefund.urls")),
    ]))
]
''',
        encoding="utf-8",
    )
    (refund_dir / "urls.py").write_text(
        """
from django.urls import path, include
from django.views.decorators.csrf import csrf_exempt
from OrderRefund import views

urlpatterns = [
    path("order_return/", csrf_exempt(views.make_vinculum_order_return_request_wraper)),
    path("order_return_status/", include("OrderReturnStatus.urls")),
    path("get-prod-variants/<str:prod_slug>", csrf_exempt(views.get_prod_var_stocks)),
]
""",
        encoding="utf-8",
    )
    (refund_dir / "views.py").write_text(
        """
def make_vinculum_order_return_request_wraper(request):
    return None


def get_prod_var_stocks(request, prod_slug):
    return None
""",
        encoding="utf-8",
    )
    (status_dir / "urls.py").write_text(
        """
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from OrderReturnStatus import views

urlpatterns = [
    path("return/", csrf_exempt(views.return_status_update)),
]
""",
        encoding="utf-8",
    )
    (status_dir / "views.py").write_text(
        """
def return_status_update(request):
    return None
""",
        encoding="utf-8",
    )

    scan = scan_repo(repo_root, deepcopy(DEFAULT_CONFIG))
    endpoints = {(ep["path"], ep["handler"], ep["handler_file"]) for ep in scan.api_endpoints}
    paths = {ep["path"] for ep in scan.api_endpoints}

    assert (
        "/api/v2/orderrefund/order_return",
        "make_vinculum_order_return_request_wraper",
        "OrderRefund/views.py",
    ) in endpoints
    assert (
        "/api/v2/orderrefund/order_return_status/return",
        "return_status_update",
        "OrderReturnStatus/views.py",
    ) in endpoints
    assert (
        "/api/v2/orderrefund/get-prod-variants/{prod_slug}",
        "get_prod_var_stocks",
        "OrderRefund/views.py",
    ) in endpoints
    assert "/blog" not in paths
    assert "/" not in paths


def test_scan_repo_resolves_django_sync_wrapped_imported_views_and_datatables(tmp_path):
    repo_root = tmp_path / "django-pos"
    project_dir = repo_root / "project"
    order_dir = repo_root / "order"
    datatable_dir = order_dir / "datatables"
    project_dir.mkdir(parents=True)
    datatable_dir.mkdir(parents=True)

    (project_dir / "settings.py").write_text(
        """
ROOT_URLCONF = "project.urls"
""",
        encoding="utf-8",
    )
    (project_dir / "urls.py").write_text(
        """
from django.urls import include, path

urlpatterns = [
    path("orders/", include("order.urls")),
]
""",
        encoding="utf-8",
    )
    (repo_root / "POSAdmin").mkdir(parents=True)
    (repo_root / "POSAdmin" / "connection_handler.py").write_text(
        """
sync_to_async = None
""",
        encoding="utf-8",
    )
    (order_dir / "urls.py").write_text(
        """
from django.urls import path
from order import views as order_views
from order.datatables import orders_datatable
from POSAdmin.connection_handler import sync_to_async

urlpatterns = [
    path("ajax-online-order/", sync_to_async(order_views.AjaxOnlineOrderView.as_view(), thread_sensitive=False)),
    path("ajax-order-list/", sync_to_async(orders_datatable.AjaxOrderListView.as_view(), thread_sensitive=False)),
]
""",
        encoding="utf-8",
    )
    (order_dir / "views.py").write_text(
        """
from django.views.generic import View


class AjaxOnlineOrderView(View):
    async def post(self, request):
        pass
""",
        encoding="utf-8",
    )
    (datatable_dir / "orders_datatable.py").write_text(
        """
from django.views.generic import View


class AjaxOrderListView(View):
    def post(self, request):
        pass
""",
        encoding="utf-8",
    )

    scan = scan_repo(repo_root, deepcopy(DEFAULT_CONFIG))
    endpoints = {
        (ep["method"], ep["path"], ep["handler"], ep["handler_file"])
        for ep in scan.api_endpoints
    }

    assert (
        "POST",
        "/orders/ajax-online-order",
        "AjaxOnlineOrderView",
        "order/views.py",
    ) in endpoints
    assert (
        "POST",
        "/orders/ajax-order-list",
        "AjaxOrderListView",
        "order/datatables/orders_datatable.py",
    ) in endpoints


def test_scan_repo_resolves_django_multiline_imported_datatable_handlers(tmp_path):
    repo_root = tmp_path / "django-report"
    project_dir = repo_root / "project"
    report_dir = repo_root / "report"
    datatable_dir = report_dir / "datatables"
    project_dir.mkdir(parents=True)
    datatable_dir.mkdir(parents=True)

    (project_dir / "settings.py").write_text(
        """
ROOT_URLCONF = "project.urls"
""",
        encoding="utf-8",
    )
    (project_dir / "urls.py").write_text(
        """
from django.urls import include, path

urlpatterns = [
    path("reports/", include("report.urls")),
]
""",
        encoding="utf-8",
    )
    (repo_root / "POSAdmin").mkdir(parents=True)
    (repo_root / "POSAdmin" / "connection_handler.py").write_text(
        """
sync_to_async = None
""",
        encoding="utf-8",
    )
    (report_dir / "urls.py").write_text(
        """
from django.urls import path
from POSAdmin.connection_handler import sync_to_async
from report.datatables import (
    export_datatable,
)

urlpatterns = [
    path("ajax-export-logs/", sync_to_async(export_datatable.AjaxExportLogsView.as_view(), thread_sensitive=False)),
]
""",
        encoding="utf-8",
    )
    (datatable_dir / "export_datatable.py").write_text(
        """
from django.views.generic import View


class AjaxExportLogsView(View):
    def post(self, request):
        pass
""",
        encoding="utf-8",
    )

    scan = scan_repo(repo_root, deepcopy(DEFAULT_CONFIG))
    endpoints = {
        (ep["method"], ep["path"], ep["handler"], ep["handler_file"])
        for ep in scan.api_endpoints
    }

    assert (
        "POST",
        "/reports/ajax-export-logs",
        "AjaxExportLogsView",
        "report/datatables/export_datatable.py",
    ) in endpoints
