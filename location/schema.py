import graphene_django_optimizer as gql_optimizer

from core.models import Officer
from core.schema import OrderedDjangoFilterConnectionField
from core.schema import signal_mutation_module_validate
from django.utils.translation import gettext as _
from graphene_django.filter import DjangoFilterConnectionField
from .gql_mutations import *
from .gql_queries import *
from .models import *
from .services import LocationService


def _uba_scope_args():
    """
    The arguments scoping a location query to the locations a UBA credential puts the
    user on - an enrolment officer's pickers showing their villages only. Opt in: a query
    without `uba_link_type` keeps the district scope, whatever credentials the user holds.
    """
    return {
        "uba_link_type": graphene.String(
            required=False,
            description="Restrict to the locations the current user holds a link on under "
                        "that credential (e.g. 'ENROLMENT'), 'ALL' for any location aware one. "
                        "Ignored for a user holding no such link."),
        "uba_include_ancestors": graphene.Boolean(
            required=False,
            description="With uba_link_type, also return the ancestors of the linked "
                        "locations so the tree can be navigated down to them. Defaults to "
                        "the location module setting uba_picker_include_ancestors (true)."),
    }


def _uba_scoped_location_ids(user, kwargs):
    """The location ids the UBA arguments restrict to, None when they restrict nothing."""
    link_type = kwargs.get("uba_link_type")
    if not link_type or not isinstance(user._u, core_models.InteractiveUser):
        return None
    include_ancestors = kwargs.get("uba_include_ancestors")
    if include_ancestors is None:
        include_ancestors = LocationConfig.uba_picker_include_ancestors
    return LocationManager().uba_location_ids(
        user._u, link_type, include_ancestors=include_ancestors)


