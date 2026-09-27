from core.gql.custom_lookup import NotEqual
import graphene
import base64
from graphene_django import DjangoObjectType
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext as _
from core import prefix_filterset, ExtendedConnection
from location.apps import LocationConfig
from location.models import (
    HealthFacilityLegalForm,
    Location,
    HealthFacilitySubLevel,
    HealthFacilityCatchment,
    HealthFacility,
    LocationManager,
    UserDistrict,
    OfficerVillage,
    extend_allowed_locations,
)
from core.models import InteractiveUser
from django.conf import settings
from django.db.models import Field
from core.gql import ScopedQuerysetMixin


# Marker for "this user is not location-restricted at all"
UNRESTRICTED_LOCATIONS = object()


def allowed_location_ids(info):
    """
    The locations the user may read: the ones they are assigned, their ancestors
    and their descendants. Memoized on the request, the set is the same for
    every node of a response.
    """
    cached = getattr(info.context, "_allowed_location_ids", None)
    if cached is not None:
        return cached

    user = info.context.user
    interactive_user = getattr(user, "_u", user)
    if (
        LocationConfig.no_location_check
        or not settings.ROW_SECURITY
        or user.is_superuser
        or not isinstance(interactive_user, InteractiveUser)
    ):
        # Same convention as LocationManager.build_user_location_filter_query:
        # a user who is not an InteractiveUser is not location-restricted.
        allowed = UNRESTRICTED_LOCATIONS
    else:
        allowed = set(
            extend_allowed_locations(
                LocationManager().get_allowed_ids(interactive_user), strict=False
            )
        )
    try:
        info.context._allowed_location_ids = allowed
    except AttributeError:
        pass
    return allowed


def _root_field_name(info):
    """Name of the root field this resolution started from, alias resolved."""
    if not info.path:
        return None
    response_name = info.path[0]
    for selection in info.operation.selection_set.selections:
        name = getattr(selection, "name", None)
        if name is None:
            continue
        alias = getattr(selection, "alias", None)
        if (alias.value if alias else name.value) == response_name:
            return name.value
    return response_name


def check_location_readable(info, location_id):
    """
    Row security for a single location reached by walking a foreign key.

    Location.get_queryset only bounds the querysets behind the root queries. A
    field returning one location - a parent, a health facility location - is
    resolved straight off the model, so without this any node of the tree could
    be read from any node the user legitimately holds. Reading these needs no
    right, as a user is entitled to their own locations, but it stays inside
    their own branch: what they are assigned, above it and below it.
    """
    if not info.context.user.is_authenticated:
        raise PermissionDenied(_("unauthorized"))
    if location_id is None:
        return
    if _root_field_name(info) == "locationsAll":
        # locationsAll deliberately hands the whole tree to any authenticated
        # user - see Query.resolve_locations_all and the bypass in
        # LocationGQLType.get_queryset - so row security on a walk started there
        # would protect nothing while breaking the callers that rely on it.
        return
    allowed = allowed_location_ids(info)
    if allowed is not UNRESTRICTED_LOCATIONS and location_id not in allowed:
        raise PermissionDenied(_("unauthorized"))


class LocationGQLType(DjangoObjectType):
    client_mutation_id = graphene.String()
    Field.register_lookup(NotEqual)

    def resolve_parent(self, info):
        check_location_readable(info, self.parent_id)
        if "location_loader" in info.context.dataloaders and self.parent_id:
            return info.context.dataloaders["location_loader"].load(self.parent_id)
        return self.parent

    class Meta:
        model = Location
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "id": ["exact"],
            "uuid": ["exact", "in"],
            "code": ["exact", "istartswith", "icontains", "iexact", "ne"],
            "name": ["exact", "istartswith", "icontains", "iexact", "ne"],
            "type": ["exact"],
            "parent__uuid": ["exact", "in"],  # can't import itself!
            "parent__parent__uuid": ["exact", "in"],  # can't import itself!
            # can't import itself!
            "parent__parent__parent__uuid": ["exact", "in"],
            "parent__id": ["exact", "in"],  # can't import itself!
        }

    def resolve_client_mutation_id(self, info):
        if not info.context.user.is_authenticated:
            raise PermissionDenied(_("unauthorized"))
        location_mutation = (
            self.mutations.select_related("mutation").filter(mutation__status=0).first()
        )
        return (
            location_mutation.mutation.client_mutation_id if location_mutation else None
        )

    @classmethod
    def get_queryset(cls, queryset, info):
        if info.field_name == "locationsAll":
            return queryset
        else:
            return Location.get_queryset(queryset, info.context.user)


class HealthFacilityLegalFormGQLType(DjangoObjectType):
    class Meta:
        model = HealthFacilityLegalForm


class HealthFacilitySubLevelGQLType(DjangoObjectType):
    class Meta:
        model = HealthFacilitySubLevel


class HealthFacilityCatchmentGQLType(ScopedQuerysetMixin, DjangoObjectType):
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
            "phone": ["exact", "istartswith", "icontains", "iexact"],
            "status": ["exact"],
            **prefix_filterset("location__", LocationGQLType._meta.filter_fields),
        }
        connection_class = ExtendedConnection

    def resolve_location(self, info):
        check_location_readable(info, self.location_id)
        if "location_loader" in info.context.dataloaders:
            return info.context.dataloaders["location_loader"].load(self.location_id)

    def resolve_catchments(self, info):
        if not info.context.user.has_perms(
            LocationConfig.gql_query_health_facilities_perms
        ):
            raise PermissionDenied(_("unauthorized"))
        return self.catchments.filter(validity_to__isnull=True)

    def resolve_client_mutation_id(self, info):
        if not info.context.user.has_perms(
            LocationConfig.gql_query_health_facilities_perms
        ):
            raise PermissionDenied(_("unauthorized"))
        health_facility_mutation = (
            self.mutations.select_related("mutation").filter(mutation__status=0).first()
        )
        return (
            health_facility_mutation.mutation.client_mutation_id
            if health_facility_mutation
            else None
        )


class UserRegionGQLType(graphene.ObjectType):
    id = graphene.String()
    uuid = graphene.String()
    code = graphene.String()
    name = graphene.String()

    def __init__(self, region):
        if region:
            self.id = str(
                base64.b64encode(f"LocationGQLType:{region.id}".encode()), "utf-8"
            )
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
        if district:
            self.id = str(
                base64.b64encode(f"LocationGQLType:{district.location_id}".encode()),
                "utf-8",
            )
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
        return OfficerVillage.get_queryset(queryset, info).filter(
            validity_to__isnull=True
        )
