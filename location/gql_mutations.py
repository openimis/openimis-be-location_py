import graphene
from .apps import LocationConfig
from core import assert_string_length
from core.schema import OpenIMISMutation
from .models import (
    Location,
    HealthFacility,
    UserDistrict,
    MicroCatchment,
    Hotspot,
    HotspotVillage,
)
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.utils.translation import gettext as _
from graphene import InputObjectType

import copy

from .services import LocationService, HealthFacilityService, MicroCatchmentService, CatchmentService


class LocationInputType(OpenIMISMutation.Input):
    id = graphene.Int(required=False, read_only=True)
    uuid = graphene.String(required=False)
    code = graphene.String(required=True)
    name = graphene.String(required=True)
    type = graphene.String(required=True)
    male_population = graphene.Int(required=False)
    female_population = graphene.Int(required=False)
    other_population = graphene.Int(required=False)
    families = graphene.Int(required=False)
    parent_uuid = graphene.String(required=False)


def update_or_create_location(data, user):
    if "client_mutation_id" in data:
        data.pop("client_mutation_id")
    if "client_mutation_label" in data:
        data.pop("client_mutation_label")
    return LocationService(user).update_or_create(data)


class CreateOrUpdateLocationMutation(OpenIMISMutation):
    @classmethod
    def do_mutate(cls, perms, user, **data):
        if type(user) is AnonymousUser or not user.id:
            raise ValidationError(_("mutation.authentication_required"))
        if not user.has_perms(perms):
            raise PermissionDenied(_("unauthorized"))

        data["audit_user_id"] = user.id_for_audit
        from core.utils import TimeUtils

        data["validity_from"] = TimeUtils.now()
        update_or_create_location(data, user)
        return None


class CreateLocationMutation(CreateOrUpdateLocationMutation):
    _mutation_module = "location"
    _mutation_class = "CreateLocationMutation"

    class Input(LocationInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):

        if Location.objects.filter(
            code=data["code"], type=data["type"], validity_to=None
        ).exists():
            raise ValidationError("Location with this code already exists.")
        try:
            return cls.do_mutate(
                LocationConfig.gql_mutation_create_locations_perms, user, **data
            )
        except Exception as exc:
            return [
                {
                    "message": _("location.mutation.failed_to_create_location")
                    % {"code": data["code"]},
                    "detail": str(exc),
                }
            ]


