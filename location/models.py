from functools import reduce
import django
from django.core.cache import cache
import uuid

from core import filter_validity
from django.conf import settings
from django.db import models, connection
from django.db.models.expressions import RawSQL
from program import models as program_models
from core import models as core_models
from graphql import ResolveInfo
from .apps import LocationConfig
import logging
from django.db.models import Q

logger = logging.getLogger(__file__)


class LocationManager(models.Manager):
    def parents(self, location_id, loc_type=None):
        parents = Location.objects.raw(
            f"""
            WITH {"" if settings.MSSQL else "RECURSIVE"} CTE_PARENTS AS (
            SELECT 
                "LocationId",
                "LocationType",
                "ParentLocationId"
            FROM
                "tblLocations"
            WHERE "LocationId" = %s
            UNION ALL

            SELECT
                parent."LocationId",
                parent."LocationType",
                parent."ParentLocationId"
            FROM
                "tblLocations" parent
                INNER JOIN CTE_PARENTS leaf
                    ON parent."LocationId" = leaf."ParentLocationId"
            )
            SELECT * FROM CTE_PARENTS;
        """,
            (location_id,),
        )
        return self.get_location_from_ids((parents), loc_type) if loc_type else parents

    def allowed(self, user_id, loc_types=['R', 'D', 'W', 'V'], strict=True, qs=False):
        query = f"""
            WITH {"" if settings.MSSQL else "RECURSIVE"} USER_LOC AS (SELECT l."LocationId", l."ParentLocationId" FROM "tblUsersDistricts" ud JOIN "tblLocations" l ON ud."LocationId" = l."LocationId"  WHERE ud."ValidityTo"  is Null AND "UserID" = %s ),
             CTE_PARENTS AS (
            SELECT
                parent."LocationId",
                parent."LocationType",
                parent."ParentLocationId"

            FROM
                "tblLocations" parent
            WHERE "LocationId" in (SELECT "LocationId" FROM USER_LOC) 
            OR (  parent."LocationId" in  (SELECT "ParentLocationId" FROM USER_LOC) 
                    {'AND (SELECT COUNT(*) FROM USER_LOC  ul WHERE ul."ParentLocationId" = parent."LocationId" ) =  (SELECT COUNT(*) FROM "tblLocations" l WHERE l."ParentLocationId" = parent."LocationId" AND l."ValidityTo" is Null  )' if strict else ""})
            UNION ALL
            SELECT
                child."LocationId",
                child."LocationType",
                child."ParentLocationId"
            FROM
                "tblLocations"  child
                INNER JOIN CTE_PARENTS leaf
                    ON child."ParentLocationId" = leaf."LocationId"
            )
            SELECT DISTINCT "LocationId" FROM CTE_PARENTS WHERE "LocationType" in ('{"','".join(loc_types)}')
        """

        if qs is not None:
            # location_allowed = Location.objects.filter( id__in =[obj.id for obj in Location.objects.raw( query,(user_id,))])
            if settings.MSSQL: # MSSQL don't support WITH in subqueries

                with connection.cursor() as cursor:
                    cursor.execute(query, (user_id,))
                    ids = cursor.fetchall()
                    location_allowed = Location.objects.filter(id__in=[x for x, in ids])
            else:
                location_allowed = Location.objects.filter(id__in=RawSQL(query, (user_id,)))

        else:
            location_allowed = Location.objects.raw(query, (user_id,))

        return location_allowed

    def children(self, location_id, loc_type=None):
        children = Location.objects.raw(
            f"""
                WITH {"" if settings.MSSQL else "RECURSIVE"} CTE_CHILDREN AS (
                SELECT
                    "LocationId",
                    "LocationType",
                    "ParentLocationId",
                    0 as "Level"
                FROM
                    "tblLocations"
                WHERE "LocationId" = %s
                UNION ALL

                SELECT
                    child."LocationId",
                    child."LocationType",
                    child."ParentLocationId",
                    parent."Level" + 1 as "Level" 
                FROM
                    "tblLocations" child
                    INNER JOIN CTE_CHILDREN parent
                        ON child."ParentLocationId" = parent."LocationId"
                )
                SELECT * FROM CTE_CHILDREN;
            """,
            (location_id,),
        )
        return self.get_location_from_ids((children), loc_type) if loc_type else children


    def build_user_location_filter_query(self, user: core_models.InteractiveUser, prefix='location', queryset=None, loc_types=['R', 'D', 'W', 'V']):
        """
        The row filter for `user` on a path pointing at a Location.

        Two things narrow a user: the districts they are assigned to
        (`tblUsersDistricts`, through `allowed`) and, when they hold any, their UBA
        credentials. They are AND'ed: a credential narrows *within* the assigned
        districts, it never grants access outside them. A user holding no location aware
        credential keeps the plain district filter, which is why
        `build_uba_location_filter_query` answers None rather than an empty filter.

        Every caller gets this for free, so a module never restates the UBA rule: the
        path from the model it filters to the linked object is worked out from the
        credential's registry `params`. It also means the rule reaches the REST/FHIR API,
        which calls the same `Model.get_queryset`.
        """
        q_allowed_location = None
        if not isinstance(user, core_models.InteractiveUser):
            logger.warning(f"Access without filter for user {user.id} ")
            if queryset is not None:
                return queryset
            else:
                return Q()
        elif not user.is_imis_admin:
            q_allowed_location = Q((f"{prefix}__in", self.allowed(user.id, loc_types))) | Q((f"{prefix}__isnull", True))
            q_uba = self.build_uba_location_filter_query(user, prefix=prefix, loc_types=loc_types)
            if q_uba is not None:
                q_allowed_location &= q_uba

            if queryset is not None:
                return queryset.filter(q_allowed_location)
            else:
                return q_allowed_location
        else:
            if queryset is not None:
                return queryset
            else:
                return Q()

    # --- UBA aware narrowing ---------------------------------------------------- #

    def build_uba_location_filter_query(self, user, prefix='location', loc_types=('R', 'D', 'W', 'V')):
        """
        The narrowing the UBA credentials of `user` imply on `prefix`.

        One term per location aware credential they actually hold a link on, OR'ed
        together: holding an ENROLMENT link on a village and a CLAIM_ADMIN link on a
        health facility widens what they see rather than intersecting it.

        None when they hold no such link, so that the caller keeps its district filter
        instead of AND'ing with something that matches nothing.
        """
        from core.uba_filters import business_access_object_ids
        from core.uba_link_types import get_location_aware_uba_link_types

        prefix_type = self._prefix_location_type(loc_types)
        q_uba = None
        for link_type in get_location_aware_uba_link_types():
            model_label = link_type.models[0] if link_type.models else None
            object_ids = business_access_object_ids(user, link_type.code, model_label)
            if not object_ids:
                continue
            term = self._uba_link_type_filter_query(link_type, object_ids, prefix, prefix_type)
            if term is None:
                # the credential says nothing about this path, e.g. a health facility
                # credential on a queryset that never reaches a health facility
                continue
            q_uba = term if q_uba is None else q_uba | term
        return q_uba

    def _uba_link_type_filter_query(self, link_type, object_ids, prefix, prefix_type):
        """
        Turn one credential into a filter on `prefix`, using its registry `params`.

        `location_field` means the credential is held on a model hanging off a location,
        so the path to it is the location path minus that last segment
        ('health_facility__location' -> 'health_facility'). `location_type` means it is
        held on a Location, so the path is the location path re-aimed at that type.
        """
        from core.uba_filters import uba_filter_from_object_ids

        params = link_type.params
        location_field = params.get("location_field")
        if location_field:
            if prefix == location_field:
                # the filtered model *is* the one the credential is held on
                return uba_filter_from_object_ids(object_ids)
            suffix = f"__{location_field}"
            if not prefix.endswith(suffix):
                return None
            return uba_filter_from_object_ids(object_ids, prefix=prefix[:-len(suffix)])

        location_type = params.get("location_type")
        configured = list(LocationConfig.location_types) or ['R', 'D', 'W', 'V']
        if not location_type or not prefix_type:
            return None
        if location_type not in configured or prefix_type not in configured:
            logger.warning(
                "UBA link type '%s' declares location_type '%s', not in the configured %s",
                link_type.code, location_type, configured)
            return None
        location_ids = self._expand_location_ids(
            object_ids,
            descendants=bool(params.get("include_descendants")),
            ancestors=bool(params.get("include_ancestors")),
        )
        delta = configured.index(location_type) - configured.index(prefix_type)
        path = self._walk_prefix(prefix, delta)
        if path is not None:
            return uba_filter_from_object_ids(location_ids, prefix=path)
        # the path cannot be walked down to the level the credential is held on: compare
        # what the row does expose, its ancestor at the prefix level. Coarser, but the
        # narrowing still applies instead of being silently dropped
        return uba_filter_from_object_ids(
            self._locations_at_type(location_ids, prefix_type), prefix=prefix)

    @staticmethod
    def _prefix_location_type(loc_types):
        """
        The loc_type the `prefix` points at, taken as the deepest type the caller allows:
        `loc_types=['D']` goes with a path climbing to the district, the default (every
        type) with a plain location field.
        """
        configured = list(LocationConfig.location_types) or ['R', 'D', 'W', 'V']
        allowed = [t for t in configured if t in (loc_types or configured)]
        return allowed[-1] if allowed else None

    @staticmethod
    def _walk_prefix(prefix, delta):
        """
        Re-aim a location path `delta` levels deeper (positive) or shallower (negative).

        A path such as 'location__parent__parent' was built by climbing from the row's own
        village up to its district, so going back down is dropping trailing '__parent'
        segments and going up is adding them. None when there is no '__parent' left to
        drop, the caller then comparing ancestors instead.
        """
        if delta == 0:
            return prefix
        if delta < 0:
            return prefix + '__parent' * (-delta)
        parts = prefix.split('__')
        if len(parts) <= delta or any(part != 'parent' for part in parts[-delta:]):
            return None
        return '__'.join(parts[:-delta])

    @staticmethod
    def _expand_location_ids(location_ids, descendants=False, ancestors=False):
        """
        Widen a set of location ids down and/or up the tree, for the `include_descendants`
        and `include_ancestors` params: a credential granted on a district can then reach
        its villages. Walks level by level, the tree being as deep as `location_types`.
        """
        ids = {int(object_id) for object_id in location_ids}
        if descendants:
            frontier = set(ids)
            while frontier:
                frontier = set(Location.objects.filter(
                    parent_id__in=frontier, *filter_validity()
                ).values_list('id', flat=True)) - ids
                ids |= frontier
        if ancestors:
            frontier = set(ids)
            while frontier:
                frontier = set(Location.objects.filter(
                    id__in=frontier, *filter_validity()
                ).exclude(parent__isnull=True).values_list('parent_id', flat=True)) - ids
                ids |= frontier
        return ids

    @staticmethod
    def _locations_at_type(location_ids, loc_type):
        """
        The locations of `location_ids`, or their nearest ancestor, sitting at `loc_type`.
        Used when a path stops above the level a credential is held on.
        """
        found, seen = set(), {int(object_id) for object_id in location_ids}
        frontier = set(seen)
        while frontier:
            rows = Location.objects.filter(
                id__in=frontier, *filter_validity()
            ).values_list('id', 'type', 'parent_id')
            next_frontier = set()
            for location_id, location_type, parent_id in rows:
                if location_type == loc_type:
                    found.add(location_id)
                elif parent_id and parent_id not in seen:
                    seen.add(parent_id)
                    next_frontier.add(parent_id)
            frontier = next_frontier
        return found



    def get_location_from_ids(self, qsr, loc_type):
        if loc_type:
            return [x for x in list(qsr) if x.type == loc_type]
        return list(qsr)


