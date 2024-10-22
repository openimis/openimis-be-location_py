import json
from typing import Union
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q
from django.utils.translation import gettext as _

from core.signals import register_service_signal
from location.apps import LocationConfig
from location.models import (
    Location,
    HealthFacility,
    HealthFacilityCatchment,
    UserDistrict,
)


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


def get_ancestor_location_filter(
    ancestor_uuid: Union[str, UUID], location_field="location", levels=4
) -> Q:
    """
    A generic service that return a Q object that can be used to filter if a model belongs to a location
    or any of its children.

    :param ancestor_uuid: UUID of the target location
    :param location_field: The name of the location field in the filtered model
    :param levels: The number of location levels to search up. Should not change until location rework.
    :return: Q object that checks parent locations "levels" levels deep
    """
    filters = Q(
        **{
            location_field + "__uuid": ancestor_uuid,
            location_field + "__validity_to__isnull": True,
        }
    )
    for i in range(1, levels):
        filters = filters | Q(
            **{
                location_field + "__parent" * i + "__uuid": ancestor_uuid,
                location_field + "__parent" * i + "__validity_to__isnull": True,
            }
        )
    return filters


class HealthFacilityLevel:
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

    @register_service_signal("location_service.update_or_create")
    def update_or_create(self, data):
        location_uuid = data.pop("uuid") if "uuid" in data else None
        parent_uuid = data.pop("parent_uuid") if "parent_uuid" in data else None
        incoming_code = data.get("code")
        current_location = Location.objects.filter(uuid=location_uuid).first()
        current_code = current_location.code if current_location else None
        if current_code != incoming_code:
            if self.check_unique_code(incoming_code):
                raise ValidationError(_("mutation.location_code_duplicated"))
        # update_or_create(uuid=location_uuid, ...)
        # doesn't work because of explicit attempt to set null to uuid!
        self._check_users_locations_rights(data["type"])
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

    def _check_users_locations_rights(self, loc_type):
        if self.user.is_superuser or self.user.has_perms(
            LocationConfig.gql_mutation_create_region_locations_perms
        ):
            pass
        elif loc_type in ["R", "D"]:
            raise PermissionDenied(_("unauthorized_to_create_update_region_district"))
        elif not self.user.has_perms(
            LocationConfig.gql_mutation_create_locations_perms
        ):
            raise PermissionDenied(
                _("unauthorized_to_create_or_update_municipalities_and_villages")
            )

    @staticmethod
    def _reset_location_before_update(location):
        location.male_population = None
        location.female_population = None
        location.other_population = None
        location.families = None

    def _ensure_user_belongs_to_district(self, location: Location):
        if location.type == "D":
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

    @register_service_signal("health_facility_service.update_or_create")
    def update_or_create(self, data):
        contract_start_date = data.get("contract_start_date", None)
        contract_end_date = data.get("contract_end_date", None)
        if LocationConfig.health_facility_contract_dates_mandatory:
            if not contract_start_date or not contract_end_date:
                raise ValidationError(_("mutation.contract_dates_required"))
        if bool(contract_start_date) ^ bool(contract_end_date):
            raise ValidationError(_("mutation.single_date_hf_contract"))
        if (
            contract_start_date and contract_end_date and contract_end_date <= contract_start_date
        ):
            raise ValidationError(_("mutation.incorrect_hf_contract_date_range"))
        if (
            "status" in data and data["status"] not in HealthFacility.HealthFacilityStatus
        ):
            raise ValidationError(_("mutation.incorrect_hf_status"))
        hf_uuid = data.pop("uuid") if "uuid" in data else None
        catchments = data.pop("catchments") if "catchments" in data else []
        # address may be multiline > sent as JSON
        # update_or_create(uuid=location_uuid, ...)
        # doesn't work because of explicit attempt to set null to uuid!
        prev_hf_id = None
        if hf_uuid:
            hf = HealthFacility.objects.get(uuid=hf_uuid)
            if hf.validity_to:
                raise ValidationError(_("cannot_update_historical_hf"))
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
            catchment_id = catchment.pop("id") if "id" in catchment else None
            if catchment_id:
                prev_catchments.remove(catchment_id)
                prev_catchment = catchments.filter(id=catchment_id, **catchment).first()
                if not prev_catchment:
                    # catchment has been updated, let's bind the old value to prev_hf
                    prev_catchment = catchments.get(id=catchment_id)
                    prev_catchment.health_facility_id = prev_hf_id
                    prev_catchment.save()
                    # ... and create a new one with the new values
                    catchment["validity_from"] = TimeUtils.now()
                    catchment["audit_user_id"] = self.user.id_for_audit
                    catchment["health_facility_id"] = hf_id
                    HealthFacilityCatchment.objects.create(**catchment)
            else:
                catchment["validity_from"] = TimeUtils.now()
                catchment["audit_user_id"] = self.user.id_for_audit
                catchment["health_facility_id"] = hf_id
                HealthFacilityCatchment.objects.create(**catchment)

        if prev_catchments:
            catchments.filter(id__in=prev_catchments).update(
                health_facility_id=prev_hf_id, validity_to=TimeUtils.now()
            )

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
