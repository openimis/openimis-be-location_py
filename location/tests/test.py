from django.test import TestCase
from location.test_helpers import (
    create_test_village,
    create_test_health_facility,
    create_test_location,
    assign_user_districts
)
from core.test_helpers import create_test_officer, create_test_interactive_user
from claim.test_helpers import create_test_claim_admin
from django.core.cache import cache

from location.models import LocationManager
from core.services import create_or_update_interactive_user, create_or_update_core_user, create_or_update_user_districts
from core.utils import filter_validity
from core.models.user import Role

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
    test_hf = None
    test_ca = None
    test_eo = None
    test_user_eo = None
    test_user_ca = None
    other_loc = None
    
    @classmethod
    def setUpTestData(cls):
        cls.test_village = create_test_village()
        
        ca_role = Role.objects.filter(is_system=16, *filter_validity()).first()
        eo_role = Role.objects.filter(is_system=1, *filter_validity()).first()
        xx_role = Role.objects.filter(is_system=2, *filter_validity()).first()
        cls.test_user = create_test_interactive_user(username='loctest', roles=[xx_role.id] )
        cls.test_hf = create_test_health_facility(location_id=cls.test_village.parent.parent_id)
        cls.test_user_ca = create_test_interactive_user(
            username="tst_ca", 
            roles=[ca_role.id],
            custom_props={'health_facility_id': cls.test_hf.id}
        )
        cls.test_user_eo = create_test_interactive_user(username="tst_eo", roles=[eo_role.id],)
        cls.other_loc = create_test_location('D', custom_props={'parent': cls.test_village.parent.parent.parent, 'code': 'NOTALLO'})
        assign_user_districts(cls.test_user, [cls.test_village.parent.parent.code])
        
        cls.test_ca = create_test_claim_admin(custom_props={
            'health_facility_id': cls.test_hf.id,
            'code': cls.test_user_ca.username,
            'has_login': True
        })
        cls.test_eo = create_test_officer(
            villages=[cls.test_village],
            custom_props={
                'code': cls.test_user_eo.username,
                'has_login': True
            }
        )


    def test_parents(self):
        hierachy = LocationManager().parents(self.test_village.id)
        self.assertEqual(len(hierachy), 4)
        district = LocationManager().parents(self.test_village.id, loc_type='D')
        self.assertEqual(len(district), 1)
        
    def test_children(self):
        hierachy = LocationManager().children(self.test_village.parent.parent.parent.id)
        self.assertEqual(len(hierachy), 5)
        district = LocationManager().children(self.test_village.parent.parent.parent.id, loc_type='D')
        self.assertEqual(len(district), 2)
        
    def test_allowed_location(self):
        allowed = LocationManager().allowed(self.test_user._u.id, loc_types=['V', 'D', 'W'])
        self.assertEqual(len(allowed), 3)
        self.assertTrue(LocationManager().is_allowed(self.test_user, [self.test_village.parent.parent.id]), 'is_allowed function is not working as supposed')
        
        allowed = LocationManager().allowed(self.test_user._u.id, loc_types=['R', 'D', 'W'])
        self.assertEqual(len(allowed), 2)
        self.assertFalse(LocationManager().is_allowed(self.test_user, [self.other_loc.id, self.test_village.parent.parent.id]), 'is_allowed function is not working as supposed')
        cached = cache.get(f"user_locations_s_{self.test_user._u.id}")
        self.assertIsNotNone(cached)
 
    def test_allowed_location_eo(self):
        self.assertFalse(
            LocationManager().is_allowed(
                self.test_user_eo,
                [self.test_village.id, self.test_village.parent.parent_id]
            ), 
            'is_allowed function is not working as supposed'
        )
        self.assertFalse(
            LocationManager().is_allowed(
                self.test_user_eo,
                [self.other_loc.id, self.test_village.id, self.test_village.parent.parent_id],
                strict=False
            ), 
            'is_allowed function is not working as supposed'
        )
        self.assertTrue(
            LocationManager().is_allowed(
                self.test_user_eo,
                [self.test_village.id, self.test_village.parent.parent_id],
                strict=False
            ), 
            'is_allowed function is not working as supposed'
        )
        self.assertTrue(
            LocationManager().is_allowed(
                self.test_user_eo,
                [self.test_village.id, self.test_village.parent.parent_id],
                strict=False
            ), 
            'is_allowed function is not working as supposed'
        )

    
    def test_allowed_location_ca(self):
        self.assertFalse(
            LocationManager().is_allowed(
                self.test_user_ca,
                [self.test_village.parent.parent_id, self.test_village.parent.parent.parent_id]
            ), 
            'is_allowed function is not working as supposed'
        )
        self.assertFalse(
            LocationManager().is_allowed(
                self.test_user_ca,
                [self.other_loc.id, self.test_village.parent.parent_id, self.test_village.parent.parent.parent_id],
                strict=False
            ), 
            'is_allowed function is not working as supposed'
        )
        self.assertTrue(
            LocationManager().is_allowed(
                self.test_user_ca,
                [self.test_village.parent.parent_id, self.test_village.parent.parent.parent_id],
                strict=False
            ), 
            'is_allowed function is not working as supposed'
        )
        self.assertTrue(
            LocationManager().is_allowed(
                self.test_user_ca,
                [self.test_village.parent.parent_id]
            ), 
            'is_allowed function is not working as supposed'
        )
        