class Location(core_models.VersionedModel, core_models.ExtendableModel):
    objects = LocationManager()

    id = models.AutoField(db_column='LocationId', primary_key=True)
    uuid = models.CharField(db_column='LocationUUID',
                            max_length=36, default=uuid.uuid4, unique=True)
    code = models.CharField(db_column='LocationCode',
                            max_length=8, blank=True, null=True)
    name = models.CharField(db_column='LocationName',
                            max_length=50, blank=True, null=True)
    parent = models.ForeignKey('Location', models.DO_NOTHING,
                               db_column='ParentLocationId',
                               blank=True, null=True, related_name='children')
    type = models.CharField(db_column='LocationType', max_length=1)
    male_population = models.IntegerField(
        db_column='MalePopulation', blank=True, null=True)
    female_population = models.IntegerField(
        db_column='FemalePopulation', blank=True, null=True)
    other_population = models.IntegerField(
        db_column='OtherPopulation', blank=True, null=True)
    families = models.IntegerField(db_column='Families', blank=True, null=True)

    # rowid = models.TextField(db_column='RowId')
    audit_user_id = models.IntegerField(
        db_column='AuditUserId', blank=True, null=True)

    def __str__(self):
        return self.code + " " + self.name

    @classmethod
    def get_queryset(cls, queryset, user):
        queryset = cls.filter_queryset(queryset)
        # GraphQL calls with an info object while Rest calls with the user itself
        if isinstance(user, ResolveInfo):
            user = user.context.user
        if settings.ROW_SECURITY and user.is_anonymous:
            return queryset.filter(id=-1)

        # OMT-280: if you create a new region and your user has district limitations, you won't find what you
        # just created. So we'll consider that if you were allowed to create it, you are also allowed to retrieve it.
        if settings.ROW_SECURITY \
                and not user.has_perms(LocationConfig.gql_mutation_create_region_locations_perms) \
                and not user.is_superuser:
            if user.is_officer:
                from core.models import Officer
                return Officer.objects \
                    .filter(code=user.username, has_login=True, validity_to__isnull=True) \
                    .get().officer_allowed_locations
            elif user.is_claim_admin:
                from claim.models import ClaimAdmin
                return ClaimAdmin.objects \
                    .filter(code=user.username, has_login=True, validity_to__isnull=True) \
                    .get().officer_allowed_locations
            elif user.is_imis_admin:
                return Location.objects
            else:
                return cls.objects.allowed(user.i_user_id, qs=True)
        return queryset

    @staticmethod
    def build_user_location_filter_query(cls, user: core_models.InteractiveUser, queryset=None):
        return cls.objects.build_user_location_filter_query(user, queryset=queryset)

    class Meta:
        managed = True
        db_table = 'tblLocations'


