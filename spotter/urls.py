from django.urls import include, path
from django.utils.csp import CSP
from django.views.decorators.csp import csp_override
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerSplitView

SWAGGER_CDN = "https://cdn.jsdelivr.net"
# The only inline <style> in drf-spectacular 0.30's Swagger template; re-hash on upgrade.
SWAGGER_INLINE_STYLE = "'sha256-MMpT0iDxyjALd9PdfepImGX3DBfJPXZ4IlDWdPAgtn0='"

docs_view = csp_override(
    {
        "default-src": [CSP.NONE],
        "script-src": [CSP.SELF, SWAGGER_CDN],
        "style-src": [SWAGGER_CDN, SWAGGER_INLINE_STYLE],
        "img-src": [SWAGGER_CDN, "data:"],
        "connect-src": [CSP.SELF],
        "base-uri": [CSP.NONE],
        "frame-ancestors": [CSP.NONE],
    }
)(SpectacularSwaggerSplitView.as_view(url_name="schema"))

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="docs")),
    path("", include("routefuel.urls")),
    path("api/schema", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs", docs_view, name="docs"),
]
