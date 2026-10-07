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
    ALL_UBA_LINK_TYPES,
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


class LocationAwareSelectionTest(TestCase):
    """Which credentials a caller asks the row filter to consider."""

    @staticmethod
    def codes(link_types):
        return {link_type.code for link_type in get_location_aware_uba_link_types(link_types)}

    def test_all_takes_every_location_aware_type(self):
        every = self.codes(ALL_UBA_LINK_TYPES)
        self.assertEqual(every, self.codes([ALL_UBA_LINK_TYPES]))
        self.assertIn(ENROLMENT_UBA_LINK_TYPE, every)
        self.assertIn(CLAIM_ADMIN_UBA_LINK_TYPE, every)

    def test_a_single_code_may_be_passed_as_a_string(self):
        self.assertEqual({ENROLMENT_UBA_LINK_TYPE}, self.codes(ENROLMENT_UBA_LINK_TYPE))
        self.assertEqual({ENROLMENT_UBA_LINK_TYPE}, self.codes([ENROLMENT_UBA_LINK_TYPE]))

    def test_a_list_keeps_the_named_ones_only(self):
        self.assertEqual(
            {ENROLMENT_UBA_LINK_TYPE, CLAIM_ADMIN_UBA_LINK_TYPE},
            self.codes([ENROLMENT_UBA_LINK_TYPE, CLAIM_ADMIN_UBA_LINK_TYPE]))

    def test_all_inside_a_list_wins_over_the_other_entries(self):
        self.assertEqual(
            self.codes(ALL_UBA_LINK_TYPES),
            self.codes([ENROLMENT_UBA_LINK_TYPE, ALL_UBA_LINK_TYPES]))

    def test_nothing_selects_nothing(self):
        # the row filter's own default: a module that does not name a credential is not
        # governed by one, and must not see its district scope shrunk by a link it holds
        # for another module's rows
        self.assertEqual(set(), self.codes(None))
        self.assertEqual(set(), self.codes([]))

    def test_an_unknown_code_is_dropped(self):
        with self.assertLogs('core.uba_link_types', level='WARNING'):
            self.assertEqual(set(), self.codes(['NO_SUCH_LINK_TYPE']))


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
            self.user.i_user, prefix='location__parent__parent', loc_types=['D'],
            link_types=ALL_UBA_LINK_TYPES))

    def test_a_village_credential_narrows_on_the_walked_down_path(self):
        create_test_user_business_access(
            user=self.user, business_object=self.village,
            link_type=ENROLMENT_UBA_LINK_TYPE)
        q = LocationManager().build_uba_location_filter_query(
            self.user.i_user, prefix='location__parent__parent', loc_types=['D'],
            link_types=ENROLMENT_UBA_LINK_TYPE)
        self.assertIsNotNone(q)
        # 'location__parent__parent' points at the district, the credential at the
        # village: the filter lands on 'location'
        self.assertIn('location__id__in', str(q))
        self.assertNotIn('parent', str(q))

    def test_a_health_facility_credential_narrows_on_the_owning_model(self):
        create_test_user_business_access(
            user=self.user, business_object=self.hf, link_type=CLAIM_ADMIN_UBA_LINK_TYPE)
        q = LocationManager().build_uba_location_filter_query(
            self.user.i_user, prefix='health_facility__location', loc_types=['D'],
            link_types=CLAIM_ADMIN_UBA_LINK_TYPE)
        self.assertIsNotNone(q)
        self.assertIn('health_facility__id__in', str(q))

    def test_a_health_facility_credential_filters_the_facility_itself(self):
        create_test_user_business_access(
            user=self.user, business_object=self.hf, link_type=CLAIM_ADMIN_UBA_LINK_TYPE)
        # 'location' is the field the credential is held through, so the filter lands on
        # the facility's own id - what the claim module gets when it demands CLAIM_ADMIN
        visible = LocationManager().build_user_location_filter_query(
            self.user.i_user, prefix='location', loc_types=['D'],
            queryset=HealthFacility.objects.filter(code__startswith="UBALF"),
            link_types=CLAIM_ADMIN_UBA_LINK_TYPE)
        self.assertEqual({"UBALF1"}, set(visible.values_list("code", flat=True)))

    def test_the_health_facility_list_is_not_narrowed_on_its_own(self):
        create_test_user_business_access(
            user=self.user, business_object=self.hf, link_type=CLAIM_ADMIN_UBA_LINK_TYPE)
        # the generic facility list demands no credential, so being claim admin of one
        # facility does not hide the other facilities of the user's districts
        visible = HealthFacility.get_queryset(
            HealthFacility.objects.filter(code__startswith="UBALF"), self.user)
        self.assertEqual({"UBALF1", "UBALF2"}, set(visible.values_list("code", flat=True)))

    def test_a_health_facility_credential_says_nothing_about_a_village_path(self):
        create_test_user_business_access(
            user=self.user, business_object=self.hf, link_type=CLAIM_ADMIN_UBA_LINK_TYPE)
        # the path never reaches a health facility, so that credential contributes no
        # term - and must not empty the result either
        self.assertIsNone(LocationManager().build_uba_location_filter_query(
            self.user.i_user, prefix='location__parent__parent', loc_types=['D'],
            link_types=CLAIM_ADMIN_UBA_LINK_TYPE))

    def test_two_credentials_are_ored(self):
        create_test_user_business_access(
            user=self.user, business_object=self.village,
            link_type=ENROLMENT_UBA_LINK_TYPE)
        create_test_user_business_access(
            user=self.user, business_object=self.hf, link_type=CLAIM_ADMIN_UBA_LINK_TYPE)
        rendered = str(LocationManager().build_uba_location_filter_query(
            self.user.i_user, prefix='health_facility__location', loc_types=['D'],
            link_types=ALL_UBA_LINK_TYPES))
        # CLAIM_ADMIN lands on the facility; ENROLMENT cannot walk this path down to the
        # village, so it falls back to comparing the district. Both terms are present and
        # OR'ed: a second credential widens what the user sees
        self.assertIn('health_facility__id__in', rendered)
        self.assertIn('health_facility__location__id__in', rendered)
        self.assertIn('OR', rendered)

    def test_only_the_demanded_credential_is_considered(self):
        create_test_user_business_access(
            user=self.user, business_object=self.village,
            link_type=ENROLMENT_UBA_LINK_TYPE)
        create_test_user_business_access(
            user=self.user, business_object=self.hf, link_type=CLAIM_ADMIN_UBA_LINK_TYPE)
        rendered = str(LocationManager().build_uba_location_filter_query(
            self.user.i_user, prefix='health_facility__location', loc_types=['D'],
            link_types=CLAIM_ADMIN_UBA_LINK_TYPE))
        # the ENROLMENT term, present when every credential is considered, is gone
        self.assertIn('health_facility__id__in', rendered)
        self.assertNotIn('health_facility__location__id__in', rendered)

    def test_demanding_a_credential_the_user_does_not_hold_leaves_no_narrowing(self):
        create_test_user_business_access(
            user=self.user, business_object=self.hf, link_type=CLAIM_ADMIN_UBA_LINK_TYPE)
        self.assertIsNone(LocationManager().build_uba_location_filter_query(
            self.user.i_user, prefix='health_facility__location', loc_types=['D'],
            link_types=[ENROLMENT_UBA_LINK_TYPE]))

    def test_the_demanded_credentials_reach_the_user_filter(self):
        create_test_user_business_access(
            user=self.user, business_object=self.village,
            link_type=ENROLMENT_UBA_LINK_TYPE)
        rendered = str(LocationManager().build_user_location_filter_query(
            self.user.i_user, prefix='location__parent__parent', loc_types=['D'],
            link_types=[CLAIM_ADMIN_UBA_LINK_TYPE]))
        # only the district filter is left, the ENROLMENT link was not asked for
        self.assertIn('location__parent__parent__in', rendered)
        self.assertNotIn('location__id__in', rendered)

    def test_by_default_no_credential_is_considered(self):
        create_test_user_business_access(
            user=self.user, business_object=self.village,
            link_type=ENROLMENT_UBA_LINK_TYPE)
        # a caller naming no credential keeps the plain district filter: the module owning
        # the rows is the one that says which credential governs them
        self.assertIsNone(LocationManager().build_uba_location_filter_query(
            self.user.i_user, prefix='location__parent__parent', loc_types=['D']))
        rendered = str(LocationManager().build_user_location_filter_query(
            self.user.i_user, prefix='location__parent__parent', loc_types=['D']))
        self.assertIn('location__parent__parent__in', rendered)
        self.assertNotIn('location__id__in', rendered)

    def test_the_uba_filter_is_anded_with_the_district_filter(self):
        create_test_user_business_access(
            user=self.user, business_object=self.village,
            link_type=ENROLMENT_UBA_LINK_TYPE)
        rendered = str(LocationManager().build_user_location_filter_query(
            self.user.i_user, prefix='location__parent__parent', loc_types=['D'],
            link_types=ENROLMENT_UBA_LINK_TYPE))
        self.assertIn('AND', rendered)
        # the district filter is still in there, the credential narrows inside it
        self.assertIn('location__parent__parent__in', rendered)
        self.assertIn('location__id__in', rendered)


