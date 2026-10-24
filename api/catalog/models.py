from django.db import models


class DistrictProduct(models.Model):
    """One District One Product (ODOP): the product each district is promoted for under the PM-FME scheme.

    Loaded from the Ministry of Food Processing Industries list (see data/odop.csv and `load_odop`). `crops` are the
    catalog keys the product text maps to, so a district's featured product links to rates, farmers and listings.
    """

    state = models.CharField(max_length=60, db_index=True)
    district = models.CharField(max_length=80, db_index=True)
    product = models.CharField(max_length=200, help_text="As written in the official list")
    crops = models.JSONField(default=list, blank=True, help_text="Catalog keys this product is made from")
    source = models.CharField(max_length=200, default="MoFPI PM-FME ODOP list of 713 districts")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["state", "district"], name="uniq_odop_district")]
        ordering = ["state", "district"]

    def __str__(self):
        return f"{self.district}, {self.state}: {self.product}"
