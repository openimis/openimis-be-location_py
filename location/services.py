import json
import random
from datetime import date
from typing import Union
from uuid import UUID

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from core.signals import register_service_signal
from location.apps import LocationConfig
from location.models import (
    Location,
    HealthFacility,
    HealthFacilityCatchment,
    UserDistrict,
    MicroCatchment,
    MicroCatchmentTA,
    MicroCatchmentGVH,
    allowed_micro_catchment_district_ids,
    Catchment,
    CatchmentDistrict,
)


CODE_RANDOM_DIGITS = 5
CODE_GENERATION_ATTEMPTS = 20


def generate_unique_catchment_code(model, current_date=None):
    """Build a `<year><random 5-digit suffix>` code, retrying on collision."""
    year = (current_date or date.today()).year
    for _ in range(CODE_GENERATION_ATTEMPTS):
        suffix = random.randint(0, 10 ** CODE_RANDOM_DIGITS - 1)
        code = f"{year}{suffix:0{CODE_RANDOM_DIGITS}d}"
        if not model.objects.filter(code=code, validity_to__isnull=True).exists():
            return code
    raise ValueError("Unable to generate a unique catchment code, please retry.")


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


class MicroCatchmentService:
    def __init__(self, user):
        self.user = user

    def _validate_micro_catchment_relations(self, data, ta_ids, gvh_ids):
        district_id = data.get("district_id")
        if not district_id:
            raise ValidationError("District is required")

        if not ta_ids:
            raise ValidationError("At least one Traditional Authority is required")

        if not gvh_ids:
            raise ValidationError("At least one GVH is required")

        # Malawi hierarchy: District = type R, TA = type D, GVH = type W, Village = type V.
        district = Location.objects.filter(
            id=district_id,
            type="R",
            validity_to__isnull=True,
        ).first()
        if not district:
            raise ValidationError("Invalid district")

        allowed_district_ids = allowed_micro_catchment_district_ids(self.user)
        if allowed_district_ids is not None and district.id not in allowed_district_ids:
            raise PermissionDenied(_("unauthorized"))

        ta_ids_set = set(ta_ids)
        valid_ta_ids = set(
            Location.objects.filter(
                id__in=ta_ids_set,
                type="D",
                parent_id=district.id,
                validity_to__isnull=True,
            ).values_list("id", flat=True)
        )
        if valid_ta_ids != ta_ids_set:
            raise ValidationError("Traditional Authorities must belong to the selected district")

        gvh_ids_set = set(gvh_ids)
        valid_gvh_ids = set(
            Location.objects.filter(
                id__in=gvh_ids_set,
                type="W",
                parent_id__in=valid_ta_ids,
                validity_to__isnull=True,
            ).values_list("id", flat=True)
        )
        if valid_gvh_ids != gvh_ids_set:
            raise ValidationError("GVHs must belong to selected Traditional Authorities")

    @register_service_signal("micro_catchment_service.update_or_create")
    @transaction.atomic
    def update_or_create(self, data):
        ta_ids = data.pop("ta_ids", []) or []
        gvh_ids = data.pop("gvh_ids", []) or []
        micro_catchment_uuid = data.pop("uuid") if "uuid" in data else None

        self._validate_micro_catchment_relations(data, ta_ids, gvh_ids)

        name = (data.get("name") or "").strip()
        duplicate_name = MicroCatchment.objects.filter(
            name__iexact=name,
            district_id=data["district_id"],
            validity_to__isnull=True,
        )
        if micro_catchment_uuid:
            duplicate_name = duplicate_name.exclude(uuid=micro_catchment_uuid)
        if duplicate_name.exists():
            raise ValidationError(
                f"Micro-catchment name '{name}' already exists."
            )
        data["name"] = name

        if micro_catchment_uuid:
            # Codes identify their original hierarchy and are immutable.
            data.pop("code", None)
            micro_catchment = MicroCatchment.get_queryset(None, self.user).get(
                uuid=micro_catchment_uuid,
                validity_to__isnull=True,
            )
            micro_catchment.save_history()
            [setattr(micro_catchment, key, data[key]) for key in data]
        else:
            # The first selected TA owns the code. Locking it serializes code
            # allocation when multiple requests create under the same TA.
            primary_ta = Location.objects.select_for_update().get(id=ta_ids[0])
            prefix = primary_ta.code
            if not prefix:
                raise ValidationError("The primary Traditional Authority must have a code")

            next_number = 1
            for existing_code in MicroCatchment.objects.filter(
                code__startswith=prefix,
            ).values_list("code", flat=True):
                suffix = existing_code[len(prefix):]
                if suffix.isdigit():
                    next_number = max(next_number, int(suffix) + 1)
            data["code"] = f"{prefix}{next_number:02d}"
            micro_catchment = MicroCatchment.objects.create(**data)

        micro_catchment.save()

        # Sync Traditional Authorities
        if ta_ids is not None:
            from core.utils import TimeUtils
            now = TimeUtils.now()
            # Soft-delete removed ones
            micro_catchment.traditional_authorities.filter(
                validity_to__isnull=True
            ).exclude(location_id__in=ta_ids).update(validity_to=now)
            # Add new ones
            existing_ta_ids = set(
                micro_catchment.traditional_authorities.filter(
                    validity_to__isnull=True
                ).values_list("location_id", flat=True)
            )
            for loc_id in ta_ids:
                if loc_id not in existing_ta_ids:
                    MicroCatchmentTA.objects.create(
                        micro_catchment=micro_catchment,
                        location_id=loc_id,
                        audit_user_id=self.user.id_for_audit,
                        validity_from=now,
                    )

        # Sync GVHs
        if gvh_ids is not None:
            from core.utils import TimeUtils
            now = TimeUtils.now()
            # Soft-delete removed ones
            micro_catchment.gvhs.filter(
                validity_to__isnull=True
            ).exclude(location_id__in=gvh_ids).update(validity_to=now)
            # Add new ones
            existing_gvh_ids = set(
                micro_catchment.gvhs.filter(
                    validity_to__isnull=True
                ).values_list("location_id", flat=True)
            )
            for loc_id in gvh_ids:
                if loc_id not in existing_gvh_ids:
                    MicroCatchmentGVH.objects.create(
                        micro_catchment=micro_catchment,
                        location_id=loc_id,
                        audit_user_id=self.user.id_for_audit,
                        validity_from=now,
                    )

        return micro_catchment


