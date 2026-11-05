from core.rights_role_test_case import RightsRoleGraphQLTestCase
from core.test_helpers import create_right_only_user
from location.test_helpers import create_basic_test_locations


LOCATIONS_QUERY = """
query {
  locations(first: 5) {
    edges { node { id code name type } }
  }
}
"""

VALIDATE_LOCATION = """
query {
  validateLocationCode(locationCode: "R1")
}
"""

HEALTH_FACILITIES_QUERY = """
query {
  healthFacilities(first: 5) {
    edges { node { id code name } }
  }
}
"""

VALIDATE_HF = """
query {
  validateHealthFacilityCode(healthFacilityCode: "TST-HF")
}
"""


class LocationRightsTests(RightsRoleGraphQLTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_basic_test_locations()

    def _user(self, name, perms):
        return create_right_only_user(name, perms, district_codes=self.DISTRICT_CODES)

    def test_query_locations_right_gate(self):
        allowed = self._user("r_loc_q", ["gql_query_locations_perms"])
        denied = self._user("r_loc_q_no", [])
        self.assert_user_has_named_perms(allowed, ["gql_query_locations_perms"])
        self.assert_user_lacks_named_perms(denied, ["gql_query_locations_perms"])
        self.assert_gql_ok(allowed, VALIDATE_LOCATION)
        self.assert_gql_unauthorized(denied, VALIDATE_LOCATION)
        self.assert_gql_ok(allowed, LOCATIONS_QUERY)

    def test_query_health_facilities_right_gate(self):
        allowed = self._user("r_hf_q", ["gql_query_health_facilities_perms"])
        denied = self._user("r_hf_q_no", [])
        self.assert_user_has_named_perms(allowed, ["gql_query_health_facilities_perms"])
        self.assert_user_lacks_named_perms(denied, ["gql_query_health_facilities_perms"])
        self.assert_gql_ok(allowed, VALIDATE_HF)
        self.assert_gql_unauthorized(denied, VALIDATE_HF)
        self.assert_gql_ok(allowed, HEALTH_FACILITIES_QUERY)
