import graphene
from graphene_django import DjangoObjectType
from .models import HealthFacility, Location, UserDistrict
from core import prefix_filterset, filter_validity
from core import models as core_models


class LocationGQLType(DjangoObjectType):
    class Meta:
        model = Location
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "id": ["exact"],
            "uuid": ["exact"],
            "code": ["exact", "istartswith", "icontains", "iexact"],
            "name": ["exact", "istartswith", "icontains", "iexact"],
            "type": ["exact"],
            "parent__uuid": ["exact"],  # can't import itself!
            "parent__id": ["exact"],  # can't import itself!
        }

    @classmethod
    def get_queryset(cls, queryset, info):
        queryset = queryset.filter(*filter_validity())
        return queryset


class HealthFacilityGQLType(DjangoObjectType):
    class Meta:
        model = HealthFacility
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "id": ["exact"],
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
    return UserDistrict.objects \
        .select_related('location') \
        .select_related('location__parent') \
        .filter(user=user) \
        .filter(*filter_validity()) \
        .exclude(location__parent__isnull=True)
