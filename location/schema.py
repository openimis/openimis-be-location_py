import graphene
from graphene_django import DjangoObjectType
from .models import HealthFacility, Location
from .services import HealthFacilityFullPathRequest, HealthFacilityFullPathService


class HealthFacilityGQLType(DjangoObjectType):
    class Meta:
        model = HealthFacility


class LocationGQLType(DjangoObjectType):
    class Meta:
        model = Location


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
