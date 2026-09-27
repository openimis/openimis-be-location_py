import json

from core.rights_role_test_case import RightsRoleGraphQLTestCase
from core.test_helpers import create_right_only_user, create_test_interactive_user
from location.models import Location
from location.test_helpers import (
    create_basic_test_locations,
    create_test_health_facility,
)


class LocationWalkRowSecurityTests(RightsRoleGraphQLTestCase):
    """
    Walking a foreign key into the location tree stays inside the user's own
    branch: the locations they are assigned, their ancestors and descendants.
    """

    OWN_DISTRICT = "R2D1"
    FOREIGN_DISTRICT = "R1D1"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_basic_test_locations()
        cls.own_district = Location.objects.get(
            code=cls.OWN_DISTRICT, *Location.filter_validity()
        )
        cls.foreign_district = Location.objects.get(
            code=cls.FOREIGN_DISTRICT, *Location.filter_validity()
        )
        cls.foreign_hf = create_test_health_facility(
            code="FRN-HF", location_id=cls.foreign_district.id
        )
        cls.super_user = create_test_interactive_user(username="loc_walk_super")

    def _district_limited_user(self, username):
        return create_right_only_user(
            username, ["gql_query_locations_perms"], district_codes=[self.OWN_DISTRICT]
        )

    def assert_forbidden_on(self, response, field):
        content = json.loads(response.content)
        errors = content.get("errors") or []
        self.assertTrue(
            any(
                e.get("extensions", {}).get("code") == "FORBIDDEN"
                and field in (e.get("path") or [])
                for e in errors
            ),
            msg=content,
        )
        return content

    def test_walk_up_to_own_ancestor_is_allowed(self):
        """The parent of an assigned district is above the user's own branch."""
        user = self._district_limited_user("loc_walk_up")
        headers, _token = self.bearer(user)
        query = """
            query OwnBranch($code: String!) {
                locations(code: $code, first: 5) {
                    edges { node { code parent { code } } }
                }
            }
        """
        response = self.query(
            query, headers=headers, variables={"code": self.OWN_DISTRICT}
        )
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        nodes = [e["node"] for e in content["data"]["locations"]["edges"]]
        self.assertEqual([n["code"] for n in nodes], [self.OWN_DISTRICT])
        self.assertEqual(nodes[0]["parent"]["code"], self.own_district.parent.code)

    def test_walk_into_foreign_location_is_denied(self):
        """
        ignoreLocation hands out health facilities outside the user's districts;
        their location must not come with them.
        """
        user = self._district_limited_user("loc_walk_foreign")
        headers, _token = self.bearer(user)
        query = """
            query ForeignHf($search: String!) {
                healthFacilitiesStr(str: $search, ignoreLocation: true, first: 5) {
                    edges { node { code location { code } } }
                }
            }
        """
        response = self.query(
            query, headers=headers, variables={"search": self.foreign_hf.code}
        )
        self.assert_forbidden_on(response, "location")

    def test_locations_all_still_walks_the_whole_tree(self):
        """locationsAll is the module's deliberate full-tree feed, walk included."""
        user = self._district_limited_user("loc_walk_all")
        headers, _token = self.bearer(user)
        query = """
            query AllLocations($code: String!) {
                locationsAll(code: $code, first: 5) {
                    edges { node { code parent { code } } }
                }
            }
        """
        response = self.query(
            query, headers=headers, variables={"code": self.FOREIGN_DISTRICT}
        )
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        nodes = [e["node"] for e in content["data"]["locationsAll"]["edges"]]
        self.assertEqual([n["code"] for n in nodes], [self.FOREIGN_DISTRICT])
        self.assertEqual(nodes[0]["parent"]["code"], self.foreign_district.parent.code)

    def test_locations_all_exemption_survives_an_alias(self):
        """The exemption is keyed on the field, not on the response name."""
        user = self._district_limited_user("loc_walk_alias")
        headers, _token = self.bearer(user)
        query = """
            query AliasedAll($code: String!) {
                everything: locationsAll(code: $code, first: 5) {
                    edges { node { code parent { code } } }
                }
            }
        """
        response = self.query(
            query, headers=headers, variables={"code": self.FOREIGN_DISTRICT}
        )
        self.assertResponseNoErrors(response)

    def test_superuser_is_not_location_restricted(self):
        query = """
            query ForeignHf($search: String!) {
                healthFacilitiesStr(str: $search, ignoreLocation: true, first: 5) {
                    edges { node { code location { code } } }
                }
            }
        """
        headers, _token = self.bearer(self.super_user)
        response = self.query(
            query, headers=headers, variables={"search": self.foreign_hf.code}
        )
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        nodes = [e["node"] for e in content["data"]["healthFacilitiesStr"]["edges"]]
        self.assertEqual(nodes[0]["location"]["code"], self.FOREIGN_DISTRICT)
