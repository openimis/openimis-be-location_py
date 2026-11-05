from django.test import TestCase
from location.test_helpers import (
    create_test_village,
    create_test_health_facility,
    create_test_location,
    assign_user_districts,
)
from core.test_helpers import (
    create_test_officer,
    create_test_interactive_user,
    create_test_claim_admin,
    create_manager_role,
    create_imis_admin_role,
    create_enrolment_officer_role,
    create_claim_admin_role,
    create_admin_role
)
from django.core.cache import caches

from location.models import LocationManager, UserDistrict, Location, cache, cache_location_if_not_cached


_TEST_USER_NAME = "test_batch_run"
_TEST_USER_PASSWORD = "test_batch_run"
_TEST_DATA_USER = {
    "username": _TEST_USER_NAME,
    "last_name": _TEST_USER_NAME,
    "password": _TEST_USER_PASSWORD,
    "other_names": _TEST_USER_NAME,
    "user_types": "INTERACTIVE",
    "language": "en",
    "roles": [create_admin_role().id],
}


class LocationTest(TestCase):
    test_village = None
    test_user = None
    test_hf = None
    test_ca = None
    test_eo = None
    test_user_eo = None
    test_user_ca = None
    other_loc = None

    @classmethod
    def setUpTestData(cls):
        cls.test_village = create_test_village()

        super_user_role = create_imis_admin_role()
        ca_role = create_claim_admin_role()
        eo_role = create_enrolment_officer_role()
        xx_role = create_manager_role()
        cls.test_user = create_test_interactive_user(
            username="loctest", roles=[xx_role.id]
        )
        cls.test_hf = create_test_health_facility(
            location_id=cls.test_village.parent.parent_id
        )
        cls.test_user_ca = create_test_interactive_user(
            username="tst_ca",
            roles=[ca_role.id],
            custom_props={"health_facility_id": cls.test_hf.id},
        )
        cls.test_user_eo = create_test_interactive_user(
            username="tst_eo",
            roles=[eo_role.id],
        )
        cls.test_super_user = create_test_interactive_user(
            username="superuser", roles=[super_user_role.id]
        )
        cls.other_loc = create_test_location(
            "D",
            custom_props={
                "parent": cls.test_village.parent.parent.parent,
                "code": "NOTALLO",
            },
        )
        assign_user_districts(cls.test_user, [cls.test_village.parent.parent.code])

        cls.test_ca = create_test_claim_admin(
            custom_props={
                "health_facility_id": cls.test_hf.id,
                "code": cls.test_user_ca.username,
                "has_login": True,
            }
        )
        cls.test_eo = create_test_officer(
            villages=[cls.test_village],
            custom_props={"code": cls.test_user_eo.username, "has_login": True},
        )

    def test_parents(self):
        hierachy = LocationManager().parents(self.test_village.id)
        self.assertEqual(len(hierachy), 4)
        district = LocationManager().parents(self.test_village.id, loc_type="D")
        self.assertEqual(len(district), 1)

    def test_children(self):
        hierachy = LocationManager().children(self.test_village.parent.parent.parent.id)
        self.assertEqual(len(hierachy), 5)
        district = LocationManager().children(
            self.test_village.parent.parent.parent.id, loc_type="D"
        )
        self.assertEqual(len(district), 2)

    def test_allowed(self):
        allowed_ids = LocationManager().allowed(
            self.test_user._u.id, loc_types=["V", "D", "W"], qs=True
        ).values_list('id', flat=True)
        self.assertTrue(self.test_village.id in allowed_ids)
        self.assertTrue(self.test_village.parent.id in allowed_ids)
        self.assertTrue(self.test_village.parent.parent.id in allowed_ids)
        self.assertEqual(len(allowed_ids), 3)

        allowed_ids = LocationManager().allowed(
            self.test_user._u.id, loc_types=["R", "D", "W"], qs=True
        ).values_list('id', flat=True)
        self.assertTrue(self.test_village.parent.id in allowed_ids)
        self.assertTrue(self.test_village.parent.parent.id in allowed_ids)
        self.assertEqual(len(allowed_ids), 2)

        # non-queryset
        allowed = LocationManager().allowed(
            self.test_user._u.id, loc_types=["R", "D", "W"]
        )
        self.assertEqual(len(allowed), 2)
        allowed_ids_non_qs = list(loc.id for loc in allowed)
        self.assertEqual(sorted(allowed_ids_non_qs), sorted(allowed_ids))

        # Not strict should include parent, but not sibling
        allowed_ids = LocationManager().allowed(
            self.test_user._u.id, loc_types=["R", "D", "W"], qs=True, strict=False
        ).values_list('id', flat=True)
        self.assertTrue(self.test_village.parent.id in allowed_ids)
        self.assertTrue(self.test_village.parent.parent.id in allowed_ids)
        self.assertTrue(self.test_village.parent.parent.parent.id in allowed_ids)
        self.assertFalse(self.other_loc.id in allowed_ids)
        self.assertEqual(len(allowed_ids), 3)

    def test_allowed_composes_as_a_subquery(self):
        """It must stay a lazy queryset, not a list of ids (OP-3197).

        `allowed()` used to be a recursive CTE, which MSSQL cannot host in a
        subquery - so on that backend it executed on its own and came back as
        a literal `IN` list of every allowed id. SQL Server caps a statement
        at 2100 parameters, so a village-level hierarchy did not just run
        slowly, it stopped running.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        allowed = LocationManager().allowed(self.test_user._u.id, qs=True)

        # building it, and nesting it, must touch the database zero times
        with CaptureQueriesContext(connection) as ctx:
            composed = Location.objects.filter(id__in=allowed.values("id"))
            sql = str(composed.query)
        self.assertEqual(
            len(ctx.captured_queries), 0, "the allowed set was materialised"
        )

        # and the hierarchy must be resolved by the server, without a CTE
        self.assertNotIn("WITH ", sql.upper())
        self.assertIn("SELECT", sql)

        self.assertEqual(
            set(composed.values_list("id", flat=True)),
            set(allowed.values_list("id", flat=True)),
        )

    def test_is_allowed(self):
        self.assertTrue(
            LocationManager().is_allowed(
                self.test_user, [self.test_village.parent.parent.id]
            ),
            "is_allowed function is not working as supposed",
        )
        # same but with cache
        self.assertTrue(
            LocationManager().is_allowed(
                self.test_user, [self.test_village.parent.parent.id]
            ),
            "is_allowed function is not working as supposed",
        )

        self.assertFalse(
            LocationManager().is_allowed(
                self.test_user, [self.other_loc.id, self.test_village.parent.parent.id]
            ),
            "is_allowed function is not working as supposed",
        )
        cached = caches["location"].get(f"user_locations_{self.test_user._u.id}")
        self.assertIsNotNone(cached)
        districts = UserDistrict.get_user_districts(self.test_user)
        self.assertIsNotNone(districts)

    def test_allowed_location_excludes_invalid(self):
        invalid_village = create_test_village({'name': 'Invalid Vilalge', 'code': 'IV2020'})
        invalid_village.validity_to = '2020-02-20'
        invalid_village.parent = self.test_village.parent
        invalid_village.save()

        allowed = LocationManager().allowed(
            self.test_user._u.id, loc_types=["V"]
        )
        self.assertEqual(len(allowed), 1)
        self.assertEqual(allowed.first().id, self.test_village.id)

    def test_cache_invalidation(self):
        LocationManager().is_allowed(self.test_user, [])
        cached = caches["location"].get(f"user_locations_{self.test_user._u.id}")
        self.assertIsNotNone(cached, "cache not found")
        self.test_user._u.email = "test@opeimis.org"
        self.test_user._u.save()
        # test invalidation
        cached = caches["location"].get(f"user_locations_{self.test_user._u.id}")
        self.assertIsNone(cached, "cache not cleared")
        LocationManager().is_allowed(self.test_user, [])
        create_test_village()
        cached = caches["location"].get(f"user_locations_{self.test_user._u.id}")
        self.assertIsNone(cached, "cache not cleared")

    def test_allowed_location_eo(self):
        self.assertFalse(
            LocationManager().is_allowed(
                self.test_user_eo,
                [self.test_village.id, self.test_village.parent.parent_id],
            ),
            "is_allowed function is not working as supposed",
        )
        self.assertFalse(
            LocationManager().is_allowed(
                self.test_user_eo,
                [
                    self.other_loc.id,
                    self.test_village.id,
                    self.test_village.parent.parent_id,
                ],
                strict=False,
            ),
            "is_allowed function is not working as supposed",
        )
        self.assertTrue(
            LocationManager().is_allowed(
                self.test_user_eo,
                [self.test_village.id, self.test_village.parent.parent_id],
                strict=False,
            ),
            "is_allowed function is not working as supposed",
        )
        self.assertTrue(
            LocationManager().is_allowed(
                self.test_user_eo,
                [self.test_village.id, self.test_village.parent.parent_id],
                strict=False,
            ),
            "is_allowed function is not working as supposed",
        )

    def test_allowed_location_ca(self):
        self.assertFalse(
            LocationManager().is_allowed(
                self.test_user_ca,
                [
                    self.test_village.parent.parent_id,
                    self.test_village.parent.parent.parent_id,
                ],
            ),
            "is_allowed function is not working as supposed",
        )
        self.assertFalse(
            LocationManager().is_allowed(
                self.test_user_ca,
                [
                    self.other_loc.id,
                    self.test_village.parent.parent_id,
                    self.test_village.parent.parent.parent_id,
                ],
                strict=False,
            ),
            "is_allowed function is not working as supposed",
        )
        self.assertTrue(
            LocationManager().is_allowed(
                self.test_user_ca,
                [
                    self.test_village.parent.parent_id,
                    self.test_village.parent.parent.parent_id,
                ],
                strict=False,
            ),
            "is_allowed function is not working as supposed",
        )
        self.assertTrue(
            LocationManager().is_allowed(
                self.test_user_ca, [self.test_village.parent.parent_id]
            ),
            "is_allowed function is not working as supposed",
        )

    def test_get_user_districts_does_not_rely_on_cache_for_correctness(self):
        all_valid_districts = Location.objects.filter(
            type="D",
            parent__isnull=False,
            *Location.filter_validity(),
        )
        self.assertTrue(all_valid_districts.exists())

        # Manually prime location cache
        cache_location_if_not_cached()

        # Simulate cache eviction of a location's parent
        example_district = all_valid_districts.first()
        self.assertIsNotNone(example_district.parent_id)

        # Also ensure no UserDistricts are cached for the user
        cache.delete(f"user_districts_{self.test_super_user.id}")

        # Invoke the method, which should hfill the cache
        user_districts = UserDistrict.get_user_districts(self.test_super_user)
        self.assertEqual(len(user_districts), all_valid_districts.count())
        caches['default'].delete(f"cs_Location_{example_district.parent_id}")
        # Invoke the method, which should handle missing parent cache gracefully
        user_districts = UserDistrict.get_user_districts(self.test_super_user)
        self.assertEqual(len(user_districts), all_valid_districts.count())

        # Check that all districts have a parent loaded even if it had been evicted
        for ud in user_districts:
            self.assertIsNotNone(ud.location)
            self.assertIsNotNone(ud.location.parent)
