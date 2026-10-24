from rest_framework.permissions import BasePermission

from .models import Role, UserStatus


class HasRole(BasePermission):
    roles: tuple = ()

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.status == UserStatus.ACTIVE and u.role in self.roles)


class IsFarmer(HasRole):
    roles = (Role.FARMER,)


class IsBuyer(HasRole):
    roles = (Role.BUYER,)


class IsAgent(HasRole):
    roles = (Role.AGENT,)
