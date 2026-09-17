from datetime import date
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase

from location.models import Catchment, CatchmentDistrict, Location
from location.services import CatchmentService, generate_unique_catchment_code


class AuditUser:
    id_for_audit = 1


class CatchmentServiceTest(TestCase):
    def setUp(self):
        self.district_1 = Location.objects.create(
            code="101", name="Chitipa", type="R", audit_user_id=1
        )
        self.district_2 = Location.objects.create(
            code="102", name="Karonga", type="R", audit_user_id=1
        )
        self.ta = Location.objects.create(
            code="10101",
            name="Kameme",
            type="D",
            parent=self.district_1,
            audit_user_id=1,
        )
        self.service = CatchmentService(AuditUser())

    def payload(self, code="CA01", district_ids=None):
        from core.utils import TimeUtils

        return {
            "code": code,
            "name": "North Catchment",
            "district_ids": district_ids or [self.district_1.id],
            "audit_user_id": 1,
            "validity_from": TimeUtils.now(),
        }

    def test_create_with_multiple_districts(self):
        catchment = self.service.update_or_create(
            self.payload(district_ids=[self.district_1.id, self.district_2.id])
        )
        self.assertEqual(
            set(catchment.district_links.filter(validity_to__isnull=True).values_list(
                "location_id", flat=True
            )),
            {self.district_1.id, self.district_2.id},
        )

    def test_generates_code_when_creating_without_one(self):
        payload = self.payload()
        payload.pop("code")

        catchment = self.service.update_or_create(payload)

        self.assertRegex(catchment.code, rf"^{date.today().year}\d{{5}}$")

    def test_generated_code_retries_on_collision(self):
        self.service.update_or_create(self.payload(code="202612345"))

        with mock.patch("location.services.random.randint", side_effect=[12345, 67890]):
            code = generate_unique_catchment_code(Catchment, date(2026, 1, 1))

        self.assertEqual(code, "202667890")

    def test_district_can_belong_to_multiple_catchments(self):
        self.service.update_or_create(self.payload(code="CA01"))
        self.service.update_or_create(self.payload(code="CA02"))
        self.assertEqual(
            CatchmentDistrict.objects.filter(
                location=self.district_1,
                validity_to__isnull=True,
            ).count(),
            2,
        )

    def test_rejects_empty_districts(self):
        payload = self.payload()
        payload["district_ids"] = []
        with self.assertRaises(ValidationError):
            self.service.update_or_create(payload)

    def test_rejects_non_district_location(self):
        with self.assertRaises(ValidationError):
            self.service.update_or_create(
                self.payload(district_ids=[self.ta.id])
            )