class UpdateLocationMutation(CreateOrUpdateLocationMutation):
    _mutation_module = "location"
    _mutation_class = "UpdateLocationMutation"

    class Input(LocationInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            return cls.do_mutate(
                LocationConfig.gql_mutation_edit_locations_perms, user, **data
            )
        except Exception as exc:
            return [
                {
                    "message": _("location.mutation.failed_to_update_location")
                    % {"code": data["code"]},
                    "detail": str(exc),
                }
            ]


def tree_delete(parents, now):
    if parents:
        children = Location.objects.filter(
            parent__in=parents
        )  # .filter(*filter_validity())
        org_children = copy.copy(children)
        children.update(validity_to=now)
        tree_delete(org_children, now)


class DeleteLocationMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "DeleteLocationMutation"

    class Input(OpenIMISMutation.Input):
        uuid = graphene.String()
        code = graphene.String()
        new_parent_uuid = graphene.String()

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if not user.has_perms(LocationConfig.gql_mutation_delete_locations_perms):
                raise PermissionDenied(_("unauthorized"))
            location = Location.objects.get(uuid=data["uuid"])
            np_uuid = data.get("new_parent_uuid", None)
            from core import datetime

            now = datetime.datetime.now()
            if np_uuid:
                new_parent = Location.objects.get(uuid=np_uuid)
                Location.objects.filter(parent=location).filter(
                    *Location.filter_validity()
                ).update(parent=new_parent)
            else:
                tree_delete((location,), now)

            location.validity_to = now
            location.save()
            if location.type == "D":
                cls.__delete_user_districts(location, now)
            return None
        except Exception as exc:
            return [
                {
                    "message": _("location.mutation.failed_to_delete_location")
                    % {"code": data["code"]},
                    "detail": str(exc),
                }
            ]

    @classmethod
    def __delete_user_districts(cls, location: Location, location_delete_date=None):

        if location_delete_date is None:
            from core import datetime

            location_delete_date = datetime.datetime.now()

        UserDistrict.objects.filter(location=location, validity_to__isnull=True).update(
            validity_to=location_delete_date
        )


def tree_reset_types(parent, location, new_level):
    if new_level >= len(LocationConfig.location_types):
        location.parent = parent.parent
        location.type = LocationConfig.location_types[-1]
        return
    location.type = LocationConfig.location_types[new_level]
    for child in location.children.filter(*Location.filter_validity()).all():
        child.save_history()
        tree_reset_types(location, child, new_level + 1)
        child.save()


class MoveLocationMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "MoveLocationMutation"

    class Input(OpenIMISMutation.Input):
        uuid = graphene.String()
        new_parent_uuid = graphene.String()

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if not user.has_perms(LocationConfig.gql_mutation_move_location_perms):
                raise PermissionDenied(_("unauthorized"))
            location = Location.objects.get(uuid=data["uuid"])
            location.save_history()
            level = LocationConfig.location_types.index(location.type)
            np_uuid = data.get("new_parent_uuid", None)
            new_parent = Location.objects.get(uuid=np_uuid) if np_uuid else None
            np_level = (
                LocationConfig.location_types.index(new_parent.type)
                if new_parent
                else -1
            )
            location.parent = new_parent
            if np_level < level - 1 or np_level >= level:
                tree_reset_types(new_parent, location, np_level + 1)
            location.save()
            return None
        except Exception as exc:
            return [
                {
                    "message": _("location.mutation.failed_to_move_location")
                    % {"code": data["code"]},
                    "detail": str(exc),
                }
            ]


class HealthFacilityCodeInputType(graphene.String):

    @staticmethod
    def coerce_string(value):
        assert_string_length(value, 8)
        return value

    serialize = coerce_string
    parse_value = coerce_string

    @staticmethod
    def parse_literal(ast):
        result = graphene.String.parse_literal(ast)
        assert_string_length(result, 8)
        return result


class HealthFacilityCatchmentInputType(InputObjectType):
    id = graphene.Int(required=False, read_only=True)
    location_id = graphene.Int(required=True)
    catchment = graphene.Int(required=False)


class HealthFacilityInputType(OpenIMISMutation.Input):
    id = graphene.Int(required=False, read_only=True)
    uuid = graphene.String(required=False)
    code = HealthFacilityCodeInputType(required=True)
    name = graphene.String(required=True)
    acc_code = graphene.String(required=False)
    legal_form_id = graphene.String(required=True)
    level = graphene.String(required=True)
    sub_level_id = graphene.String(required=False)
    location_id = graphene.Int(required=True)
    address = graphene.String(required=False)
    phone = graphene.String(required=False)
    fax = graphene.String(required=False)
    email = graphene.String(required=False)
    care_type = graphene.String(required=True)
    services_pricelist_id = graphene.Int(required=False)
    items_pricelist_id = graphene.Int(required=False)
    offline = graphene.Boolean(required=False)
    catchments = graphene.List(HealthFacilityCatchmentInputType, required=False)
    contract_start_date = graphene.Date(required=False)
    contract_end_date = graphene.Date(required=False)
    status = graphene.String(required=False)


def update_or_create_health_facility(data, user):
    if "client_mutation_id" in data:
        data.pop("client_mutation_id")
    if "client_mutation_label" in data:
        data.pop("client_mutation_label")
    return HealthFacilityService(user).update_or_create(data)


class CreateHealthFacilityMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "CreateHealthFacilityMutation"

    class Input(HealthFacilityInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if HealthFacilityService.check_unique_code(data.get("code")):
                raise ValidationError(_("mutation.hf_code_duplicated"))
            if type(user) is AnonymousUser or not user.id:
                raise ValidationError(_("mutation.authentication_required"))
            if not user.has_perms(
                LocationConfig.gql_mutation_create_health_facilities_perms
            ):
                raise PermissionDenied(_("unauthorized"))

            data["audit_user_id"] = user.id_for_audit
            from core.utils import TimeUtils

            data["validity_from"] = TimeUtils.now()
            update_or_create_health_facility(data, user)
            return None
        except Exception as exc:
            return [
                {
                    "message": _("location.mutation.failed_to_create_health_facility")
                    % {"code": data["code"]},
                    "detail": str(exc),
                }
            ]


class UpdateHealthFacilityMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "UpdateHealthFacilityMutation"

    class Input(HealthFacilityInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if type(user) is AnonymousUser or not user.id:
                raise ValidationError(_("mutation.authentication_required"))
            if not user.has_perms(
                LocationConfig.gql_mutation_edit_health_facilities_perms
            ):
                raise PermissionDenied(_("unauthorized"))

            incoming_HF_code = data["code"]
            current_HF = HealthFacility.objects.get(uuid=data["uuid"])
            if current_HF.code != incoming_HF_code:
                if HealthFacilityService.check_unique_code(incoming_HF_code):
                    raise ValidationError(_("mutation.hf_code_duplicated"))

            data["audit_user_id"] = user.id_for_audit
            from core.utils import TimeUtils

            data["validity_from"] = TimeUtils.now()
            update_or_create_health_facility(data, user)
            return None
        except Exception as exc:
            return [
                {
                    "message": _("location.mutation.failed_to_update_health_facility")
                    % {"code": data["code"]},
                    "detail": str(exc),
                }
            ]


class DeleteHealthFacilityMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "DeleteHealthFacilityMutation"

    class Input(OpenIMISMutation.Input):
        uuid = graphene.String()
        code = graphene.String()

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if not user.has_perms(
                LocationConfig.gql_mutation_delete_health_facilities_perms
            ):
                raise PermissionDenied(_("unauthorized"))
            hf = HealthFacility.objects.get(uuid=data["uuid"])

            from core import datetime

            now = datetime.datetime.now()
            hf.validity_to = now
            hf.save()
            return None
        except Exception as exc:
            return [
                {
                    "message": _("location.mutation.failed_to_delete_health_facility")
                    % {"code": data["code"]},
                    "detail": str(exc),
                }
            ]


class MicroCatchmentInputType(OpenIMISMutation.Input):
    id = graphene.Int(required=False, read_only=True)
    uuid = graphene.String(required=False)
    code = graphene.String(required=False)
    name = graphene.String(required=True)
    type = graphene.String(required=False)
    district_id = graphene.Int(required=False)
    date_from = graphene.Date(required=False)
    date_to = graphene.Date(required=False)
    ta_ids = graphene.List(graphene.Int, required=False)
    gvh_ids = graphene.List(graphene.Int, required=False)


def update_or_create_micro_catchment(data, user):
    if "client_mutation_id" in data:
        data.pop("client_mutation_id")
    if "client_mutation_label" in data:
        data.pop("client_mutation_label")
    return MicroCatchmentService(user).update_or_create(data)


class CreateMicroCatchmentMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "CreateMicroCatchmentMutation"

    class Input(MicroCatchmentInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if type(user) is AnonymousUser or not user.id:
                raise ValidationError(_("mutation.authentication_required"))
            if not user.has_perms(LocationConfig.gql_mutation_create_locations_perms):
                raise PermissionDenied(_("unauthorized"))

            data["audit_user_id"] = user.id_for_audit
            from core.utils import TimeUtils

            data["validity_from"] = TimeUtils.now()
            update_or_create_micro_catchment(data, user)
            return None
        except Exception as exc:
            return [
                {
                    "message": _("location.mutation.failed_to_create_micro_catchment")
                    % {"code": data.get("code", "unknown")},
                    "detail": str(exc),
                }
            ]


class UpdateMicroCatchmentMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "UpdateMicroCatchmentMutation"

    class Input(MicroCatchmentInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if type(user) is AnonymousUser or not user.id:
                raise ValidationError(_("mutation.authentication_required"))
            if not user.has_perms(LocationConfig.gql_mutation_edit_locations_perms):
                raise PermissionDenied(_("unauthorized"))

            data["audit_user_id"] = user.id_for_audit
            from core.utils import TimeUtils

            data["validity_from"] = TimeUtils.now()
            update_or_create_micro_catchment(data, user)
            return None
        except Exception as exc:
            return [
                {
                    "message": _("location.mutation.failed_to_update_micro_catchment")
                    % {"code": data.get("code", "unknown")},
                    "detail": str(exc),
                }
            ]


class DeleteMicroCatchmentMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "DeleteMicroCatchmentMutation"

    class Input(OpenIMISMutation.Input):
        uuid = graphene.String(required=True)
        code = graphene.String(required=True)

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if not user.has_perms(
                LocationConfig.gql_mutation_delete_micro_catchments_perms
            ):
                raise PermissionDenied(_("unauthorized"))
            mc = MicroCatchment.get_queryset(None, user).get(
                uuid=data["uuid"], validity_to__isnull=True
            )

            from core import datetime

            now = datetime.datetime.now()
            mc.validity_to = now
            mc.audit_user_id = user.id_for_audit
            mc.save(update_fields=["validity_to", "audit_user_id"])
            return None
        except Exception as exc:
            return [
                {
                    "message": _("location.mutation.failed_to_delete_micro_catchment")
                    % {"code": data.get("code", "unknown")},
                    "detail": str(exc),
                }
            ]


class HotspotInputType(OpenIMISMutation.Input):
    id = graphene.Int(required=False, read_only=True)
    uuid = graphene.String(required=False)
    code = graphene.String(required=False)
    name = graphene.String(required=True)
    description = graphene.String(required=False)
    micro_catchment_uuid = graphene.String(required=True)
    village_uuids = graphene.List(graphene.String, required=True)


def get_hotspot_eligible_villages(micro_catchment, hotspot=None):
    """
    Villages (Location type V) that can be attached to a hotspot for the given
    micro-catchment: those whose parent GVH (Location type W under the Malawi
    mapping) belongs to the micro-catchment's GVH set (its `gvhs` links).
    """
    gvh_locations = Location.objects.filter(
        *Location.filter_validity(),
        micro_catchments_gvh__micro_catchment=micro_catchment,
        micro_catchments_gvh__validity_to__isnull=True,
    )
    villages = Location.objects.filter(
        *Location.filter_validity(),
        type="V",
        parent__in=gvh_locations,
    )
    assigned_villages = HotspotVillage.objects.filter(
        validity_to__isnull=True,
        hotspot__validity_to__isnull=True,
    )
    if hotspot:
        assigned_villages = assigned_villages.exclude(hotspot=hotspot)
    return villages.exclude(
        id__in=assigned_villages.values_list("location_id", flat=True)
    )


@transaction.atomic
def update_or_create_hotspot(data, user):
    if "client_mutation_id" in data:
        data.pop("client_mutation_id")
    if "client_mutation_label" in data:
        data.pop("client_mutation_label")

    micro_catchment_uuid = data.pop("micro_catchment_uuid", None)
    village_uuids = list(dict.fromkeys(data.pop("village_uuids", None) or []))

    if not micro_catchment_uuid:
        raise ValidationError(_("location.mutation.hotspot_micro_catchment_required"))
    if not village_uuids:
        raise ValidationError(_("location.mutation.hotspot_villages_required"))

    try:
        micro_catchment = MicroCatchment.get_queryset(None, user).select_for_update().get(
            uuid=micro_catchment_uuid, validity_to__isnull=True
        )
    except MicroCatchment.DoesNotExist:
        raise ValidationError(_("location.mutation.hotspot_micro_catchment_required"))

    current_hotspot = None
    if data.get("uuid"):
        current_hotspot = Hotspot.get_queryset(None, user).filter(
            uuid=data["uuid"], validity_to__isnull=True
        ).first()
        if current_hotspot is None:
            raise PermissionDenied(_("unauthorized"))
    eligible_villages = get_hotspot_eligible_villages(micro_catchment, current_hotspot)
    villages = list(eligible_villages.filter(uuid__in=village_uuids))
    if len(villages) != len(village_uuids):
        raise ValidationError(_("location.mutation.hotspot_invalid_villages"))

    # A village must belong to only one hotspot: reject any village already
    # attached to another active hotspot.
    conflicting = (
        Hotspot.objects.filter(
            validity_to__isnull=True,
            village_links__location__in=villages,
            village_links__validity_to__isnull=True,
        )
        .exclude(uuid=data.get("uuid"))
        .distinct()
    )
    if conflicting.exists():
        raise ValidationError(_("location.mutation.hotspot_village_already_assigned"))

    data["micro_catchment"] = micro_catchment

    if not data.get("uuid"):
        prefix = micro_catchment.code
        next_number = 1
        for existing_code in Hotspot.objects.filter(
            code__startswith=prefix
        ).values_list("code", flat=True):
            suffix = existing_code[len(prefix):]
            if suffix.isdigit():
                next_number = max(next_number, int(suffix) + 1)
        data["code"] = f"{prefix}{next_number:02d}"
        hotspot = Hotspot.objects.create(**data)
    else:
        # Moving or editing a hotspot must not rewrite its identifier.
        data.pop("code", None)
        hotspot = Hotspot.get_queryset(None, user).get(
            uuid=data["uuid"], validity_to__isnull=True
        )
        for field, value in data.items():
            setattr(hotspot, field, value)
        hotspot.save()

    _set_hotspot_villages(hotspot, villages, data.get("audit_user_id"))
    return hotspot


def _set_hotspot_villages(hotspot, villages, audit_user_id):
    from core.utils import TimeUtils

    village_ids = {v.id for v in villages}
    # Drop links that are no longer selected.
    hotspot.village_links.exclude(location_id__in=village_ids).delete()
    existing_ids = set(hotspot.village_links.values_list("location_id", flat=True))
    for village in villages:
        if village.id not in existing_ids:
            HotspotVillage.objects.create(
                hotspot=hotspot,
                location=village,
                audit_user_id=audit_user_id,
                validity_from=TimeUtils.now(),
            )


class CreateHotspotMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "CreateHotspotMutation"

    class Input(HotspotInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if type(user) is AnonymousUser or not user.id:
                raise ValidationError(_("mutation.authentication_required"))
            if not user.has_perms(LocationConfig.gql_mutation_create_locations_perms):
                raise PermissionDenied(_("unauthorized"))

            data["audit_user_id"] = user.id_for_audit
            from core.utils import TimeUtils

            data["validity_from"] = TimeUtils.now()
            update_or_create_hotspot(data, user)
            return None
        except Exception as exc:
            return [
                {
                    "message": _("location.mutation.failed_to_create_hotspot")
                    % {"code": data.get("code", "")},
                    "detail": str(exc),
                }
            ]


class UpdateHotspotMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "UpdateHotspotMutation"

    class Input(HotspotInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if type(user) is AnonymousUser or not user.id:
                raise ValidationError(_("mutation.authentication_required"))
            if not user.has_perms(LocationConfig.gql_mutation_edit_locations_perms):
                raise PermissionDenied(_("unauthorized"))

            data["audit_user_id"] = user.id_for_audit
            from core.utils import TimeUtils

            data["validity_from"] = TimeUtils.now()
            update_or_create_hotspot(data, user)
            return None
        except Exception as exc:
            return [
                {
                    "message": _("location.mutation.failed_to_update_hotspot")
                    % {"code": data.get("code", "")},
                    "detail": str(exc),
                }
            ]


class DeleteHotspotMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "DeleteHotspotMutation"

    class Input(OpenIMISMutation.Input):
        uuid = graphene.String()
        code = graphene.String()

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if not user.has_perms(LocationConfig.gql_mutation_delete_locations_perms):
                raise PermissionDenied(_("unauthorized"))
            hotspot = Hotspot.get_queryset(None, user).get(
                uuid=data["uuid"], validity_to__isnull=True
            )

            from core import datetime

            now = datetime.datetime.now()
            hotspot.validity_to = now
            hotspot.save()
            return None
        except Exception as exc:
            return [
                {
                    "message": _("location.mutation.failed_to_delete_hotspot")
                    % {"code": data.get("code", "")},
                    "detail": str(exc),
                }
            ]


class CatchmentInputType(OpenIMISMutation.Input):
    id = graphene.Int(required=False, read_only=True)
    uuid = graphene.String(required=False)
    code = graphene.String(required=True)
    name = graphene.String(required=True)
    district_ids = graphene.List(graphene.NonNull(graphene.Int), required=True)


class CreateCatchmentInputType(CatchmentInputType):
    code = graphene.String(required=False)


def clean_catchment_mutation_data(data):
    data.pop("client_mutation_id", None)
    data.pop("client_mutation_label", None)
    return data


class CreateCatchmentMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "CreateCatchmentMutation"

    class Input(CreateCatchmentInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if type(user) is AnonymousUser or not user.id:
                raise ValidationError(_("mutation.authentication_required"))
            if not user.has_perms(
                LocationConfig.gql_mutation_create_catchments_perms
            ):
                raise PermissionDenied(_("unauthorized"))

            from core.utils import TimeUtils

            data = clean_catchment_mutation_data(data)
            data["audit_user_id"] = user.id_for_audit
            data["validity_from"] = TimeUtils.now()
            CatchmentService(user).update_or_create(data)
            return None
        except Exception as exc:
            return [{
                "message": _("location.mutation.failed_to_create_catchment")
                % {"code": data.get("code", "unknown")},
                "detail": str(exc),
            }]


class UpdateCatchmentMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "UpdateCatchmentMutation"

    class Input(CatchmentInputType):
        uuid = graphene.String(required=True)

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if type(user) is AnonymousUser or not user.id:
                raise ValidationError(_("mutation.authentication_required"))
            if not user.has_perms(
                LocationConfig.gql_mutation_edit_catchments_perms
            ):
                raise PermissionDenied(_("unauthorized"))

            from core.utils import TimeUtils

            data = clean_catchment_mutation_data(data)
            data["audit_user_id"] = user.id_for_audit
            data["validity_from"] = TimeUtils.now()
            CatchmentService(user).update_or_create(data)
            return None
        except Exception as exc:
            return [{
                "message": _("location.mutation.failed_to_update_catchment")
                % {"code": data.get("code", "unknown")},
                "detail": str(exc),
            }]


class DeleteCatchmentMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "DeleteCatchmentMutation"

    class Input(OpenIMISMutation.Input):
        uuid = graphene.String(required=True)
        code = graphene.String(required=True)

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if type(user) is AnonymousUser or not user.id:
                raise ValidationError(_("mutation.authentication_required"))
            if not user.has_perms(
                LocationConfig.gql_mutation_delete_catchments_perms
            ):
                raise PermissionDenied(_("unauthorized"))
            CatchmentService(user).delete(data["uuid"])
            return None
        except Exception as exc:
            return [{
                "message": _("location.mutation.failed_to_delete_catchment")
                % {"code": data.get("code", "unknown")},
                "detail": str(exc),
            }]
