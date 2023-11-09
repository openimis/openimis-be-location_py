from django.test import TestCase
from location.test_helpers import create_test_village
from location.models import LocationManager
from core.services import create_or_update_interactive_user, create_or_update_core_user, create_or_update_user_districts


_TEST_USER_NAME = "test_batch_run"
_TEST_USER_PASSWORD = "test_batch_run"
_TEST_DATA_USER = {
    "username": _TEST_USER_NAME,
    "last_name": _TEST_USER_NAME,
    "password": _TEST_USER_PASSWORD,
    "other_names": _TEST_USER_NAME,
    "user_types": "INTERACTIVE",
    "language": "en",
    "roles": [1, 5, 9],
}
# Create your tests here.
class LocationTest(TestCase):
    test_village = None
    test_user = None
    
    @classmethod
    def setUpTestData(cls):
        cls.test_village = create_test_village()
        cls.test_user, i_user_created = create_or_update_interactive_user(
            user_id=None, data=_TEST_DATA_USER, audit_user_id=999, connected=False
        )
        create_or_update_core_user(
            user_uuid=None, username='loctest', i_user=cls.test_user)
        
        create_or_update_user_districts(cls.test_user, [cls.test_village.parent.parent.id], -1)


    def test_parents(self):
        hierachy = LocationManager().parents(self.test_village.id)
        self.assertEqual(len(hierachy),4)
        district = LocationManager().parents(self.test_village.id, loc_type = 'D')
        self.assertEqual(len(district),1)
        
    def test_children(self):
        village = create_test_village()
        hierachy = LocationManager().children(self.test_village.parent.parent.parent.id)
        self.assertEqual(len(hierachy),4)
        district = LocationManager().children(self.test_village.parent.parent.parent.id, loc_type = 'D')
        self.assertEqual(len(district),1)
        
    def test_allowed_location(self):
        allowed = LocationManager().get_locations_allowed(self.test_user.id)
        self.assertEqual(len(allowed),3)