class Query(graphene.ObjectType):
    health_facilities = OrderedDjangoFilterConnectionField(
        HealthFacilityGQLType,
        showHistory=graphene.Boolean(),
        orderBy=graphene.List(of_type=graphene.String)
    )
    locations = OrderedDjangoFilterConnectionField(
        LocationGQLType,
        orderBy=graphene.List(of_type=graphene.String),
        **_uba_scope_args(),
    )
    locations_all = OrderedDjangoFilterConnectionField(
        LocationGQLType,
        orderBy=graphene.List(of_type=graphene.String)
    )
    locations_str = DjangoFilterConnectionField(
        LocationGQLType,
        str=graphene.String(),
        **_uba_scope_args(),
    )
    user_districts = graphene.List(
        UserDistrictGQLType,
        **_uba_scope_args(),
    )
    officer_locations = graphene.List(LocationGQLType,
                                      officer_code=graphene.String(required=True),
                                      location_type=graphene.String(required=False),
                                      description="Returns list of locations assigned to a given enrolment officer.")
    health_facilities_str = DjangoFilterConnectionField(
        HealthFacilityGQLType,
        str=graphene.String(),
        region_uuid=graphene.String(),
        district_uuid=graphene.String(),
        districts_uuids=graphene.List(of_type=graphene.String),
        ignore_location=graphene.Boolean()
    )
    validate_location_code = graphene.Field(
        graphene.Boolean,
        location_code=graphene.String(required=True),
        description="Checks that the specified location code is unique."
    )
    validate_health_facility_code = graphene.Field(
        graphene.Boolean,
        health_facility_code=graphene.String(required=True),
        description="Checks that the specified health facility code is unique."
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

        query = LocationManager().build_user_location_filter_query(info.context.user._u, queryset = query)

        return gql_optimizer.query(query.all(), info)

    def resolve_validate_location_code(self, info, **kwargs):
        if not info.context.user.has_perms(LocationConfig.gql_query_locations_perms):
            raise PermissionDenied(_("unauthorized"))
        errors = LocationService.check_unique_code(code=kwargs['location_code'])
        return False if errors else True

    def resolve_validate_health_facility_code(self, info, **kwargs):
        if not info.context.user.has_perms(LocationConfig.gql_query_health_facilities_perms):
            raise PermissionDenied(_("unauthorized"))
        errors = HealthFacilityService.check_unique_code(code=kwargs['health_facility_code'])
        return False if errors else True

    def resolve_locations(self, info, **kwargs):
        # OMT-281 allow querying to anyone, with limitations in the get_queryset
        # if not info.context.user.has_perms(LocationConfig.gql_query_locations_perms):
        if info.context.user.is_anonymous:
            raise PermissionDenied(_("unauthorized"))
        uba_location_ids = _uba_scoped_location_ids(info.context.user, kwargs)
        if uba_location_ids is not None:
            # Location.get_queryset still applies the district scope on top of it
            return Location.objects.filter(id__in=uba_location_ids)
        return None

    def resolve_locations_all(self, info, **kwargs):
        if info.context.user.is_anonymous:
            raise PermissionDenied(_("unauthorized"))
        return Location.objects.filter(*filter_validity()).all()

    def resolve_locations_str(self, info, **kwargs):
        if info.context.user.is_anonymous:
            raise PermissionDenied(_("unauthorized"))

        queryset = Location.get_queryset(None, info.context.user)
        filters = [*filter_validity(**kwargs)]

        str = kwargs.get('str')
        if str is not None:
            filters += [Q(code__icontains=str) | Q(name__icontains=str)]
        uba_location_ids = _uba_scoped_location_ids(info.context.user, kwargs)
        if uba_location_ids is not None:
            filters += [Q(id__in=uba_location_ids)]

        return queryset.filter(*filters)

    def resolve_health_facilities_str(self, info, **kwargs):
        if not info.context.user.is_authenticated:
            raise PermissionDenied(_("unauthorized"))
        filters = [*filter_validity(**kwargs)]
        search = kwargs.get('str')
        district_uuid = kwargs.get('district_uuid')
        district_uuids = kwargs.get('districts_uuids')
        region_uuid = kwargs.get('region_uuid')
        if search is not None:
            filters += [Q(code__icontains=search) | Q(name__icontains=search)]
        if district_uuid is not None:
            filters += [Q(location__uuid=district_uuid)]
        if district_uuids is not None:
            if None not in district_uuids:
                filters += [Q(location__uuid__in=district_uuids)]
        if region_uuid is not None:
            filters += [Q(location__parent__uuid=region_uuid)]

        if (kwargs.get('ignore_location') == False or kwargs.get('ignore_location') is None):

          if settings.ROW_SECURITY and not info.context.user._u.is_imis_admin:
              filters += [LocationManager().build_user_location_filter_query(info.context.user._u, loc_types= ['D'])]
        return HealthFacility.objects.filter(*filters)

    def resolve_user_districts(self, info, **kwargs):
        if info.context.user.is_anonymous:
            raise NotImplementedError(
                'Anonymous Users are not registered for districts')
        if not isinstance(info.context.user._u, core_models.InteractiveUser):
            raise NotImplementedError(
                'Only Interactive Users are registered for districts')
        districts = UserDistrict.get_user_districts(info.context.user._u)
        uba_location_ids = _uba_scoped_location_ids(info.context.user, kwargs)
        if uba_location_ids is not None:
            # the districts of a user are few: fetch the allowed ones once
            allowed = set(uba_location_ids.filter(type='D').values_list('id', flat=True))
            districts = [d for d in districts if d.location_id in allowed]
        return [UserDistrictGQLType(d) for d in districts]

    def resolve_officer_locations(self, info, **kwargs):
        if not info.context.user.has_perms(LocationConfig.gql_query_locations_perms):
            raise PermissionDenied(_("unauthorized"))
        current_officer = Officer.objects.get(code=kwargs['officer_code'], validity_to__isnull=True)
        if 'location_type' in kwargs:
            return current_officer.officer_allowed_locations.filter(type=kwargs['location_type'])
        return current_officer.officer_allowed_locations


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
