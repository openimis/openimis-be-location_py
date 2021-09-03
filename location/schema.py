import graphene_django_optimizer as gql_optimizer
from core.schema import OrderedDjangoFilterConnectionField
from core.schema import signal_mutation_module_validate
from django.db.models import Q
from django.utils.translation import gettext as _
from graphene_django.filter import DjangoFilterConnectionField

from .gql_mutations import *
from .gql_queries import *
from .models import *


class Query(graphene.ObjectType):
    health_facilities = OrderedDjangoFilterConnectionField(
        HealthFacilityGQLType,
        showHistory=graphene.Boolean(),
        orderBy=graphene.List(of_type=graphene.String)
    )
    locations = DjangoFilterConnectionField(LocationGQLType)
    locations_str = DjangoFilterConnectionField(
        LocationGQLType,
        str=graphene.String(),
    )
    user_districts = graphene.List(
        UserDistrictGQLType
    )
    health_facilities_str = DjangoFilterConnectionField(
        HealthFacilityGQLType,
        str=graphene.String(),
        region_uuid=graphene.String(),
        district_uuid=graphene.String(),
    )

    def resolve_health_facilities(self, info, **kwargs):
        show_history = kwargs.get('showHistory', False) and info.context.user.has_perms(
            LocationConfig.gql_query_health_facilities_perms)
        # OMT-281 allow anyone to query, limited by the get_queryset
        # if not info.context.user.has_perms(LocationConfig.gql_query_health_facilities_perms):
        if info.context.user.is_anonymous:
            raise PermissionDenied(_("unauthorized"))
        query = HealthFacility.get_queryset(None, info.context.user, **kwargs)
        if not show_history:
            query = HealthFacility.filter_queryset(query)
        return gql_optimizer.query(query.all(), info)

    def resolve_locations(self, info, **kwargs):
        # OMT-281 allow querying to anyone, with limitations in the get_queryset
        # if not info.context.user.has_perms(LocationConfig.gql_query_locations_perms):
        if info.context.user.is_anonymous:
            raise PermissionDenied(_("unauthorized"))

    def resolve_locations_str(self, info, **kwargs):
        if not info.context.user.has_perms(LocationConfig.gql_query_locations_perms):
            raise PermissionDenied(_("unauthorized"))
        filters = [*filter_validity(**kwargs)]
        str = kwargs.get('str')
        if str is not None:
            filters += [Q(code__icontains=str) | Q(name__icontains=str)]
        return Location.objects.filter(*filters)

    def resolve_health_facilities_str(self, info, **kwargs):
        if not info.context.user.has_perms(LocationConfig.gql_query_locations_perms):
            raise PermissionDenied(_("unauthorized"))
        filters = [*filter_validity(**kwargs)]
        str = kwargs.get('str')
        if str is not None:
            filters += [Q(code__icontains=str) | Q(name__icontains=str)]
        district_uuid = kwargs.get('district_uuid')
        if district_uuid is not None:
            filters += [Q(location__uuid=district_uuid)]
        region_uuid = kwargs.get('region_uuid')
        if region_uuid is not None:
            filters += [Q(location__parent__uuid=region_uuid)]
        dist = UserDistrict.get_user_districts(info.context.user._u)
        filters += [Q(location__id__in=[l.location_id for l in dist])]
        return HealthFacility.objects.filter(*filters)

    def resolve_user_districts(self, info, **kwargs):
        if info.context.user.is_anonymous:
            raise NotImplementedError(
                'Anonymous Users are not registered for districts')
        if not isinstance(info.context.user._u, core_models.InteractiveUser):
            raise NotImplementedError(
                'Only Interactive Users are registered for districts')
        return [UserDistrictGQLType(d) for d in UserDistrict.get_user_districts(info.context.user._u)]


class Mutation(graphene.ObjectType):
    create_location = CreateLocationMutation.Field()
    update_location = UpdateLocationMutation.Field()
    delete_location = DeleteLocationMutation.Field()
    move_location = MoveLocationMutation.Field()
    create_health_facility = CreateHealthFacilityMutation.Field()
    update_health_facility = UpdateHealthFacilityMutation.Field()
    delete_health_facility = DeleteHealthFacilityMutation.Field()


def on_location_mutation(sender, **kwargs):
    uuid = kwargs['data'].get('uuid', None)
    if not uuid:
        return []
    if "Location" in str(sender._mutation_class):
        impacted_location = Location.objects.get(uuid=uuid)
        LocationMutation.objects.create(
            location=impacted_location, mutation_id=kwargs['mutation_log_id'])
    if "HealthFacility" in str(sender._mutation_class):
        impacted_health_facility = HealthFacility.objects.get(uuid=uuid)
        HealthFacilityMutation.objects.create(
            health_facility=impacted_health_facility, mutation_id=kwargs['mutation_log_id'])
    return []


def bind_signals():
    signal_mutation_module_validate["location"].connect(on_location_mutation)
