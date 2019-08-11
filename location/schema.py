from django.db.models import Q
import graphene
from graphene_django import DjangoObjectType
from graphene_django.filter import DjangoFilterConnectionField
from .models import HealthFacility, Location
from .services import HealthFacilityFullPathRequest, HealthFacilityFullPathService
from core import prefix_filterset, filter_validity


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


class HealthFacilityFullPathGQLType(graphene.ObjectType):
    hf_id = graphene.Int()
    hf_code = graphene.String()
    hf_name = graphene.String()
    hf_level = graphene.String()
    district_id = graphene.Int()
    district_code = graphene.String()
    district_name = graphene.String()
    region_id = graphene.Int()
    region_code = graphene.String()
    region_name = graphene.String()


class Query(graphene.ObjectType):
    health_facility_full_path = graphene.Field(
        HealthFacilityFullPathGQLType,
        hfId=graphene.Int(required=True)
    )

    health_facilities_str = DjangoFilterConnectionField(
        HealthFacilityGQLType,
        str=graphene.String()
    )

    locations_str = DjangoFilterConnectionField(
        LocationGQLType,
        tpe=graphene.String(),
        str=graphene.String(),
    )

    def resolve_health_facility_full_path(self, info, **kwargs):
        req = HealthFacilityFullPathRequest(
            hf_id=kwargs.get('hfId')
        )
        resp = HealthFacilityFullPathService(
            user=info.context.user).request(req)
        if resp is None:
            return None
        return HealthFacilityFullPathGQLType(
            hf_id=resp.hf_id,
            hf_code=resp.hf_code,
            hf_name=resp.hf_name,
            hf_level=resp.hf_level,
            district_id=resp.district_id,
            district_code=resp.district_code,
            district_name=resp.district_name,
            region_id=resp.region_id,
            region_code=resp.region_code,
            region_name=resp.region_name
        )

    def resolve_health_facilities_str(self, info, **kwargs):
        filters = [*filter_validity(**kwargs)]
        str = kwargs.get('str')
        if str is not None:
            filters.extend([Q(code__icontains=str) | Q(name__icontains=str)])
        return HealthFacility.objects.filter(*filters)

    def resolve_locations_str(self, info, **kwargs):
        filters = [*filter_validity(**kwargs)]
        str = kwargs.get('str')
        if str is not None:
            filters.extend([Q(code__icontains=str) | Q(name__icontains=str)])
        tpe = kwargs.get('tpe')
        if tpe is not None:
            filters.extend([Q(type__exact=tpe)])
        return Location.objects.filter(*filters)
