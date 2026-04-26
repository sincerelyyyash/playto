from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token


def healthz(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz),
    path("api/v1/auth/token/", obtain_auth_token, name="api-token-auth"),
    path("api/v1/", include("apps.merchants.urls")),
    path("api/v1/", include("apps.payouts.urls")),
]
