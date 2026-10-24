"""Public JSON for the future app and other tools: today's mandi rates. No sign-in needed."""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.errors import ApiError

from . import services
from .crops import CROPS
from .serialize import quote_json


class Open(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]


class QuoteView(Open):
    """GET /api/rates/?crop=wheat&state=Madhya Pradesh&district=Rewa"""

    def get(self, request):
        crop = (request.query_params.get("crop") or "").lower()
        if crop not in CROPS:
            raise ApiError("unknown_crop", "crop must be one of: " + ", ".join(CROPS))
        q = services.quote(crop, request.query_params.get("state", "").strip(), request.query_params.get("district", "").strip())
        return Response(quote_json(q))


class PlacesView(Open):
    def get(self, request):
        return Response({"places": services.places()})


class CropsView(Open):
    def get(self, request):
        rows = services.crop_prices(request.query_params.get("state", "").strip(), request.query_params.get("district", "").strip())
        return Response({"crops": [{"crop": r["crop"], "label": CROPS[r["crop"]], "typical": int(r["typical"]), "as_of": r["as_of"].isoformat()} for r in rows]})
