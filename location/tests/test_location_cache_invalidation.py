"""Invalidation of the per-user location caches.

Those entries are written with ``timeout=None``, so a missed invalidation is
permanent: a village moved to another district keeps resolving against its old
branch for the life of the cache server. The existing coverage exercised only
LocMemCache, which takes the ``clear()`` path -- the Redis path, the one
production runs, is the one that was broken.
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django_redis.cache import RedisCache

from location import models as location_models
from location.models import free_cache_for_user


class FreeCacheForUserTest(TestCase):

    @staticmethod
    def _deleted_keys(mock_cache):
        return [call.args[0] for call in mock_cache.delete.call_args_list]

    def test_one_user_deletes_only_that_users_keys(self):
        cache = MagicMock()
        with patch.object(location_models, "cache", cache):
            free_cache_for_user(42)

        self.assertEqual(
            ["user_locations_42", "user_districts_42"], self._deleted_keys(cache)
        )
        cache.clear.assert_not_called()

    def test_wildcard_on_redis_globs(self):
        # cache.delete() is literal: passing "*" deleted a key *named*
        # "user_locations_*" and invalidated nothing. Globbing is django-redis'
        # delete_pattern, and this backend is the only one that has it.
        cache = MagicMock(spec=RedisCache)
        with patch.object(location_models, "cache", cache):
            free_cache_for_user()

        self.assertEqual(
            ["user_locations_*", "user_districts_*"],
            [call.args[0] for call in cache.delete_pattern.call_args_list],
        )
        cache.delete.assert_not_called()

    def test_wildcard_without_globbing_clears_everything(self):
        # No delete_pattern to reach for, so the only way to honour "everyone"
        # is to drop the whole cache.
        cache = MagicMock()
        with patch.object(location_models, "cache", cache):
            free_cache_for_user()

        cache.clear.assert_called_once_with()
        cache.delete.assert_not_called()
