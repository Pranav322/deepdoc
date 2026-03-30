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
