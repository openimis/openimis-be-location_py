import graphene
from graphene_django import DjangoObjectType
from .models import HealthFacility


class HealthFacilityType(DjangoObjectType):
    class Meta:
        model = HealthFacility
        exclude_fields = ('row_id',)


class Query(graphene.ObjectType):
    all_health_facilities = graphene.List(HealthFacilityType)

    def resolve_all_health_facilities(self, info, **kwargs):
        return HealthFacility.objects.all()