class UbaLocationPickerTest(TestCase):
    """
    The location pickers of an enrolment officer: `uba_location_ids` gives the linked
    village and, to navigate the tree down to it, its ancestors; the `locations`,
    `locationsStr` and `userDistricts` queries opt into it through `ubaLinkType`.
    """

    @classmethod
    def setUpTestData(cls):
        cls.village = create_test_village({"name": "UbaPickLinked"})
        cls.ward = cls.village.parent
        cls.district = cls.ward.parent
        cls.region = cls.district.parent
        cls.sibling = Location.objects.create(
            name="UbaPickSibling", code="UBAPS2", type="V", parent=cls.ward,
            audit_user_id=-1, validity_from="2019-01-01")
        role = create_test_role(name="UBA picker")
        cls.officer = create_test_interactive_user(username="ubapickofficer", roles=[role.id])
        cls.plain = create_test_interactive_user(username="ubapickplain", roles=[role.id])
        for user in (cls.officer, cls.plain):
            create_or_update_user_districts(user.i_user, [cls.district.id], -1)
        create_test_user_business_access(
            user=cls.officer, business_object=cls.village, link_type=ENROLMENT_UBA_LINK_TYPE)

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @staticmethod
    def _info(user):
        from types import SimpleNamespace

        return SimpleNamespace(context=SimpleNamespace(user=user))

    def test_the_linked_village_comes_with_its_ancestors(self):
        self.assertEqual(
            {self.village.id, self.ward.id, self.district.id, self.region.id},
            set(LocationManager().uba_location_ids(self.officer.i_user, ENROLMENT_UBA_LINK_TYPE)))

    def test_the_ancestors_can_be_left_out(self):
        self.assertEqual(
            {self.village.id},
            set(LocationManager().uba_location_ids(
                self.officer.i_user, ENROLMENT_UBA_LINK_TYPE, include_ancestors=False)))

    def test_no_link_restricts_nothing(self):
        self.assertIsNone(
            LocationManager().uba_location_ids(self.plain.i_user, ENROLMENT_UBA_LINK_TYPE))

    def test_a_credential_that_is_not_asked_for_restricts_nothing(self):
        self.assertIsNone(
            LocationManager().uba_location_ids(self.officer.i_user, CLAIM_ADMIN_UBA_LINK_TYPE))

    def test_get_queryset_keeps_the_filter_it_is_given(self):
        from django.test import override_settings

        with override_settings(ROW_SECURITY=True):
            visible = Location.get_queryset(
                Location.objects.filter(id__in=[self.village.id, self.sibling.id]),
                self.plain)
            self.assertEqual({self.village.id, self.sibling.id}, set(visible.values_list("id", flat=True)))
            only_village = Location.get_queryset(Location.objects.filter(id=self.village.id), self.plain)
            self.assertEqual([self.village.id], list(only_village.values_list("id", flat=True)))

    def test_the_locations_query_is_scoped_on_demand(self):
        from django.test import override_settings
        from location.schema import Query

        info = self._info(self.officer)
        with override_settings(ROW_SECURITY=True):
            scoped = Query.resolve_locations(None, info, uba_link_type=ENROLMENT_UBA_LINK_TYPE)
            # what graphene then does with the resolver's queryset
            ids = set(Location.get_queryset(scoped, self.officer).values_list("id", flat=True))
            self.assertIn(self.village.id, ids)
            self.assertIn(self.ward.id, ids)
            self.assertNotIn(self.sibling.id, ids)
            # without the argument the query keeps the district scope
            self.assertIsNone(Query.resolve_locations(None, info))

    def test_the_user_districts_follow_the_same_scope(self):
        from location.schema import Query

        info = self._info(self.officer)
        districts = Query.resolve_user_districts(
            None, info, uba_link_type=ENROLMENT_UBA_LINK_TYPE, uba_include_ancestors=True)
        self.assertEqual([self.district.uuid], [d.uuid for d in districts])
        districts = Query.resolve_user_districts(
            None, info, uba_link_type=ENROLMENT_UBA_LINK_TYPE, uba_include_ancestors=False)
        self.assertEqual([], districts)
