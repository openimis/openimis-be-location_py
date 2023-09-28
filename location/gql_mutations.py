import graphene
from .apps import LocationConfig
from core import assert_string_length, filter_validity
from core.schema import OpenIMISMutation
from .models import Location, HealthFacility, UserDistrict
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils.translation import gettext as _
from graphene import InputObjectType
from django.core.cache import cache

import copy

from .services import LocationService, HealthFacilityService


class LocationCodeInputType(graphene.String):
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


class LocationInputType(OpenIMISMutation.Input):
    id = graphene.Int(required=False, read_only=True)
    uuid = graphene.String(required=False)
    code = LocationCodeInputType(required=True)
    name = graphene.String(required=True)
    type = graphene.String(required=True)
    male_population = graphene.Int(required=False)
    female_population = graphene.Int(required=False)
    other_population = graphene.Int(required=False)
    families = graphene.Int(required=False)
    parent_uuid = graphene.String(required=False)


def update_or_create_location(data, user):
    if "client_mutation_id" in data:
        data.pop('client_mutation_id')
    if "client_mutation_label" in data:
        data.pop('client_mutation_label')
    return LocationService(user).update_or_create(data)


class CreateOrUpdateLocationMutation(OpenIMISMutation):
    @classmethod
    def do_mutate(cls, perms, user, **data):
        if type(user) is AnonymousUser or not user.id:
            raise ValidationError(
                _("mutation.authentication_required"))
        if not user.has_perms(perms):
            raise PermissionDenied(_("unauthorized"))

        data['audit_user_id'] = user.id_for_audit
        from core.utils import TimeUtils
        data['validity_from'] = TimeUtils.now()
        update_or_create_location(data, user)
        return None


class CreateLocationMutation(CreateOrUpdateLocationMutation):
    _mutation_module = "location"
    _mutation_class = "CreateLocationMutation"

    class Input(LocationInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):

        if Location.objects.filter(code=data['code'], type=data['type'], validity_to=None).exists():
            raise ValidationError("Location with this code already exists.")
        try:
            return cls.do_mutate(LocationConfig.gql_mutation_create_locations_perms, user, **data)
        except Exception as exc:
            return [{
                'message': _("location.mutation.failed_to_create_location") % {'code': data['code']},
                'detail': str(exc)}]


class UpdateLocationMutation(CreateOrUpdateLocationMutation):
    _mutation_module = "location"
    _mutation_class = "UpdateLocationMutation"

    class Input(LocationInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            return cls.do_mutate(
                LocationConfig.gql_mutation_edit_locations_perms,
                user,
                **data
            )
        except Exception as exc:
            return [{
                'message': _("location.mutation.failed_to_update_location") % {'code': data['code']},
                'detail': str(exc)}]


def tree_delete(parents, now):
    if parents:
        children = Location.objects \
            .filter(parent__in=parents) \
            # .filter(*filter_validity())
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
            location = Location.objects.get(uuid=data['uuid'])
            np_uuid = data.get('new_parent_uuid', None)
            from core import datetime
            now = datetime.datetime.now()
            if np_uuid:
                new_parent = Location.objects.get(uuid=np_uuid)
                Location.objects \
                    .filter(parent=location) \
                    .filter(*filter_validity()) \
                    .update(parent=new_parent)
            else:
                tree_delete((location,), now)

            location.validity_to = now
            location.save()
            if location.type == 'D':
                cls.__delete_user_districts(location, now)
            return None
        except Exception as exc:
            return [{
                'message': _("location.mutation.failed_to_delete_location") % {'code': data['code']},
                'detail': str(exc)}]

    @classmethod
    def __delete_user_districts(cls, location: Location, location_delete_date=None):
        
        if location_delete_date is None:
            from core import datetime
            location_delete_date = datetime.datetime.now()

        UserDistrict.objects\
            .filter(location=location, validity_to__isnull=True)\
            .update(validity_to=location_delete_date)
        cache.delete('user_disctrict_'+user.id)



def tree_reset_types(parent, location, new_level):
    if new_level >= len(LocationConfig.location_types):
        location.parent = parent.parent
        location.type = LocationConfig.location_types[-1]
        return
    location.type = LocationConfig.location_types[new_level]
    for child in location.children.filter(*filter_validity()).all():
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
            location = Location.objects.get(uuid=data['uuid'])
            location.save_history()
            level = LocationConfig.location_types.index(location.type)
            np_uuid = data.get('new_parent_uuid', None)
            new_parent = Location.objects.get(uuid=np_uuid) if np_uuid else None
            np_level = LocationConfig.location_types.index(new_parent.type) if new_parent else -1
            location.parent = new_parent
            if np_level < level - 1 or np_level >= level:
                tree_reset_types(new_parent, location, np_level + 1)
            location.save()
            return None
        except Exception as exc:
            return [{
                'message': _("location.mutation.failed_to_move_location") % {'code': data['code']},
                'detail': str(exc)}]


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
        data.pop('client_mutation_id')
    if "client_mutation_label" in data:
        data.pop('client_mutation_label')
    return HealthFacilityService(user).update_or_create(data)


class CreateHealthFacilityMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "CreateHealthFacilityMutation"

    class Input(HealthFacilityInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if HealthFacilityService.check_unique_code(data.get('code')):
                raise ValidationError(
                    _("mutation.hf_code_duplicated"))
            if type(user) is AnonymousUser or not user.id:
                raise ValidationError(
                    _("mutation.authentication_required"))
            if not user.has_perms(LocationConfig.gql_mutation_create_health_facilities_perms):
                raise PermissionDenied(_("unauthorized"))

            data['audit_user_id'] = user.id_for_audit
            from core.utils import TimeUtils
            data['validity_from'] = TimeUtils.now()
            update_or_create_health_facility(data, user)
            return None
        except Exception as exc:
            return [{
                'message': _("location.mutation.failed_to_create_health_facility") % {'code': data['code']},
                'detail': str(exc)}]


class UpdateHealthFacilityMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "UpdateHealthFacilityMutation"

    class Input(HealthFacilityInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if type(user) is AnonymousUser or not user.id:
                raise ValidationError(
                    _("mutation.authentication_required"))
            if not user.has_perms(LocationConfig.gql_mutation_edit_health_facilities_perms):
                raise PermissionDenied(_("unauthorized"))

            incoming_HF_code = data['code']
            current_HF = HealthFacility.objects.get(uuid=data['uuid'])
            if current_HF.code != incoming_HF_code:
                if HealthFacilityService.check_unique_code(incoming_HF_code):
                    raise ValidationError(
                        _("mutation.hf_code_duplicated"))

            data['audit_user_id'] = user.id_for_audit
            from core.utils import TimeUtils
            data['validity_from'] = TimeUtils.now()
            update_or_create_health_facility(data, user)
            return None
        except Exception as exc:
            return [{
                'message': _("location.mutation.failed_to_update_health_facility") % {'code': data['code']},
                'detail': str(exc)}]


class DeleteHealthFacilityMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "DeleteHealthFacilityMutation"

    class Input(OpenIMISMutation.Input):
        uuid = graphene.String()
        code = graphene.String()

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if not user.has_perms(LocationConfig.gql_mutation_delete_health_facilities_perms):
                raise PermissionDenied(_("unauthorized"))
            hf = HealthFacility.objects.get(uuid=data['uuid'])

            from core import datetime
            now = datetime.datetime.now()
            hf.validity_to = now
            hf.save()
            return None
        except Exception as exc:
            return [{
                'message': _("location.mutation.failed_to_delete_health_facility") % {'code': data['code']},
                'detail': str(exc)}]
