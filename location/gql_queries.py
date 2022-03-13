import graphene
import base64
from graphene_django import DjangoObjectType
from core import prefix_filterset, filter_validity, ExtendedConnection
from location.models import HealthFacilityLegalForm, Location, HealthFacilitySubLevel, HealthFacilityCatchment, \
    HealthFacility, UserDistrict, OfficerVillage


class LocationGQLType(DjangoObjectType):
    client_mutation_id = graphene.String()

    def resolve_parent(self, info):
        if "location_loader" in info.context.dataloaders and self.parent_id:
            return info.context.dataloaders["location_loader"].load(self.parent_id)
        return self.parent

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

    def resolve_client_mutation_id(self, info):
        location_mutation = self.mutations.select_related(
            'mutation').filter(mutation__status=0).first()
        return location_mutation.mutation.client_mutation_id if location_mutation else None

    @classmethod
    def get_queryset(cls, queryset, info):
        return Location.get_queryset(queryset, info.context.user)


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
    client_mutation_id = graphene.String()

    class Meta:
        model = HealthFacility
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "id": ["exact"],
            "uuid": ["exact"],
            "code": ["exact", "istartswith", "icontains", "iexact"],
            "fax": ["exact", "istartswith", "icontains", "iexact", "isnull"],
            "email": ["exact", "istartswith", "icontains", "iexact", "isnull"],
            "name": ["exact", "istartswith", "icontains", "iexact"],
            "level": ["exact"],
            "sub_level": ["exact", "isnull"],
            "care_type": ["exact"],
            "legal_form__code": ["exact"],
            **prefix_filterset("location__", LocationGQLType._meta.filter_fields)
        }
        connection_class = ExtendedConnection

    def resolve_location(self, info):
        if "location_loader" in info.context.dataloaders:
            return info.context.dataloaders["location_loader"].load(self.location_id)

    def resolve_catchments(self, info):
        return self.catchments.filter(validity_to__isnull=True)

    def resolve_client_mutation_id(self, info):
        health_facility_mutation = self.mutations.select_related(
            'mutation').filter(mutation__status=0).first()
        return health_facility_mutation.mutation.client_mutation_id if health_facility_mutation else None


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


class UserDistrictType(DjangoObjectType):
    class Meta:
        model = UserDistrict
        filter_fields = {
            "id": ["exact"],
            "user": ["exact"],
            "location": ["exact"],
        }
        connection_class = ExtendedConnection

    @classmethod
    def get_queryset(cls, queryset, info):
        return UserDistrict.get_queryset(queryset, info)


class OfficerVillageGQLType(DjangoObjectType):
    class Meta:
        model = OfficerVillage

    @classmethod
    def get_queryset(cls, queryset, info):
        return OfficerVillage.get_queryset(queryset, info).filter(validity_to__isnull=True)
