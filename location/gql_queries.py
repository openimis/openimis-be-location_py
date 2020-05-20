import graphene
import base64
from graphene_django import DjangoObjectType
from core import prefix_filterset, filter_validity, ExtendedConnection
from location.models import HealthFacilityLegalForm, Location, HealthFacilitySubLevel, HealthFacilityCatchment, \
    HealthFacility


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


class HealthFacilityLegalFormGQLType(DjangoObjectType):
    class Meta:
        model = HealthFacilityLegalForm


class HealthFacilitySubLevelGQLType(DjangoObjectType):
    class Meta:
        model = HealthFacilitySubLevel


class HealthFacilityCatchmentGQLType(DjangoObjectType):
    class Meta:
        model = HealthFacilityCatchment


class HealthFacilityGQLType(DjangoObjectType):
    class Meta:
        model = HealthFacility
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "id": ["exact"],
            "uuid": ["exact"],
            "code": ["exact", "istartswith", "icontains", "iexact"],
            "fax": ["exact", "istartswith", "icontains", "iexact"],
            "email": ["exact", "istartswith", "icontains", "iexact"],
            "name": ["exact", "istartswith", "icontains", "iexact"],
            "level": ["exact"],
            "care_type": ["exact"],
            "legal_form__code": ["exact"],
            **prefix_filterset("location__", LocationGQLType._meta.filter_fields)
        }
        connection_class = ExtendedConnection

    def resolve_catchments(self, info):
        return self.catchments.filter(validity_to__isnull=True)


class UserRegionGQLType(graphene.ObjectType):
    id = graphene.String()
    uuid = graphene.String()
    code = graphene.String()
    name = graphene.String()

    def __init__(self, region):
        self.id = str(base64.b64encode(f"LocationGQLType:{region.id}".encode()), 'utf-8')
        self.uuid = region.uuid
        self.code = region.code
        self.name = region.name


class UserDistrictGQLType(graphene.ObjectType):
    id = graphene.String()
    uuid = graphene.String()
    code = graphene.String()
    name = graphene.String()
    parent = graphene.Field(UserRegionGQLType)

    def __init__(self, district):
        self.id = str(base64.b64encode(f"LocationGQLType:{district.location_id}".encode()), 'utf-8')
        self.uuid = district.location.uuid
        self.code = district.location.code
        self.name = district.location.name
        self.parent = UserRegionGQLType(district.location.parent)
