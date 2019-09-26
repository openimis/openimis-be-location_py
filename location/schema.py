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


def userDistricts(user):
    return UserDistrict.objects                 \
        .select_related('location')             \
        .select_related('location__parent')     \
        .filter(user=user)


class Query(graphene.ObjectType):
    health_facilities = DjangoFilterConnectionField(HealthFacilityGQLType)
    health_facility_full_path = graphene.Field(
        HealthFacilityFullPathGQLType,
        hfId=graphene.Int(required=True)
    )
    user_districts = graphene.List(
        UserDistrictGQLType
    )
    health_facilities_str = DjangoFilterConnectionField(
        HealthFacilityGQLType,
        str=graphene.String(),
        region_id=graphene.Int(),
        district_id=graphene.Int(),
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
