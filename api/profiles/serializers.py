from rest_framework import serializers

from accounts.models import Language
from accounts.views import PhoneField

from .models import BuyerProfile, FarmerProfile, OrgLinkRequest, Organisation


class CropListField(serializers.ListField):
    child = serializers.CharField(max_length=40)

    def __init__(self, **kw):
        super().__init__(max_length=20, **kw)


class FarmerProfileSerializer(serializers.ModelSerializer):
    crops = CropListField(required=False)
    organisation = serializers.SerializerMethodField()
    assisted_by = serializers.SerializerMethodField()

    class Meta:
        model = FarmerProfile
        fields = ["name", "village", "block", "district", "state", "land_acres", "crops", "contact_is_family",
                  "family_contact_name", "level", "org_status", "organisation", "assisted_by"]
        read_only_fields = ["level", "org_status"]

    def get_organisation(self, obj):
        return {"id": obj.organisation_id, "name": obj.organisation.name} if obj.organisation_id else None

    def get_assisted_by(self, obj):
        return obj.assisted_by_id is not None

    def validate_land_acres(self, v):
        if v is not None and (v <= 0 or v > 100000):
            raise serializers.ValidationError("Enter a sensible land size in acres")
        return v


class BuyerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = BuyerProfile
        fields = ["contact_name", "business_name", "business_type", "city", "gstin", "fssai", "level"]
        read_only_fields = ["level"]

    def validate_gstin(self, v):
        v = v.strip().upper()
        if v and len(v) != 15:
            raise serializers.ValidationError("GSTIN has 15 characters")
        return v

    def validate_fssai(self, v):
        v = v.strip()
        if v and (len(v) != 14 or not v.isdigit()):
            raise serializers.ValidationError("FSSAI number has 14 digits")
        return v


class MeSerializer(serializers.Serializer):
    language = serializers.ChoiceField(choices=Language.values, required=False)


class OrganisationPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organisation
        fields = ["id", "name", "kind", "district", "block"]


class JoinOrgSerializer(serializers.Serializer):
    org_code = serializers.CharField(max_length=20)


class AssistedFarmerSerializer(FarmerProfileSerializer):
    phone = PhoneField(write_only=True)
    org_code = serializers.CharField(max_length=20, required=False, write_only=True)
    language = serializers.ChoiceField(choices=Language.values, required=False, write_only=True)
    channel = serializers.ChoiceField(choices=["sms", "whatsapp", "voice"], required=False, write_only=True)

    class Meta(FarmerProfileSerializer.Meta):
        fields = FarmerProfileSerializer.Meta.fields + ["phone", "org_code", "language", "channel"]


class LinkRequestSerializer(serializers.ModelSerializer):
    farmer_name = serializers.CharField(source="farmer.name")
    farmer_phone = serializers.CharField(source="farmer.user.phone")
    organisation_name = serializers.CharField(source="organisation.name")

    class Meta:
        model = OrgLinkRequest
        fields = ["id", "farmer_name", "farmer_phone", "organisation_name", "status", "created_at"]
