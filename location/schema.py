from django.db.models import Q
import graphene
from graphene_django import DjangoObjectType
from graphene_django.filter import DjangoFilterConnectionField
from .models import HealthFacility, Location, UserDistrict
from .services import HealthFacilityFullPathRequest, HealthFacilityFullPathService
from core import prefix_filterset, filter_validity
from core import models as core_models


class LocationGQLType(DjangoObjectType):
    class Meta:
        model = Location
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "id": ["exact"],
            "code": ["exact", "istartswith", "icontains", "iexact"],
            "name": ["exact", "istartswith", "icontains", "iexact"],
            "type": ["exact"],
            "parent__id": ["exact"],  # can't import itself!
        }


class HealthFacilityGQLType(DjangoObjectType):
    class Meta:
        model = HealthFacility
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "id": ["exact"],
            "code": ["exact", "istartswith", "icontains", "iexact"],
            "name": ["exact", "istartswith", "icontains", "iexact"],
            "level": ["exact"],
            **prefix_filterset("location__", LocationGQLType._meta.filter_fields)
        }


class UserDistrictGQLType(graphene.ObjectType):
    id = graphene.Int()
    code = graphene.String()
    name = graphene.String()
    region_id = graphene.Int()
    region_code = graphene.String()
    region_name = graphene.String()

    def __init__(self, district):
        self.id = district.location.id
        self.code = district.location.code
        self.name = district.location.name
        self.region_id = district.location.parent.id
        self.region_code = district.location.parent.code
        self.region_name = district.location.parent.name

def userDistricts(user):
    return UserDistrict.objects                 \
        .select_related('location')             \
        .select_related('location__parent')     \
        .filter(user=user)


class Query(graphene.ObjectType):
    health_facilities = DjangoFilterConnectionField(HealthFacilityGQLType)
    user_districts = graphene.List(
        UserDistrictGQLType
    )
    health_facilities_str = DjangoFilterConnectionField(
        HealthFacilityGQLType,
        str=graphene.String(),
        region_id=graphene.Int(),
        district_id=graphene.Int(),
    )

    def resolve_user_districts(self, info, **kwargs):
        if info.context.user.is_anonymous:
            raise NotImplementedError(
                'Anonymous Users are not registered for districts')
        if not isinstance(info.context.user._u, core_models.InteractiveUser):
            raise NotImplementedError(
                'Only Interactive Users are registered for districts')
        return [UserDistrictGQLType(d) for d in userDistricts(info.context.user._u)]

    def resolve_health_facilities_str(self, info, **kwargs):
        filters = [*filter_validity(**kwargs)]
        str = kwargs.get('str')
        if str is not None:
            filters += [Q(code__icontains=str) | Q(name__icontains=str)]
        district_id = kwargs.get('district_id')
        if district_id is not None:
            filters += [Q(location__id=district_id)]
        region_id = kwargs.get('region_id')
        if region_id is not None:
            filters += [Q(location__parent__id=region_id)]
        dist = userDistricts(info.context.user._u)
        filters += [Q(location__id__in=[l.location.id for l in dist])]
        return HealthFacility.objects.filter(*filters)
