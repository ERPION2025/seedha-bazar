from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import audit
from accounts.errors import ApiError
from accounts.models import User, UserStatus
from accounts.permissions import IsAgent, IsBuyer, IsFarmer
from accounts.views import user_summary

from . import services
from .models import FarmerProfile, LinkStatus, OrgLinkRequest, Organisation
from .serializers import (AssistedFarmerSerializer, BuyerProfileSerializer, FarmerProfileSerializer,
                          JoinOrgSerializer, LinkRequestSerializer, MeSerializer, OrganisationPublicSerializer)


class MeView(APIView):
    def get(self, request):
        return Response(user_summary(request.user))

    def patch(self, request):
        s = MeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if "language" in s.validated_data:
            request.user.language = s.validated_data["language"]
            request.user.save(update_fields=["language"])
        return Response(user_summary(request.user))


class DeleteAccountView(APIView):
    def post(self, request):
        if request.data.get("confirm") != "DELETE":
            raise ApiError("confirm_required", 'Send {"confirm": "DELETE"} to delete the account', 400)
        services.delete_account(request.user, request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class FarmerMeView(APIView):
    permission_classes = [IsFarmer]

    def get(self, request):
        return Response(FarmerProfileSerializer(request.user.farmer_profile).data)

    def patch(self, request):
        s = FarmerProfileSerializer(request.user.farmer_profile, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        audit.log("farmer_profile_updated", actor=request.user, target=request.user.farmer_profile, request=request, fields=sorted(request.data.keys()))
        return Response(s.data)


class BuyerMeView(APIView):
    permission_classes = [IsBuyer]

    def get(self, request):
        return Response(BuyerProfileSerializer(request.user.buyer_profile).data)

    def patch(self, request):
        s = BuyerProfileSerializer(request.user.buyer_profile, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)


class OrgListView(APIView):
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        qs = Organisation.objects.filter(verified=True)
        if q:
            qs = qs.filter(name__icontains=q)
        return Response({"organisations": OrganisationPublicSerializer(qs.order_by("name")[:30], many=True).data})


class JoinOrgView(APIView):
    permission_classes = [IsFarmer]

    def post(self, request):
        s = JoinOrgSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        link = services.request_join(request.user.farmer_profile, s.validated_data["org_code"], request)
        return Response({"id": link.pk, "status": link.status}, status=status.HTTP_201_CREATED)


class AgentFarmersView(APIView):
    permission_classes = [IsAgent]

    def get(self, request):
        orgs = services.agent_orgs(request.user)
        qs = FarmerProfile.objects.filter(organisation__in=orgs).select_related("user", "organisation").order_by("-updated_at")
        rows = [{"id": f.user_id, "phone": f.user.phone, "status": f.user.status, "organisation": f.organisation.name,
                 **FarmerProfileSerializer(f).data} for f in qs[:200]]
        return Response({"farmers": rows})

    def post(self, request):
        s = AssistedFarmerSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = services.create_assisted_farmer(request.user, dict(s.validated_data), request)
        return Response({"id": user.pk, "status": user.status, "message": "A code was sent to the farmer's phone. The farmer must confirm it to activate the account."}, status=status.HTTP_201_CREATED)


class AgentResendView(APIView):
    permission_classes = [IsAgent]

    def post(self, request, user_id):
        farmer = get_object_or_404(User, pk=user_id)
        channel = request.data.get("channel", "sms")
        return Response(services.resend_confirmation(request.user, farmer, channel, request))


class AgentLinkRequestsView(APIView):
    permission_classes = [IsAgent]

    def get(self, request):
        orgs = services.agent_orgs(request.user)
        st = request.query_params.get("status", LinkStatus.PENDING)
        qs = OrgLinkRequest.objects.filter(organisation__in=orgs, status=st).select_related("farmer__user", "organisation")
        return Response({"requests": LinkRequestSerializer(qs, many=True).data})


class AgentLinkDecisionView(APIView):
    permission_classes = [IsAgent]
    approve = True

    def post(self, request, pk):
        link = get_object_or_404(OrgLinkRequest.objects.select_related("farmer__user", "organisation"), pk=pk)
        services.decide_join(request.user, link, self.approve, request)
        return Response({"id": link.pk, "status": link.status})
