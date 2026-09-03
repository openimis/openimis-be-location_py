"""
Coverage of the UBA half of `LocationManager.build_user_location_filter_query`.

The point of the registry `params` is that a module never spells out the path from the
model it filters to the object a credential is held on: the filter works it out from the
location path the caller already passes. These tests pin that derivation down, both as
pure string work (`_walk_prefix`) and against the two credentials location registers.
"""
from django.core.cache import cache
from django.test import TestCase

from core.apps import (
    CLAIM_ADMIN_UBA_LINK_TYPE,
    ENROLMENT_UBA_LINK_TYPE,
    HEALTH_FACILITY_MODEL,
    VILLAGE_LOCATION_TYPE,
    VILLAGE_MODEL,
)
from core.services.userServices import create_or_update_user_districts
from core.test_helpers import (
    create_test_interactive_user,
    create_test_role,
    create_test_user_business_access,
)
from core.uba_link_types import (
    get_location_aware_uba_link_types,
    get_uba_link_type,
    get_uba_link_type_param,
)
from location.models import HealthFacility, Location, LocationManager
from location.test_helpers import create_test_health_facility, create_test_village


class UbaLinkTypeRegistrationTest(TestCase):
    """Location, not core, declares the credentials held on its own models."""

    def test_enrolment_is_declared_on_the_village(self):
        link_type = get_uba_link_type(ENROLMENT_UBA_LINK_TYPE)
        self.assertIsNotNone(link_type)
        self.assertEqual((VILLAGE_MODEL,), link_type.models)
        self.assertEqual(
            VILLAGE_LOCATION_TYPE,
            get_uba_link_type_param(ENROLMENT_UBA_LINK_TYPE, "location_type"))

    def test_claim_admin_is_declared_on_the_health_facility(self):
        link_type = get_uba_link_type(CLAIM_ADMIN_UBA_LINK_TYPE)
        self.assertIsNotNone(link_type)
        self.assertEqual((HEALTH_FACILITY_MODEL,), link_type.models)
        # the health facility is not a location, it hangs off one through `location`
        self.assertEqual(
            "location", get_uba_link_type_param(CLAIM_ADMIN_UBA_LINK_TYPE, "location_field"))
        self.assertIsNone(
            get_uba_link_type_param(CLAIM_ADMIN_UBA_LINK_TYPE, "location_type"))

    def test_both_are_location_aware(self):
        codes = {link_type.code for link_type in get_location_aware_uba_link_types()}
        self.assertIn(ENROLMENT_UBA_LINK_TYPE, codes)
        self.assertIn(CLAIM_ADMIN_UBA_LINK_TYPE, codes)


class WalkPrefixTest(TestCase):
    """
    A location path is built by climbing from the row's own location, so going back down
    to the level a credential is held on is dropping trailing '__parent' segments.
    """

    def test_no_move_returns_the_path_unchanged(self):
        self.assertEqual('location', LocationManager._walk_prefix('location', 0))

    def test_walking_down_drops_parent_segments(self):
        self.assertEqual(
            'location', LocationManager._walk_prefix('location__parent__parent', 2))
        self.assertEqual(
            'family__location',
            LocationManager._walk_prefix('family__location__parent__parent', 2))
        self.assertEqual(
            'insuree__current_village',
            LocationManager._walk_prefix('insuree__current_village__parent__parent', 2))

    def test_walking_up_adds_parent_segments(self):
        self.assertEqual(
            'location__parent', LocationManager._walk_prefix('location', -1))

    def test_walking_down_a_path_without_parents_is_refused(self):
        # nothing to drop: the caller falls back to comparing ancestors rather than
        # inventing a path that does not exist
        self.assertIsNone(LocationManager._walk_prefix('location', 2))
        self.assertIsNone(
            LocationManager._walk_prefix('health_facility__location', 1))


class PrefixLocationTypeTest(TestCase):
    def test_a_single_loc_type_is_the_level_the_path_points_at(self):
        self.assertEqual('D', LocationManager._prefix_location_type(['D']))

    def test_the_default_points_at_the_deepest_type(self):
        self.assertEqual('V', LocationManager._prefix_location_type(['R', 'D', 'W', 'V']))


