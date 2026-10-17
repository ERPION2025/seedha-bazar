from accounts.models import Role

from .models import BuyerProfile, FarmerProfile


def create_profile(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.role == Role.FARMER:
        FarmerProfile.objects.get_or_create(user=instance)
    elif instance.role == Role.BUYER:
        BuyerProfile.objects.get_or_create(user=instance)
