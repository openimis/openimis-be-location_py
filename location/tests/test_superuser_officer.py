"""
OP-3282: a superuser who is also an enrolment officer (an Officer whose code is
the login name) was limited to that officer's villages by get_allowed_ids, while
every other location check lets a superuser through. On release the individual
import rejected every UAT baseline village for Admin (UAT OCM-1128).
"""
from django.core.cache import caches
from django.test import TestCase

from core.test_helpers import create_test_interactive_user, create_test_officer
from core.utils import clear_access_cache
from location.models import LocationManager
from location.test_helpers import create_test_village


class SuperuserOfficerAllowedLocationsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.officer_village = create_test_village({"code": "OP3282V1"})
        cls.other_district = create_test_village({"code": "OP3282V2"}).parent.parent

    def setUp(self):
        caches["default"].clear()
        caches["location"].clear()
        clear_access_cache()

    def _officer_user(self, username, superuser):
        user = create_test_interactive_user(username=username, custom_props={"is_superuser": superuser})
        # has_login: the officer is the user's own login (InteractiveUser.is_officer)
        create_test_officer(custom_props={"code": username, "has_login": True}, villages=[self.officer_village])
        # creating the user already looked up (and kept) "not an officer"
        self.setUp()
        return user

    def test_superuser_is_not_limited_to_its_officer_villages(self):
        user = self._officer_user("op3282super", superuser=True)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.i_user.is_officer)

        self.assertIn(self.other_district.id, LocationManager().get_allowed_ids(user))

    def test_officer_keeps_its_villages(self):
        user = self._officer_user("op3282officer", superuser=False)

        self.assertEqual([self.officer_village.id], list(LocationManager().get_allowed_ids(user)))
