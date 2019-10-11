from django.db.models import Q
import graphene
from graphene_django import DjangoObjectType
from django.core.exceptions import PermissionDenied
from graphene_django.filter import DjangoFilterConnectionField
from .models import HealthFacility, Location, UserDistrict
from .services import HealthFacilityFullPathRequest, HealthFacilityFullPathService
from .apps import LocationConfig
from core import prefix_filterset, filter_validity
from core import models as core_models
from django.utils.translation import gettext as _


class LocationGQLType(DjangoObjectType):
    class Meta:
        model = Location
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "uuid": ["exact"],
            "code": ["exact", "istartswith", "icontains", "iexact"],
            "name": ["exact", "istartswith", "icontains", "iexact"],
            "type": ["exact"],
            "parent__uuid": ["exact"],  # can't import itself!
        }


class HealthFacilityGQLType(DjangoObjectType):
    class Meta:
        model = HealthFacility
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "uuid": ["exact"],
            "code": ["exact", "istartswith", "icontains", "iexact"],
            "name": ["exact", "istartswith", "icontains", "iexact"],
            "level": ["exact"],
            **prefix_filterset("location__", LocationGQLType._meta.filter_fields)
        }


class UserDistrictGQLType(graphene.ObjectType):
    id = graphene.Int()
    uuid = graphene.String()
    code = graphene.String()
    name = graphene.String()
    region_id = graphene.Int()
    region_uuid = graphene.String()
    region_code = graphene.String()
    region_name = graphene.String()

    def __init__(self, district):
        self.id = district.location.id
        self.uuid = district.location.uuid
        self.code = district.location.code
        self.name = district.location.name
        self.region_id = district.location.parent.id
        self.region_uuid = district.location.parent.uuid
        self.region_code = district.location.parent.code
        self.region_name = district.location.parent.name


def userDistricts(user):
    if not isinstance(user, core_models.InteractiveUser):
        return []
    return UserDistrict.objects                 \
        .select_related('location')             \
        .select_related('location__parent')     \
        .filter(user=user)                      \
        .exclude(location__parent__isnull=True)


class Query(graphene.ObjectType):
    health_facilities = DjangoFilterConnectionField(HealthFacilityGQLType)
    locations = DjangoFilterConnectionField(LocationGQLType)
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
        if not info.context.user.has_perms(LocationConfig.gql_query_health_facilities_perms):
            raise PermissionDenied(_("unauthorized"))
        pass

    def resolve_locations(self, info, **kwargs):
        if not info.context.user.has_perms(LocationConfig.gql_query_locations_perms):
            raise PermissionDenied(_("unauthorized"))
        pass

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
        dist = userDistricts(info.context.user._u)
        filters += [Q(location__id__in=[l.location.id for l in dist])]
        return HealthFacility.objects.filter(*filters)

    def resolve_user_districts(self, info, **kwargs):
        if info.context.user.is_anonymous:
            raise NotImplementedError(
                'Anonymous Users are not registered for districts')
        if not isinstance(info.context.user._u, core_models.InteractiveUser):
            raise NotImplementedError(
                'Only Interactive Users are registered for districts')
        return [UserDistrictGQLType(d) for d in userDistricts(info.context.user._u)]