class HealthFacilityLegalForm(models.Model):
    code = models.CharField(db_column='LegalFormCode', primary_key=True, max_length=1)
    legal_form = models.CharField(db_column='LegalForms', max_length=50)
    sort_order = models.IntegerField(db_column='SortOrder', blank=True, null=True)
    alt_language = models.CharField(db_column='AltLanguage', max_length=50, blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'tblLegalForms'


class HealthFacilitySubLevel(models.Model):
    code = models.CharField(db_column='HFSublevel', primary_key=True, max_length=1)
    health_facility_sub_level = models.CharField(db_column='HFSublevelDesc', max_length=50, blank=True, null=True)
    sort_order = models.IntegerField(db_column='SortOrder', blank=True, null=True)
    alt_language = models.CharField(db_column='AltLanguage', max_length=50, blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'tblHFSublevel'


class HealthFacility(core_models.VersionedModel, core_models.ExtendableModel):
    class HealthFacilityStatus(models.TextChoices):
        ACTIVE = "AC"
        INACTIVE = "IN"
        DELISTED = "DE"
        IDLE = "ID"

    id = models.AutoField(db_column='HfID', primary_key=True)
    uuid = models.CharField(
        db_column='HfUUID', max_length=36, default=uuid.uuid4, unique=True)

    code = models.CharField(db_column='HFCode', max_length=8)
    name = models.CharField(db_column='HFName', max_length=100)
    acc_code = models.CharField(
        db_column='AccCode', max_length=25, blank=True, null=True)
    legal_form = models.ForeignKey(
        HealthFacilityLegalForm, models.DO_NOTHING,
        db_column='LegalForm',
        related_name="health_facilities")
    level = models.CharField(db_column='HFLevel', max_length=1)
    sub_level = models.ForeignKey(
        HealthFacilitySubLevel, models.DO_NOTHING,
        db_column='HFSublevel', blank=True, null=True,
        related_name="health_facilities")
    location = models.ForeignKey(
        Location, models.DO_NOTHING, db_column='LocationId')
    address = models.CharField(
        db_column='HFAddress', max_length=100, blank=True, null=True)
    phone = models.CharField(
        db_column='Phone', max_length=50, blank=True, null=True)
    fax = models.CharField(
        db_column='Fax', max_length=50, blank=True, null=True)
    email = models.CharField(
        db_column='eMail', max_length=50, blank=True, null=True)

    care_type = models.CharField(db_column='HFCareType', max_length=1)

    services_pricelist = models.ForeignKey('medical_pricelist.ServicesPricelist', models.DO_NOTHING,
                                           db_column='PLServiceID', blank=True, null=True,
                                           related_name="health_facilities")
    items_pricelist = models.ForeignKey('medical_pricelist.ItemsPricelist', models.DO_NOTHING, db_column='PLItemID',
                                        blank=True, null=True, related_name="health_facilities")
    offline = models.BooleanField(db_column='OffLine', default=False)
    # row_id = models.BinaryField(db_column='RowID', blank=True, null=True)
    audit_user_id = models.IntegerField(db_column='AuditUserID')
    program = models.ManyToManyField(program_models.Program)
    bank_name = models.CharField(
        db_column='BankName', max_length=255, blank=True, null=True)
    contract_start_date = models.DateField(db_column='ContractStartDate', blank=True, null=True)
    contract_end_date = models.DateField(db_column='ContractEndDate', blank=True, null=True)
    status = models.CharField(max_length=2, choices=HealthFacilityStatus.choices, default=HealthFacilityStatus.ACTIVE)

    def __str__(self):
        return self.code + " " + self.name

    @classmethod
    def get_queryset(cls, queryset, user, **kwargs):
        # GraphQL calls with an info object while Rest calls with the user itself
        if isinstance(user, ResolveInfo):
            user = user.context.user
        if user.has_perms(LocationConfig.gql_query_health_facilities_perms) and queryset is None:
            queryset = HealthFacility.objects
        else:
            queryset = cls.filter_queryset(queryset)
        if settings.ROW_SECURITY and user.is_anonymous:
            return queryset.filter(id=-1)
        if settings.ROW_SECURITY and not user._u.is_imis_admin:
            return LocationManager().build_user_location_filter_query(user._u, queryset=queryset, loc_types=['D'])
        return queryset

    class Meta:
        managed = True
        db_table = 'tblHF'

    LEVEL_HEALTH_CENTER = 'C'
    LEVEL_DISPENSARY = 'D'
    LEVEL_HOSPITAL = 'H'

    CARE_TYPE_IN_PATIENT = 'I'
    CARE_TYPE_OUT_PATIENT = 'O'
    CARE_TYPE_BOTH = 'B'


class HealthFacilityCatchment(models.Model):
    id = models.AutoField(db_column='HFCatchmentId', primary_key=True)
    legacy_id = models.IntegerField(db_column='LegacyId', blank=True, null=True)
    health_facility = models.ForeignKey(
        HealthFacility,
        models.DO_NOTHING,
        db_column='HFID',
        related_name="catchments"
    )
    location = models.ForeignKey(
        Location,
        models.DO_NOTHING,
        db_column='LocationId',
        related_name="catchments"
    )
    catchment = models.IntegerField(db_column='Catchment', blank=True, null=True)
    validity_from = models.DateTimeField(db_column='ValidityFrom', blank=True, null=True)
    validity_to = models.DateTimeField(db_column='ValidityTo', blank=True, null=True)

    audit_user_id = models.IntegerField(db_column='AuditUserId', blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'tblHFCatchment'


class UserDistrict(core_models.VersionedModel):
    id = models.AutoField(db_column="UserDistrictID", primary_key=True)
    user = models.ForeignKey(
        core_models.InteractiveUser, models.DO_NOTHING, db_column="UserID"
    )
    location = models.ForeignKey(Location, models.DO_NOTHING, db_column="LocationId")
    audit_user_id = models.IntegerField(db_column="AuditUserID")

    class Meta:
        managed = True
        db_table = 'tblUsersDistricts'

    @classmethod
    def get_user_districts(cls, user):
        """
        Retrieve the list of UserDistricts for a user, the locations are prefetched on two levels.
        :param user: InteractiveUser to filter on
        :return: UserDistrict *objects*
        """

        if user.is_superuser is True or (hasattr(user, "is_imis_admin") and user.is_imis_admin):
            all_districts = Location.objects.filter(type='D', *filter_validity())
            districts = []
            idx = 0
            for d in all_districts:
                districts.append(
                    UserDistrict(
                        id=idx,
                        user=user,
                        location=d
                    )
                )

            return districts

        elif not isinstance(user, core_models.InteractiveUser):
            if isinstance(user, core_models.TechnicalUser):
                logger.warning(f"get_user_districts called with a technical user `{user.username}`. "
                               "We'll return an empty list, but it should be handled before reaching here.")
            return UserDistrict.objects.none()
        else:
            return (
                UserDistrict.objects
                .filter(location__type='D')
                .filter(*filter_validity())
                .filter(*filter_validity(prefix='location__'))
                .filter(user=user)
                .prefetch_related("location")
                .prefetch_related("location__parent")
                .order_by("location__parent__code")
                .order_by("location__code")
            )

    @classmethod
    def get_user_locations(cls, user):
        """
        Retrieve the list of Locations in the UserDistricts of a certain user.
        :param user: InteractiveUser to filter on
        :return: Location objects to filter on.
        """
        if not core_models.InteractiveUser.is_interactive_user(user):
            return Location.objects.none()
        return Location.objects \
            .filter(*filter_validity()) \
            .filter(parent__parent__userdistrict__user=user.i_user) \
            .order_by("code")

    @classmethod
    def get_queryset(cls, queryset, user):
        if isinstance(user, ResolveInfo):
            user = user.context.user
        if settings.ROW_SECURITY and user.is_anonymous:
            return queryset.filter(id=-1)
        if settings.ROW_SECURITY:
            pass
        return queryset


class OfficerVillage(core_models.VersionedModel):
    id = models.AutoField(db_column="OfficerVillageId", primary_key=True)
    officer = models.ForeignKey(
        core_models.Officer,
        models.CASCADE,
        db_column="OfficerId",
        related_name="officer_villages",
    )
    location = models.ForeignKey(
        Location,
        models.CASCADE,
        db_column="LocationId",
        related_name="officer_villages",
    )
    audit_user_id = models.IntegerField(db_column="AuditUserID")

    class Meta:
        managed = True
        db_table = 'tblOfficerVillages'

    @classmethod
    def get_queryset(cls, queryset, user):
        if isinstance(user, ResolveInfo):
            user = user.context.user
        if settings.ROW_SECURITY and user.is_anonymous:
            return queryset.filter(id=-1)
        if settings.ROW_SECURITY:
            pass
        return queryset


class LocationMutation(core_models.UUIDModel):
    location = models.ForeignKey(Location, models.DO_NOTHING,
                                 related_name='mutations')
    mutation = models.ForeignKey(
        core_models.MutationLog, models.DO_NOTHING, related_name='locations')

    class Meta:
        managed = True
        db_table = "location_LocationMutation"


class HealthFacilityMutation(core_models.UUIDModel):
    health_facility = models.ForeignKey(HealthFacility, models.DO_NOTHING,
                                        related_name='mutations')
    mutation = models.ForeignKey(
        core_models.MutationLog, models.DO_NOTHING, related_name='health_facilities')

    class Meta:
        managed = True
        db_table = "location_HealthFacilityMutation"
