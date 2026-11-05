"""
OP-3281: the per-user location sets must not outlive the writes that change them.

On release the individual import rejected villages Admin was allowed (UAT
OCM-1128): ``user_locations_<id>`` was cached with no expiry, and the
invalidation ran in the Celery worker (async mutations), never reaching the
web processes' copies.
"""
import time
from unittest import mock

from django.core.cache import caches
from django.db import transaction
from django.test import TestCase, override_settings

import core
from core.cache_control import get_cache_info
from core.test_helpers import create_test_interactive_user
from core.utils import clear_access_cache
from location.models import LocationManager, UserDistrict
from location.test_helpers import assign_user_districts, create_test_village


def async_mutations(enabled):
    return mock.patch.object(core, "async_mutations", enabled, create=True)


def district_of(village):
    return village.parent.parent


# The test settings' own caches are used, not an override: location.models binds
# its cache when imported, and an overridden CACHES would be a different store.
@override_settings(CACHE_OBJECT_TTL=1234)
class LocationCacheCoherenceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first = district_of(create_test_village({"code": "OP3281V1"}))
        cls.second = district_of(create_test_village({"code": "OP3281V2"}))
        # not a superuser: its allowed set comes from its own district assignments
        cls.user = create_test_interactive_user(username="op3281user", custom_props={"is_superuser": False})
        assign_user_districts(cls.user, [cls.first.code])

    def setUp(self):
        if get_cache_info("location")["backend_short"] != "LocMemCache":
            self.skipTest("needs the process-local cache of the test settings")
        caches["location"].clear()
        clear_access_cache()

    def _assign_without_signals(self, district):
        # what a write made in another process (the Celery worker) looks like here:
        # the row exists, and nothing in this process heard about it
        UserDistrict.objects.bulk_create([UserDistrict(
            user=self.user.i_user, location=district, validity_from="2019-06-01", audit_user_id=-1,
        )])

    def test_district_assigned_elsewhere_is_allowed_in_the_next_request(self):
        with async_mutations(True):
            self.assertNotIn(self.second.id, LocationManager().get_allowed_ids(self.user))
            self._assign_without_signals(self.second)

            clear_access_cache()  # the next request
            self.assertIn(self.second.id, LocationManager().get_allowed_ids(self.user))

    def test_stale_entry_written_before_commit_is_dropped_at_commit(self):
        with async_mutations(False):  # coherent cache: entries are stored and invalidated
            stale = LocationManager().get_allowed_ids(self.user)
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    assign_user_districts(self.user, [self.second.code])
                    # a concurrent request, reading committed data, rebuilds the old set
                    caches["location"].set(f"user_locations_{self.user.i_user.id}", stale)
            self.assertIn(self.second.id, LocationManager().get_allowed_ids(self.user))

    def test_allowed_set_expires(self):
        with async_mutations(False):
            LocationManager().get_allowed_ids(self.user)
        backend = caches["location"]
        expiry = backend._expire_info.get(backend.make_key(f"user_locations_{self.user.i_user.id}"))
        self.assertIsNotNone(expiry, "the allowed set must be cached with an expiry")
        self.assertAlmostEqual(expiry - time.time(), 1234, delta=5)
