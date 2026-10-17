import jwt
from rest_framework import authentication, exceptions

from . import tokens
from .models import Device


class DeviceJWTAuthentication(authentication.BaseAuthentication):
    """Bearer access token tied to a device. Revoking the device kills the token at once."""

    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword.lower().encode():
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed("Bad Authorization header")
        try:
            claims = tokens.decode_access(header[1].decode())
        except jwt.ExpiredSignatureError:
            raise exceptions.AuthenticationFailed("Access token expired")
        except jwt.PyJWTError:
            raise exceptions.AuthenticationFailed("Invalid access token")
        if claims.get("typ") != "access":
            raise exceptions.AuthenticationFailed("Invalid access token")
        device = Device.objects.select_related("user").filter(pk=claims["did"], user_id=claims["sub"]).first()
        if device is None or not device.is_active or not device.user.is_active:
            raise exceptions.AuthenticationFailed("Session ended")
        request.device = device
        return device.user, claims

    def authenticate_header(self, request):
        return self.keyword
