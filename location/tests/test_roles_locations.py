from core.rights_role_test_case import RightsRoleGraphQLTestCase
from core.test_helpers import (
    create_accountant_role,
    create_claim_admin_role,
    create_clerk_role,
    create_data_entry_clerk_hf_role,
    create_district_manager_role,
    create_enrolment_officer_role,
    create_hf_bound_role_user,
    create_medical_advisor_role,
    create_monitoring_evaluation_role,
    create_raf_role,
    create_receptionist_role,
    create_role_user,
    create_test_officer,
)
from location.tests.test_rights_locations import (
    HEALTH_FACILITIES_QUERY,
    LOCATIONS_QUERY,
    VALIDATE_HF,
    VALIDATE_LOCATION,
)
from location.test_helpers import (
    create_basic_test_locations,
    create_test_health_facility,
    create_test_village,
)


class LocationRoleTests(RightsRoleGraphQLTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_basic_test_locations()
        cls.village = create_test_village()
        cls.district = cls.village.parent.parent
        cls.hf = create_test_health_facility(
            code="LOCHF", location_id=cls.district.id
        )
        cls.districts = cls.DISTRICT_CODES + [cls.district.code]
        cls.officer = create_test_officer(
            villages=[cls.village], custom_props={"code": "LOCEO"}
        )
        cls.location_roles = {
            "accountant": create_role_user(
                "loc_acc", create_accountant_role(), district_codes=cls.districts
            ),
            "claim_admin": create_hf_bound_role_user(
                "loc_ca",
                create_claim_admin_role(),
                health_facility=cls.hf,
                district_codes=cls.districts,
            ),
            "clerk": create_role_user(
                "loc_clk", create_clerk_role(), district_codes=cls.districts
            ),
            "enrolment_officer": create_role_user(
                "loc_eo",
                create_enrolment_officer_role(),
                district_codes=cls.districts,
                officer=cls.officer,
            ),
            "receptionist": create_role_user(
                "loc_rec", create_receptionist_role(), district_codes=cls.districts
            ),
            "district_manager": create_role_user(
                "loc_dm", create_district_manager_role(), district_codes=cls.districts
            ),
            "medical_advisor": create_role_user(
                "loc_ma", create_medical_advisor_role(), district_codes=cls.districts
            ),
            "raf": create_role_user(
                "loc_raf", create_raf_role(), district_codes=cls.districts
            ),
            "me": create_role_user(
                "loc_me", create_monitoring_evaluation_role(), district_codes=cls.districts
            ),
        }
        cls.hf_roles = {
            "claim_admin": cls.location_roles["claim_admin"],
            "district_manager": cls.location_roles["district_manager"],
            "medical_advisor": cls.location_roles["medical_advisor"],
            "raf": cls.location_roles["raf"],
            "me": cls.location_roles["me"],
            "data_entry_clerk": create_hf_bound_role_user(
                "loc_dec",
                create_data_entry_clerk_hf_role(),
                health_facility=cls.hf,
                with_officer=True,
                villages=[cls.village],
                district_codes=cls.districts,
            ),
        }

    def test_roles_can_search_locations(self):
        for name, user in self.location_roles.items():
            with self.subTest(role=name):
                self.assert_user_has_named_perms(user, ["gql_query_locations_perms"])
                self.assert_gql_ok(user, VALIDATE_LOCATION)
                self.assert_gql_ok(user, LOCATIONS_QUERY)

    def test_roles_can_query_health_facilities(self):
        for name, user in self.hf_roles.items():
            with self.subTest(role=name):
                self.assert_user_has_named_perms(
                    user, ["gql_query_health_facilities_perms"]
                )
                self.assert_gql_ok(user, VALIDATE_HF)
                self.assert_gql_ok(user, HEALTH_FACILITIES_QUERY)