class UbaLocationFilterTest(TestCase):
    """The filter built for a user, against the real registry and the real tree."""

    @classmethod
    def setUpTestData(cls):
        cls.village = create_test_village({"name": "UbaLocFilter"})
        cls.district = cls.village.parent.parent
        cls.hf = create_test_health_facility(
            "UBALF1", cls.district.id, custom_props={"code": "UBALF1"})
        cls.other_hf = create_test_health_facility(
            "UBALF2", cls.district.id, custom_props={"code": "UBALF2"})
        cls.role = create_test_role(name="UBA location filter", uba_rights=[111001])
        cls.user = create_test_interactive_user(
            username="ubalocfilter", roles=[cls.role.id])
        create_or_update_user_districts(cls.user.i_user, [cls.district.id], -1)

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_no_credential_means_no_uba_narrowing(self):
        self.assertIsNone(LocationManager().build_uba_location_filter_query(
            self.user.i_user, prefix='location__parent__parent', loc_types=['D']))

    def test_a_village_credential_narrows_on_the_walked_down_path(self):
        create_test_user_business_access(
            user=self.user, business_object=self.village,
            link_type=ENROLMENT_UBA_LINK_TYPE)
        q = LocationManager().build_uba_location_filter_query(
            self.user.i_user, prefix='location__parent__parent', loc_types=['D'])
        self.assertIsNotNone(q)
        # 'location__parent__parent' points at the district, the credential at the
        # village: the filter lands on 'location'
        self.assertIn('location__id__in', str(q))
        self.assertNotIn('parent', str(q))

    def test_a_health_facility_credential_narrows_on_the_owning_model(self):
        create_test_user_business_access(
            user=self.user, business_object=self.hf, link_type=CLAIM_ADMIN_UBA_LINK_TYPE)
        q = LocationManager().build_uba_location_filter_query(
            self.user.i_user, prefix='health_facility__location', loc_types=['D'])
        self.assertIsNotNone(q)
        self.assertIn('health_facility__id__in', str(q))

    def test_a_health_facility_credential_filters_the_facility_itself(self):
        create_test_user_business_access(
            user=self.user, business_object=self.hf, link_type=CLAIM_ADMIN_UBA_LINK_TYPE)
        visible = HealthFacility.get_queryset(
            HealthFacility.objects.filter(code__startswith="UBALF"), self.user)
        self.assertEqual({"UBALF1"}, set(visible.values_list("code", flat=True)))

    def test_a_health_facility_credential_says_nothing_about_a_village_path(self):
        create_test_user_business_access(
            user=self.user, business_object=self.hf, link_type=CLAIM_ADMIN_UBA_LINK_TYPE)
        # the path never reaches a health facility, so that credential contributes no
        # term - and must not empty the result either
        self.assertIsNone(LocationManager().build_uba_location_filter_query(
            self.user.i_user, prefix='location__parent__parent', loc_types=['D']))

    def test_two_credentials_are_ored(self):
        create_test_user_business_access(
            user=self.user, business_object=self.village,
            link_type=ENROLMENT_UBA_LINK_TYPE)
        create_test_user_business_access(
            user=self.user, business_object=self.hf, link_type=CLAIM_ADMIN_UBA_LINK_TYPE)
        rendered = str(LocationManager().build_uba_location_filter_query(
            self.user.i_user, prefix='health_facility__location', loc_types=['D']))
        # CLAIM_ADMIN lands on the facility; ENROLMENT cannot walk this path down to the
        # village, so it falls back to comparing the district. Both terms are present and
        # OR'ed: a second credential widens what the user sees
        self.assertIn('health_facility__id__in', rendered)
        self.assertIn('health_facility__location__id__in', rendered)
        self.assertIn('OR', rendered)

    def test_the_uba_filter_is_anded_with_the_district_filter(self):
        create_test_user_business_access(
            user=self.user, business_object=self.village,
            link_type=ENROLMENT_UBA_LINK_TYPE)
        rendered = str(LocationManager().build_user_location_filter_query(
            self.user.i_user, prefix='location__parent__parent', loc_types=['D']))
        self.assertIn('AND', rendered)
        # the district filter is still in there, the credential narrows inside it
        self.assertIn('location__parent__parent__in', rendered)
        self.assertIn('location__id__in', rendered)
