import datetime
import json

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.translation import gettext as _

from core.signals import register_service_signal
from location.apps import LocationConfig
from location.models import Location, HealthFacility, HealthFacilityCatchment, UserDistrict


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


class LocationService:
    def __init__(self, user):
        self.user = user

    @staticmethod
    def check_unique_code(code):
        if Location.objects.filter(code=code, validity_to__isnull=True).exists():
            return [{"message": "Location code %s already exists" % code}]
        return []

    def validate_data(self, **data):
        error = None
        error = self.check_unique_code(data["code"])

        return error

    @register_service_signal('location_service.update_or_create')
    def update_or_create(self, data):
        location_uuid = data.pop('uuid') if 'uuid' in data else None
        parent_uuid = data.pop('parent_uuid') if 'parent_uuid' in data else None
        # update_or_create(uuid=location_uuid, ...)
        # doesn't work because of explicit attempt to set null to uuid!
        loc_type = data.get('type', None)
        if loc_type in ['R', 'D'] \
                and not self.user.has_perms(
                    LocationConfig.gql_mutation_create_region_locations_perms
                ) \
                and not self.user.is_superuser:
            raise PermissionDenied(_("unauthorized to create or update region and district"))
        if loc_type in ['M', 'V'] \
                and not self.user.has_perms(
            LocationConfig.gql_mutation_create_region_locations_perms
        ) \
                and not self.user.has_perms(
            LocationConfig.gql_mutation_create_locations_perms
        ) \
                and not self.user.is_superuser:
            raise PermissionDenied(_("unauthorized to create or update municipalities and villages"))
        if location_uuid:
            location = Location.objects.get(uuid=location_uuid)
            self._reset_location_before_update(location)
            [setattr(location, key, data[key]) for key in data]
        else:
            error = self.validate_data(**data)
            if error:
                raise ValueError(error)
            else:
                location = Location.objects.create(**data)

        if parent_uuid:
            location.parent = Location.objects.get(uuid=parent_uuid)
        location.save()
        self._ensure_user_belongs_to_district(location)

    @staticmethod
    def _reset_location_before_update(location):
        location.male_population = None
        location.female_population = None
        location.other_population = None
        location.families = None

    def _ensure_user_belongs_to_district(self, location: Location):
        if location.type == 'D':
            UserDistrict.objects.get_or_create(
                user=self.user.i_user,
                location=location,
                audit_user_id=self.user.id_for_audit,
            )


class HealthFacilityService:
    def __init__(self, user):
        self.user = user

    @staticmethod
    def check_unique_code(code):
        if HealthFacility.objects.filter(code=code, validity_to__isnull=True).exists():
            return [{"message": "Health facility code %s already exists" % code}]
        return []

    @register_service_signal('health_facility_service.update_or_create')
    def update_or_create(self, data):
        hf_uuid = data.pop('uuid') if 'uuid' in data else None
        catchments = data.pop('catchments') if 'catchments' in data else []
        # address may be multiline > sent as JSON
        # update_or_create(uuid=location_uuid, ...)
        # doesn't work because of explicit attempt to set null to uuid!
        prev_hf_id = None
        if hf_uuid:
            hf = HealthFacility.objects.get(uuid=hf_uuid)
            prev_hf_id = hf.save_history()
            # reset the non required fields
            # (each update is 'complete', necessary to be able to set 'null')
            self._reset_health_facility_before_update(hf)
            [setattr(hf, key, data[key]) for key in data]
        else:
            hf = HealthFacility.objects.create(**data)
        self._process_catchments(catchments, prev_hf_id, hf.id, hf.catchments)
        hf.save()
        return hf

    def _process_catchments(self, data_catchments, prev_hf_id, hf_id, catchments):
        prev_catchments = [c.id for c in catchments.all()]
        from core.utils import TimeUtils
        for catchment in data_catchments:
            catchment_id = catchment.pop('id') if 'id' in catchment else None
            if catchment_id:
                prev_catchments.remove(catchment_id)
                prev_catchment = catchments.filter(id=catchment_id, **catchment).first()
                if not prev_catchment:
                    # catchment has been updated, let's bind the old value to prev_hf
                    prev_catchment = catchments.get(id=catchment_id)
                    prev_catchment.health_facility_id = prev_hf_id
                    prev_catchment.save()
                    # ... and create a new one with the new values
                    catchment['validity_from'] = TimeUtils.now()
                    catchment['audit_user_id'] = self.user.id_for_audit
                    catchment['health_facility_id'] = hf_id
                    HealthFacilityCatchment.objects.create(**catchment)
            else:
                catchment['validity_from'] = TimeUtils.now()
                catchment['audit_user_id'] = self.user.id_for_audit
                catchment['health_facility_id'] = hf_id
                HealthFacilityCatchment.objects.create(**catchment)

        if prev_catchments:
            catchments.filter(id__in=prev_catchments).update(
                health_facility_id=prev_hf_id,
                validity_to=TimeUtils.now())

    @staticmethod
    def _reset_health_facility_before_update(hf):
        hf.code = None
        hf.name = None
        hf.acc_code = None
        hf.legal_form = None
        hf.level = None
        hf.sub_level = None
        hf.location = None
        hf.address = None
        hf.phone = None
        hf.fax = None
        hf.email = None
        hf.care_type = None
        hf.services_pricelist = None
        hf.items_pricelist = None
