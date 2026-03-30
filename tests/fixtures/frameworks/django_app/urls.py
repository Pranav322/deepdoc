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