class CatchmentService:
    def __init__(self, user):
        self.user = user

    @staticmethod
    def check_unique_code(code, exclude_uuid=None):
        query = Catchment.objects.filter(
            code__iexact=code,
            validity_to__isnull=True,
        )
        if exclude_uuid:
            query = query.exclude(uuid=exclude_uuid)
        if query.exists():
            raise ValidationError(f"Catchment code {code} already exists")

    @staticmethod
    def validate_districts(district_ids):
        district_ids = set(district_ids or [])
        if not district_ids:
            raise ValidationError("At least one District is required")

        valid_ids = set(
            Location.objects.filter(
                id__in=district_ids,
                type="R",
                validity_to__isnull=True,
            ).values_list("id", flat=True)
        )
        if valid_ids != district_ids:
            raise ValidationError(
                "Every selected District must be an active location of type R"
            )
        return valid_ids

    @transaction.atomic
    @register_service_signal("catchment_service.update_or_create")
    def update_or_create(self, data):
        district_ids = self.validate_districts(data.pop("district_ids", []))
        catchment_uuid = data.pop("uuid", None)
        if not catchment_uuid and not data.get("code"):
            data["code"] = generate_unique_catchment_code(Catchment)
        self.check_unique_code(data["code"], exclude_uuid=catchment_uuid)

        if catchment_uuid:
            catchment = Catchment.objects.select_for_update().get(
                uuid=catchment_uuid,
                validity_to__isnull=True,
            )
            catchment.save_history()
            catchment.code = data["code"]
            catchment.name = data["name"]
            catchment.audit_user_id = self.user.id_for_audit
            catchment.validity_from = data["validity_from"]
            catchment.save()
        else:
            catchment = Catchment.objects.create(**data)

        now = data["validity_from"]
        active_links = catchment.district_links.filter(validity_to__isnull=True)

        active_links.exclude(location_id__in=district_ids).update(
            validity_to=now,
            audit_user_id=self.user.id_for_audit,
        )

        existing_ids = set(
            active_links.filter(location_id__in=district_ids).values_list(
                "location_id", flat=True
            )
        )
        CatchmentDistrict.objects.bulk_create(
            [
                CatchmentDistrict(
                    catchment=catchment,
                    location_id=district_id,
                    audit_user_id=self.user.id_for_audit,
                    validity_from=now,
                )
                for district_id in district_ids - existing_ids
            ]
        )
        return catchment

    @transaction.atomic
    def delete(self, catchment_uuid):
        from core.utils import TimeUtils

        now = TimeUtils.now()
        catchment = Catchment.objects.select_for_update().get(
            uuid=catchment_uuid,
            validity_to__isnull=True,
        )
        catchment.district_links.filter(validity_to__isnull=True).update(
            validity_to=now,
            audit_user_id=self.user.id_for_audit,
        )
        catchment.validity_to = now
        catchment.audit_user_id = self.user.id_for_audit
        catchment.save(update_fields=["validity_to", "audit_user_id"])
