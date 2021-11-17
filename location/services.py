import json

from django.contrib.auth.models import AnonymousUser
from django.core.serializers.json import DjangoJSONEncoder

from location.apps import LocationConfig


def check_authentication(function):
    def wrapper(self, *args, **kwargs):
        if type(self.user) is AnonymousUser or not self.user.id:
            return {
                "success": False,
                "message": "Authentication required",
                "detail": "PermissionDenied",
            }
        else:
            result = function(self, *args, **kwargs)
            return result

    return wrapper


class HealthFacilityLevel(object):
    def __init__(self, user):
        self.user = user

    @check_authentication
    def get_all(self):
        return _output_result_success(LocationConfig.health_facility_level)


def _output_result_success(dict_representation):
    return {
        "success": True,
        "message": "Ok",
        "detail": "",
        "data": json.loads(json.dumps(dict_representation, cls=DjangoJSONEncoder)),
    }
