import base64
import json
from dataclasses import dataclass

from core.models import User
from core.test_helpers import create_test_interactive_user
from django.conf import settings
from django.core import exceptions
from graphene_django.utils.testing import GraphQLTestCase
from graphql_jwt.shortcuts import get_token
from location.models import Location, HealthFacility, HealthFacilityLegalForm
from location.test_helpers import create_test_location, assign_user_districts,create_test_village
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
    test_region = None
    test_district = None
    test_village = None
    test_ward = None
    test_location_delete = None
    @classmethod
    def setUpTestData(cls):
        if cls.test_region is None:
            cls.test_village  =create_test_village()
            cls.test_ward =cls.test_village.parent
            cls.test_region =cls.test_village.parent.parent.parent
            cls.test_district = cls.test_village.parent.parent
        cls.admin_user = create_test_interactive_user(username="testLocationAdmin")
        cls.admin_token = get_token(cls.admin_user, DummyContext(user=cls.admin_user))
        cls.noright_user = create_test_interactive_user(username="testLocationNoRight", roles=[1])
        cls.noright_token = get_token(cls.noright_user, DummyContext(user=cls.noright_user))
        cls.admin_dist_user = create_test_interactive_user(username="testLocationDist")
        assign_user_districts(cls.admin_dist_user, ["R1D1", "R2D1", "R2D2"])
        cls.admin_dist_token = get_token(cls.admin_dist_user, DummyContext(user=cls.admin_dist_user))
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


class HealthFacilityGQLTestCase(GraphQLTestCase):
    GRAPHQL_URL = f'/{settings.SITE_ROOT()}graphql'
    # This is required by some version of graphene but is never used. It should be set to the schema but the import
    # is shown as an error in the IDE, so leaving it as True.
    GRAPHQL_SCHEMA = True
    admin_user = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin_user = create_test_interactive_user(username="testHFAdmin")
        cls.admin_token = get_token(cls.admin_user, DummyContext(user=cls.admin_user))
        cls.noright_user = create_test_interactive_user(username="testHFNoRight", roles=[1])
        cls.noright_token = get_token(cls.noright_user, DummyContext(user=cls.noright_user))
        cls.admin_dist_user = create_test_interactive_user(username="testHFDist")
        assign_user_districts(cls.admin_dist_user, ["R1D1", "R2D1", "R2D2"])
        cls.admin_dist_token = get_token(cls.admin_dist_user, DummyContext(user=cls.admin_dist_user))

    def _getHFFromAPI(self, code):
        """
        Utility method that fetches HF from GraphQL whose code matches the given parameter.
        If multiple HF have the same code, this method will fail.
        """
        query = f"""
            {{
                healthFacilities(code:"{code}") {{
                    edges {{
                        node {{
                            id name code level
                        }}
                    }}
                }}
            }}
        """
        response = self.query(query, headers={"HTTP_AUTHORIZATION": f"Bearer {self.admin_dist_token}"})

        self.assertEquals(response.status_code, status.HTTP_200_OK)
        content = json.loads(response.content)

        self.assertResponseNoErrors(response)
        return content["data"]["healthFacilities"]["edges"][0]["node"]

    def test_mutation_create_health_facility_minimal_mandatory_fields(self):
        """
        This method tests that an HF can be created with its minimal mandatory fields.
        This method creates an HF by using the GraphQL API, checks that a matching HF
        is found in the database through the ORM, asks GraphQL for the newly created HF
        and compares the database-fetched HF to the GraphQL-fetched one.
        """
        client_mutation_id = "tsthfgql1"
        code = "tsthfx"
        name = "Test HF X"
        legal_form = HealthFacilityLegalForm.objects.filter(code='C').first()
        level = "H"
        location = Location.objects.filter(code='R1D1', validity_to__isnull=True).first()  # create_test_location('V')
        care_type = "B"
        query = f"""
            mutation {{
              createHealthFacility(input: {{
                clientMutationId:"{client_mutation_id}"
                clientMutationLabel: "Create Health Facility {name}"
                code:"{code}"
                name:"{name}"
                legalFormId:"{legal_form.code}"
                level:"{level}"
                locationId:{location.id}
                careType: "{care_type}"
              }}) {{
                internalId
                clientMutationId
              }}
            }}
        """
        response = self.query(query,
                              headers={"HTTP_AUTHORIZATION": f"Bearer {self.admin_token}"},
                              )

        self.assertEquals(response.status_code, status.HTTP_200_OK)
        content = json.loads(response.content)

        self.assertResponseNoErrors(response)

        self.assertEqual(content["data"]["createHealthFacility"]["clientMutationId"], client_mutation_id)

        db_hf = HealthFacility.objects.filter(code=code, validity_to__isnull=True).first()
        self.assertIsNotNone(db_hf)
        self.assertEqual(db_hf.name, name)
        self.assertEqual(db_hf.code, code)
        self.assertEqual(db_hf.legal_form, legal_form)
        self.assertEqual(db_hf.level, level)
        self.assertEqual(db_hf.location, location)
        self.assertEqual(db_hf.care_type, care_type)

        retrieved_item = self._getHFFromAPI(code=code)
        self.assertIsNotNone(retrieved_item)
        self.assertEqual(retrieved_item["name"], db_hf.name)
        self.assertEqual(retrieved_item["code"], db_hf.code)

    def test_mutation_create_health_facility_error_mandatory_fields(self):
        """
        This method tests that a health facility cannot be created through the GraphQL API
        if any of its mandatory fields is not present.
        In this case, the `legal_form` field is missing.
        """
        client_mutation_id = "tsthfgql2"
        code = "tsthfx2"
        name = "Test HF X2"
        level = "D"
        location = create_test_location('V')
        care_type = "I"
        query = f"""
            mutation {{
              createHealthFacility(input: {{
                clientMutationId:"{client_mutation_id}",
                code:"{code}",
                name:"{name}",
                level:"{level}",
                locationId:{location.id},
                careType: "{care_type}",
              }}) {{
                internalId
                clientMutationId
              }}
            }}
        """
        response = self.query(query,
                              headers={"HTTP_AUTHORIZATION": f"Bearer {self.admin_token}"},
                              )

        self.assertEquals(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertResponseHasErrors(response)

        with self.assertRaises(exceptions.ObjectDoesNotExist):
            HealthFacility.objects.get(code=code)
