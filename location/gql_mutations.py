import graphene
from .apps import LocationConfig
from core import assert_string_length, filter_validity
from core.schema import OpenIMISMutation
from .models import Location, HealthFacilityCatchment, HealthFacility
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils.translation import gettext as _
from graphene import InputObjectType


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


def reset_location_before_update(location):
    location.male_population = None
    location.female_population = None
    location.other_population = None
    location.families = None


def update_or_create_location(data, user):
    if "client_mutation_id" in data:
        data.pop('client_mutation_id')
    if "client_mutation_label" in data:
        data.pop('client_mutation_label')
    location_uuid = data.pop('uuid') if 'uuid' in data else None
    parent_uuid = data.pop('parent_uuid') if 'parent_uuid' in data else None
    # update_or_create(uuid=location_uuid, ...)
    # doesn't work because of explicit attempt to set null to uuid!
    if location_uuid:
        location = Location.objects.get(uuid=location_uuid)
        reset_location_before_update(location)
        [setattr(location, key, data[key]) for key in data]
    else:
        location = Location.objects.create(**data)
    if parent_uuid:
        location.parent = Location.objects.get(uuid=parent_uuid)
    location.save()


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
            return cls.do_mutate(LocationConfig.gql_mutation_edit_locations_perms, user, **data)
        except Exception as exc:
            return [{
                'message': _("location.mutation.failed_to_update_location") % {'code': data['code']},
                'detail': str(exc)}]


def tree_delete(parents, now):
    if parents:
        children = Location.objects \
            .filter(parent__in=parents) \
            .filter(*filter_validity())
        children.update(validity_to=now)
        tree_delete(children.all(), now)


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
            return None
        except Exception as exc:
            return [{
                'message': _("location.mutation.failed_to_delete_location") % {'code': data['code']},
                'detail': str(exc)}]


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
    legal_form_id = graphene.String(required=False)
    level = graphene.String(required=False)
    sub_level_id = graphene.String(required=False)
    location_id = graphene.Int(required=False)
    address = graphene.String(required=False)
    phone = graphene.String(required=False)
    fax = graphene.String(required=False)
    email = graphene.String(required=False)
    care_type = graphene.String(required=False)
    services_pricelist_id = graphene.Int(required=False)
    items_pricelist_id = graphene.Int(required=False)
    offline = graphene.Boolean(required=False)
    catchments = graphene.List(HealthFacilityCatchmentInputType, required=False)


def reset_health_facility_before_update(hf):
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


def process_catchments(user, data_catchments, prev_hf_id,
                       hf_id, catchments):
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
                catchment['audit_user_id'] = user.id_for_audit
                catchment['health_facility_id'] = hf_id
                HealthFacilityCatchment.objects.create(**catchment)
        else:
            catchment['validity_from'] = TimeUtils.now()
            catchment['audit_user_id'] = user.id_for_audit
            catchment['health_facility_id'] = hf_id
            HealthFacilityCatchment.objects.create(**catchment)

    if prev_catchments:
        catchments.filter(id__in=prev_catchments).update(
            health_facility_id=prev_hf_id,
            validity_to=TimeUtils.now())


def update_or_create_health_facility(data, user):
    if "client_mutation_id" in data:
        data.pop('client_mutation_id')
    if "client_mutation_label" in data:
        data.pop('client_mutation_label')
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
        reset_health_facility_before_update(hf)
        [setattr(hf, key, data[key]) for key in data]
    else:
        # UI don't foresee a field for offline > set via API (and mobile 'world' ?
        data['offline'] = False
        hf = HealthFacility.objects.create(**data)
    process_catchments(user, catchments, prev_hf_id, hf.id, hf.catchments)
    hf.save()
    return hf


class CreateHealthFacilityMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "CreateHealthFacilityMutation"

    class Input(HealthFacilityInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        try:
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
