"""get_queryset honours the OP-2029 validity contract (epic OP-3317, phase 1).

Explicit validity values return the expected rows; a caller asking for
nothing gets what it got before the contract existed.
"""

from datetime import datetime, timedelta

from django.test import TestCase

from core.models.row_filters import Validity
from core.test_helpers import assert_row_filters, create_test_interactive_user, mark_deleted
from location.models import HealthFacility, Location
from location.test_helpers import create_test_health_facility, create_test_location


class LocationRowFiltersTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = create_test_interactive_user(username="locationrowfilters")

    def test_location(self):
        live = create_test_location("R", custom_props={"code": "RWF1", "name": "row filters live"})
        deleted = mark_deleted(create_test_location("R", custom_props={"code": "RWF2", "name": "row filters deleted"}))
        assert_row_filters(
            self, Location, Location.objects.filter(id__in=[live.id, deleted.id]), self.user,
            live.id, deleted.id, default_hides_deleted=True,
        )

    def test_health_facility(self):
        live = create_test_health_facility(code="RWF1")
        deleted = mark_deleted(create_test_health_facility(code="RWF2"))
        assert_row_filters(
            self, HealthFacility, HealthFacility.objects.filter(id__in=[live.id, deleted.id]), self.user,
            live.id, deleted.id, default_hides_deleted=True,
        )

    def test_a_validity_date_picks_the_location_valid_then(self):
        location = create_test_location("R", custom_props={"code": "RWF3", "name": "row filters dated"})
        rows = Location.objects.filter(id=location.id)
        before = Validity.at(location.validity_from - timedelta(days=1))
        self.assertFalse(Location.get_queryset(rows, self.user, validity=before).exists())
        self.assertTrue(
            Location.get_queryset(rows, self.user, validity=Validity.at(datetime.now() + timedelta(seconds=1))).exists()
        )
