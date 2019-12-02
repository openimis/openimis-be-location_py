from copy import copy
import graphene
from .apps import LocationConfig
from core import prefix_filterset, ExtendedConnection, filter_validity, Q, assert_string_length
from core.schema import TinyInt, SmallInt, OpenIMISMutation, OrderedDjangoFilterConnectionField
from .models import *
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils.translation import gettext as _


class LocationCodeInputType(graphene.String):

    @staticmethod
    def coerce_string(value):
        assert_string_length(res, 8)
        return res

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


class CreateLocationMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "CreateLocationMutation"

    class Input(LocationInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if type(user) is AnonymousUser or not user.id:
                raise ValidationError(
                    _("mutation.authentication_required"))
            if not user.has_perms(LocationConfig.gql_mutation_create_locations_perms):
                raise PermissionDenied(_("unauthorized"))

            data['audit_user_id'] = user.id_for_audit
            from core.utils import TimeUtils
            data['validity_from'] = TimeUtils.now()
            update_or_create_location(data, user)
            return None
        except Exception as exc:
            return [{
                'message': _("location.mutation.failed_to_create_location") % {'code': data['code']},
                'detail': str(exc)}]


class UpdateLocationMutation(OpenIMISMutation):
    _mutation_module = "location"
    _mutation_class = "UpdateLocationMutation"

    class Input(LocationInputType):
        pass

    @classmethod
    def async_mutate(cls, user, **data):
        try:
            if type(user) is AnonymousUser or not user.id:
                raise ValidationError(
                    _("mutation.authentication_required"))
            if not user.has_perms(LocationConfig.gql_mutation_edit_locations_perms):
                raise PermissionDenied(_("unauthorized"))

            data['audit_user_id'] = user.id_for_audit
            from core.utils import TimeUtils
            data['validity_from'] = TimeUtils.now()
            update_or_create_location(data, user)
            return None
        except Exception as exc:
            return [{
                'message': _("location.mutation.failed_to_create_location") % {'code': data['code']},
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
            if not user.has_perms(LocationConfig.gql_mutation_delete_location_perms):
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
                'message': _("location.mutation.failed_to_delete") % {'code': data['code']},
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
                'message': _("location.mutation.failed_to_delete") % {'code': data['code']},
                'detail': str(exc)}]
