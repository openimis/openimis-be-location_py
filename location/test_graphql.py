import base64
import json
from dataclasses import dataclass

from core.models import User
from core.test_helpers import create_test_interactive_user
from django.conf import settings
from graphene_django.utils.testing import GraphQLTestCase
from graphql_jwt.shortcuts import get_token
from location.models import Location
from location.test_helpers import create_test_location, assign_user_districts
from rest_framework import status


# from openIMIS import schema


@dataclass
class DummyContext:
    """ Just because we need a context to generate. """
    user: User


class LocationGQLTestCase(GraphQLTestCase):
    GRAPHQL_URL = f'/{settings.SITE_ROOT()}graphql'
    # This is required by some version of graphene but is never used. It should be set to the schema but the import
    # is shown as an error in the IDE, so leaving it as True.
    GRAPHQL_SCHEMA = True
    admin_user = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin_user = create_test_interactive_user(username="testLocationAdmin")
        cls.admin_token = get_token(cls.admin_user, DummyContext(user=cls.admin_user))
        cls.noright_user = create_test_interactive_user(username="testLocationNoRight", roles=[1])
        cls.noright_token = get_token(cls.noright_user, DummyContext(user=cls.noright_user))
        cls.admin_dist_user = create_test_interactive_user(username="testLocationDist")
        assign_user_districts(cls.admin_dist_user, ["R1D1", "R2D1", "R2D2"])
        cls.admin_dist_token = get_token(cls.admin_dist_user, DummyContext(user=cls.admin_dist_user))
        cls.test_region = create_test_location('R')
        cls.test_district = create_test_location('D', custom_props={"parent_id": cls.test_region.id})
        cls.test_ward = create_test_location('W', custom_props={"parent_id": cls.test_district.id})
        cls.test_village = create_test_location('V', custom_props={"parent_id": cls.test_ward.id})
        cls.test_location_delete = create_test_location('V', custom_props={"code": "TODEL", "name": "To delete",
                                                                           "parent_id": cls.test_ward.id})

    def _getLocationFromAPI(self, code):
        response = self.query(
            '''
            query {
                locations(code:"%s") {
                    edges {
                        node {
                            id name code type
                        }
                    }
                }
            }
            ''' % (code,),
            headers={"HTTP_AUTHORIZATION": f"Bearer {self.admin_token}"},
        )

        self.assertEquals(response.status_code, status.HTTP_200_OK)
        content = json.loads(response.content)

        self.assertResponseNoErrors(response)
        return content["data"]["locations"]["edges"][0]["node"]

    def test_basic_locations_query(self):
        response = self.query(
            '''
            query {
                locations {
                    edges {
                        node {
                            id
                            name
                        }
                    }
                }
            }
            ''',
            headers={"HTTP_AUTHORIZATION": f"Bearer {self.admin_token}"},
        )

        self.assertEquals(response.status_code, status.HTTP_200_OK)
        content = json.loads(response.content)

        # This validates the status code and if you get errors
        self.assertResponseNoErrors(response)

        # Add some more asserts if you like
        self.assertGreater(len(content["data"]["locations"]["edges"]), 0)
        self.assertIsNotNone(content["data"]["locations"]["edges"][0]["node"]["id"])
        self.assertIsNotNone(content["data"]["locations"]["edges"][0]["node"]["name"])

    def _test_arg_locations_query(self, arg, token=None):
        response = self.query(
            '''
            query {
                locations(%s) {
                    edges {
                        node {
                            id
                            name
                        }
                    }
                }
            }
            ''' % (arg,),
            headers={"HTTP_AUTHORIZATION": f"Bearer {token if token else self.admin_token}"},
        )

        self.assertEquals(response.status_code, status.HTTP_200_OK)
        content = json.loads(response.content)

        self.assertResponseNoErrors(response)

        self.assertEqual(len(content["data"]["locations"]["edges"]), 1)
        self.assertEqual(content["data"]["locations"]["edges"][0]["node"]["name"], self.test_region.name)
        self.assertEqual(content["data"]["locations"]["edges"][0]["node"]["id"],
                         base64.b64encode(f"LocationGQLType:{self.test_region.id}".encode("utf8")).decode("ascii"))

    def test_code_locations_query(self):
        self._test_arg_locations_query('code:"%s"' % self.test_region.code)
        self._test_arg_locations_query('name:"%s"' % self.test_region.name)
        self._test_arg_locations_query('name_Icontains:"Test ", type:"R"')

    def test_code_locations_district_limited_query(self):
        """
        This test corresponds to OMT-280 where the Admin with UserDistricts would create a Region which would then
        not appear in the resulting list of locations since there are no districts inside the Region yet and certainly
        not in the UserDistricts.
        The adapted rule is that if the user is allowed to create locations, he should also see all of them.
        In this test, the self.test_region etc are not in the admin_dist_token ["R1D1", "R2D1", "R2D2"]
        """
        self._test_arg_locations_query('code:"%s"' % self.test_region.code, token=self.admin_dist_token)

    def test_no_auth_locations_query(self):
        """ Query without any auth token """
        response = self.query(' query { medicalLocations { edges { node { id name } } } } ')

        self.assertResponseHasErrors(response)

    def test_no_right_locations_query(self):
        """ Query with a valid token but not the right to perform this operation """
        response = self.query(' query { medicalLocations { edges { node { id name } } } } ',
                              headers={"HTTP_AUTHORIZATION": f"Bearer {self.noright_token}"})

        self.assertResponseHasErrors(response)

    def test_full_locations_query(self):
        response = self.query(
            '''
            query {
                locations {
                    edges {
                        node {
                                  id
                                  name
                                  validityFrom
                                  validityTo
                                  legacyId
                                  uuid
                                  code
                                  type
                                  parent { id }
                                  malePopulation
                                  femalePopulation
                                  otherPopulation
                                  families
                                  auditUserId
                        }
                    }
                }
            }
            ''',
            headers={"HTTP_AUTHORIZATION": f"Bearer {self.admin_token}"},
        )

        self.assertEquals(response.status_code, status.HTTP_200_OK)
        content = json.loads(response.content)

        self.assertResponseNoErrors(response)

        self.assertGreater(len(content["data"]["locations"]["edges"]), 0)
        self.assertIsNotNone(content["data"]["locations"]["edges"][0]["node"]["id"])
        self.assertIsNotNone(content["data"]["locations"]["edges"][0]["node"]["name"])

    def test_mutation_create_location(self):
        response = self.query(
            '''
            mutation {
              createLocation(input: {
                clientMutationId:"tstlocgql1",
                code:"tstrgx",
                name:"Test Region X",
                type:"R",
                malePopulation: 1,
                femalePopulation: 2,
                families: 3,
                otherPopulation: 4,
              }) {
                internalId
                clientMutationId
              }
            }
            ''',
            headers={"HTTP_AUTHORIZATION": f"Bearer {self.admin_token}"},
        )

        self.assertEquals(response.status_code, status.HTTP_200_OK)
        content = json.loads(response.content)

        self.assertResponseNoErrors(response)

        self.assertEqual(content["data"]["createLocation"]["clientMutationId"], "tstlocgql1")

        db_location = Location.objects.get(code="tstrgx")
        self.assertIsNotNone(db_location)
        self.assertEqual(db_location.name, "Test Region X")
        self.assertEqual(db_location.type, "R")
        self.assertEqual(db_location.male_population, 1)
        self.assertEqual(db_location.female_population, 2)
        self.assertEqual(db_location.families, 3)
        self.assertEqual(db_location.other_population, 4)

        retrieved_item = self._getLocationFromAPI(code="tstrgx")
        self.assertIsNotNone(retrieved_item)
        self.assertEqual(retrieved_item["name"], db_location.name)

    def test_mutation_delete_location(self):
        response = self.query(
            '''
            mutation {
              deleteLocation(input: {
                uuid: "%s"
                clientMutationId: "testlocation5"
              }) {
                internalId
                clientMutationId
              }
            }
            ''' % self.test_location_delete.uuid,
            headers={"HTTP_AUTHORIZATION": f"Bearer {self.admin_token}"},
        )

        self.assertEquals(response.status_code, status.HTTP_200_OK)
        content = json.loads(response.content)

        self.assertResponseNoErrors(response)
        self.assertEqual(content["data"]["deleteLocation"]["clientMutationId"], "testlocation5")

        self.test_location_delete.refresh_from_db()

        self.assertIsNotNone(self.test_location_delete.validity_to)

        # TODO test the newParentUUID
