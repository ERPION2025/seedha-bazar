"""How an application reaches an insurer.

There is no public API for enrolling farmers in PMFBY. Banks, Common Service Centres and authorised intermediaries
connect to the national portal under an agreement with the government. Until Seedha Bazar has such an agreement,
the `manual` connector prepares everything and the farmer or FPO submits it at a bank, CSC or pmfby.gov.in, then
records the application number here. When a partner connection is signed, add a connector class with the same
methods and set INSURANCE_CONNECTOR to its name.
"""
from django.conf import settings


class NotConnected(Exception):
    pass


class ManualConnector:
    name = "manual"
    live = False

    def submit(self, application) -> dict:
        """Nothing is sent anywhere. The person submits it themselves and tells us the number."""
        return {"sent": False, "next": "submit_yourself"}

    def status(self, application) -> dict:
        return {"status": application.status}


class PortalPartnerConnector:
    """Placeholder for an authorised connection to the national crop insurance portal. Needs credentials from the partner agreement."""

    name = "pmfby_partner"
    live = True

    def __init__(self):
        if not getattr(settings, "PMFBY_PARTNER_KEY", ""):
            raise NotConnected("The crop insurance portal connection is not set up. It needs a partner agreement and credentials.")

    def submit(self, application) -> dict:  # pragma: no cover - needs the partner's API documentation
        raise NotConnected("Partner API not implemented yet.")

    def status(self, application) -> dict:  # pragma: no cover
        raise NotConnected("Partner API not implemented yet.")


CONNECTORS = {"manual": ManualConnector, "pmfby_partner": PortalPartnerConnector}


def get():
    name = getattr(settings, "INSURANCE_CONNECTOR", "manual")
    try:
        return CONNECTORS[name]()
    except (KeyError, NotConnected):
        return ManualConnector()
