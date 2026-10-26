from django.core.cache import caches
from django_redis.cache import RedisCache
import uuid
from core.models import CachedManager
from django.conf import settings
from django.db import models, transaction
from django.dispatch import receiver
from django.db.models.signals import post_save, post_delete

from core import models as core_models
from core.cache_control import cache_delete, cache_get, cache_memo_forget, cache_set
from graphql import ResolveInfo
from .apps import LocationConfig
import logging
from django.db.models import Count, F, Q

logger = logging.getLogger(__file__)
LOCATION_CACHE = "location"
cache = caches[LOCATION_CACHE]


# Reads and writes go through core.cache_control: entries expire (CACHE_OBJECT_TTL),
# and a process-local cache is not trusted while mutations run in a worker.
def _cache_get(key):
    return cache_get(key, alias=LOCATION_CACHE)


def _cache_set(key, value):
    return cache_set(key, value, alias=LOCATION_CACHE)


USER_LOCATION_CACHE_KEYS = ("user_locations_{}", "user_districts_{}")


def free_cache_for_user(user_id="*"):
    """Drop the cached location and district sets for one user, or for everyone.

    ``user_id="*"`` means everyone, which is what a location change needs: it
    shifts the expanded set of every user whose branch the location falls
    under, not only of users whose own assignment changed.

    Globbing is a django-redis extension, so the wildcard needs
    ``delete_pattern`` on Redis and a full ``clear()`` on any other backend.
    ``cache.delete()`` is literal: passing "*" to it deleted a key *named*
    "user_locations_*" and invalidated nothing, which -- since these entries
    are written with ``timeout=None`` -- left them stale for the life of the
    Redis instance. The condition below used to be inverted, so the one backend
    that can glob was the one that did not.
    """
    if user_id == "*":
        cache_memo_forget([key.format("") for key in USER_LOCATION_CACHE_KEYS], alias=LOCATION_CACHE)
        if isinstance(cache, RedisCache):
            for key in USER_LOCATION_CACHE_KEYS:
                cache.delete_pattern(key.format("*"))
        else:
            cache.clear()
        return

    cache_memo_forget([key.format(user_id) for key in USER_LOCATION_CACHE_KEYS], alias=LOCATION_CACHE)
    for key in USER_LOCATION_CACHE_KEYS:
        cache.delete(key.format(user_id))


def free_cache_for_user_now_and_on_commit(user_id="*"):
    """``free_cache_for_user``, once now and once more when the write commits.

    The signals that call this run inside the writer's transaction. A request
    reading committed data in between rebuilds an entry without the change;
    dropping the entries again once the change is visible clears that copy.
    """
    free_cache_for_user(user_id)
    transaction.on_commit(lambda: free_cache_for_user(user_id))


@receiver(post_save, sender=core_models.InteractiveUser)
@receiver(post_delete, sender=core_models.InteractiveUser)
def free_cache_post_user_save(sender, instance, **kwargs):
    free_cache_for_user_now_and_on_commit(instance.id)


class LocationManager(CachedManager):
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
            WHERE "LocationId" in ( %s )
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
            (
                (
                    ",".join(map(str, location_id))
                    if isinstance(location_id, list)
                    else location_id
                ),
            ),
        )
        return self.get_location_from_ids((parents), loc_type) if loc_type else parents

    def allowed(self, user_id, loc_types=["R", "D", "W", "V"], strict=True, qs=False):
        """The locations ``user_id`` may see, as a queryset.

        The assigned districts, everything beneath them, and their direct
        parents. ``strict`` decides which parents count: ``False`` takes every
        direct parent, ``True`` only a parent whose valid children are *all*
        assigned.

        No recursion is needed for any of it. The hierarchy is fixed depth
        (``LocationConfig.location_types``), so the descendants are a bounded
        set of ``parent`` hops, and the strict rule is an aggregate over one
        level of children.

        This replaces a recursive CTE that MSSQL could not host in a subquery,
        which is why that backend used to execute it on its own and send every
        allowed id back as a literal ``IN`` list - a list that grows with the
        hierarchy, against a server that caps a statement at 2100 parameters
        (OP-3197). Both backends now get the same composable queryset.

        ``qs`` is accepted for compatibility and ignored: it used to pick
        between a queryset and ``Location.objects.raw()``, and every caller
        works with a queryset.
        """
        granted = UserDistrict.objects.filter(
            user_id=user_id, *UserDistrict.filter_validity()
        ).values("location_id")

        # The assigned locations themselves.
        condition = Q(id__in=granted)

        # Everything beneath them, one `parent` hop per level. Only valid rows
        # descend, which is what the recursion did; the assigned locations and
        # their parents were never validity-checked, so they still are not.
        hops = "parent"
        for _ in range(len(LocationConfig.location_types) - 1):
            condition |= Q(**{f"{hops}_id__in": granted}) & Q(
                validity_to__isnull=True
            )
            hops += "__parent"

        # Their direct parents - no recursion upward, as before.
        parents = Location.objects.filter(id__in=granted)
        if strict:
            parents = parents.values("parent_id")
            parents = (
                Location.objects.filter(id__in=parents)
                .annotate(
                    _granted_children=Count(
                        "children", filter=Q(children__id__in=granted), distinct=True
                    ),
                    _valid_children=Count(
                        "children",
                        filter=Q(children__validity_to__isnull=True),
                        distinct=True,
                    ),
                )
                .filter(_granted_children=F("_valid_children"))
                .values("id")
            )
        else:
            parents = parents.values("parent_id")
        condition |= Q(id__in=parents)

        return Location.objects.filter(condition, type__in=loc_types)

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
                WHERE "LocationId" in ( %s )
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
            (
                (
                    ",".join(map(str, location_id))
                    if isinstance(location_id, list)
                    else location_id
                ),
            ),
        )
        return (
            self.get_location_from_ids((children), loc_type) if loc_type else children
        )

    def build_user_location_filter_query(
        self,
        user: core_models.InteractiveUser,
        prefix="location",
        queryset=None,
        loc_types=["R", "D", "W", "V"],
    ):
        q_allowed_location = None
        if not isinstance(user, core_models.InteractiveUser):
            logger.warning(f"Access without filter for user {user.id} ")
            if queryset is not None:
                return queryset
            else:
                return Q()
        elif not user.is_superuser:
            q_allowed_location = Q(
                (
                    f"{prefix}__in",
                    extend_allowed_locations(
                        self.get_allowed_ids(user), True, loc_types
                    ),
                )
            ) | Q((f"{prefix}__isnull", True))
            if queryset is not None:
                return queryset.filter(q_allowed_location)
            else:
                return q_allowed_location
        else:
            if queryset is not None:
                return queryset
            else:
                return Q()

    # How many `parent` hops lead from a village to a location of each type.
    VILLAGE_HOPS = {"V": "", "W": "__parent", "D": "__parent__parent", "R": "__parent__parent__parent"}

    def build_user_village_filter_query(self, user: core_models.InteractiveUser, prefix="location"):
        """``Q`` for rows whose *village* is reached by ``prefix``, at the level the user is granted.

        ``build_user_location_filter_query`` compares one fixed level (say the
        district, ``location__parent__parent``) with the user's locations
        extended to that level. That fails for a user granted *below* it: an
        enrolment officer's locations are villages, which never extend to a
        district, so the officer matched nothing. Here each granted location is
        matched at its own level instead - a village against the village, a
        district two hops up - which also keeps every ``IN`` list as short as
        the grant itself.

        TODO(UBA): the granted locations come from ``get_allowed_ids`` (user
        districts, officer villages, or the claim administrator's facility). With
        user business access they come from the user's accesses of a given link
        type (ENROLMENT for families and insurees); only that lookup changes, the
        per-level matching below stays.
        """
        if not isinstance(user, core_models.InteractiveUser):
            logger.warning(f"Access without filter for user {user.id} ")
            return Q()
        if user.is_superuser:
            return Q()
        allowed = self.get_allowed_ids(user)
        cache_location_if_not_cached()
        location_types = _cache_get("location_types") or {}
        condition = Q((f"{prefix}__isnull", True))
        for loc_type, hops in self.VILLAGE_HOPS.items():
            ids = [pk for pk in allowed if pk in location_types.get(loc_type, ())]
            if ids:
                condition |= Q((f"{prefix}{hops}__in", ids))
        return condition

    def get_location_from_ids(self, qsr, loc_type):
        if loc_type:
            return [x for x in list(qsr) if x.type == loc_type]
        return list(qsr)

    def get_allowed_ids(self, user, strict=True):
        if hasattr(user, '_u'):
            user = user._u
        cache_name = f"user_locations_{user.id}"
        allowed = _cache_get(cache_name)
        if not allowed:
            # for CA
            if user.is_claim_admin and user.health_facility:
                allowed = [user.health_facility.location_id]
            elif user.is_officer:
                allowed = list(
                    OfficerVillage.objects.filter(
                        officer=core_models.Officer.objects.filter(
                            code=user.login_name, *core_models.Officer.filter_validity()
                        ).first(),
                        *OfficerVillage.filter_validity(),
                    ).values_list("location_id", flat=True)
                )
            else:
                allowed = [
                    d.location_id for d in UserDistrict(user).get_user_districts(user)
                ]
            _cache_set(cache_name, allowed)
        return allowed

    def is_allowed(self, user, locations_id, strict=True):
        if LocationConfig.no_location_check or user.is_superuser or not settings.ROW_SECURITY:
            return True
        allowed = self.get_allowed_ids(user, strict)
        return all(
            [loc in extend_allowed_locations(allowed, strict) for loc in locations_id]
        )


def cache_location_graph(location_id=None):
    """Cache the location graph as a dictionary of edges."""
    locations = Location.objects.filter(
        Q(parent__isnull=False) | Q(type='R'),
        *Location.filter_validity(),
    )
    graph = {}
    location_types = {}
    for location in locations:
        parent_id = location.parent_id if location.parent_id else "root"
        if parent_id not in graph:
            graph[parent_id] = set()
        graph[parent_id].add(location.id)
        if location.type not in location_types:
            location_types[location.type] = set()
        location_types[location.type].add(location.id)

    _cache_set("location_graph", graph)
    _cache_set("location_types", location_types)


def cache_location_if_not_cached():
    if _cache_get("location_types") is None:
        cache_location_graph()


def all_location_ids():
    """Every valid location id, from the same cache the graph is built into.

    Lets a caller recognise a set of allowed locations that leaves nothing out,
    which is not a restriction at all.
    """
    cache_location_if_not_cached()
    location_types = _cache_get("location_types") or {}
    if not location_types:
        return set()
    return set().union(*location_types.values())


def extend_allowed_locations(location_pks, strict=True, loc_types=None):
    """
    Get underlying locations for given location PKs.
    If strict is False, also include parents.
    """
    if not isinstance(location_pks, list):
        logger.error(
            f"extend_allowed_locations is expecting a list but received {location_pks}"
        )
    cache_location_if_not_cached()
    graph = _cache_get("location_graph")
    result_pks = set()
    to_visit = set(location_pks)
    visited = set()

    while to_visit:
        current = to_visit.pop()
        visited.add(current)
        result_pks.add(current)
        if current in graph:
            children = graph[current] - visited
            to_visit.update(children)

    if not strict:
        to_visit = set(location_pks)
        parents = set()
        while to_visit:
            current = to_visit.pop()
            for parent, children in graph.items():
                if current in children and parent != "root":
                    parents.add(parent)
                    to_visit.add(parent)
        result_pks.update(parents)
    if result_pks and loc_types:
        location_types = _cache_get("location_types")
        location_types_search = set()
        for t in loc_types:
            if t in location_types:
                location_types_search.update(location_types[t])
        result_pks = [r for r in result_pks if r in location_types_search]

    # Fetch Location objects for the result PKs
    return result_pks


# Function to update the cache when Location objects are modified
def update_location_cache(sender, instance, location_id=None, **kwargs):
    cache_location_graph(location_id)


class Location(core_models.VersionedModel, core_models.ExtendableModel):
    objects = LocationManager()

    id = models.AutoField(db_column="LocationId", primary_key=True)
    uuid = models.CharField(
        db_column="LocationUUID", max_length=36, default=uuid.uuid4, unique=True
    )
    code = models.CharField(
        db_column="LocationCode", max_length=50, blank=True, null=True
    )
    name = models.CharField(
        db_column="LocationName", max_length=50, blank=True, null=True
    )
    parent = models.ForeignKey(
        "Location",
        models.DO_NOTHING,
        db_column="ParentLocationId",
        blank=True,
        null=True,
        related_name="children",
    )
    type = models.CharField(db_column="LocationType", max_length=1)
    male_population = models.IntegerField(
        db_column="MalePopulation", blank=True, null=True
    )
    female_population = models.IntegerField(
        db_column="FemalePopulation", blank=True, null=True
    )
    other_population = models.IntegerField(
        db_column="OtherPopulation", blank=True, null=True
    )
    families = models.IntegerField(db_column="Families", blank=True, null=True)

    # rowid = models.TextField(db_column='RowId')
    audit_user_id = models.IntegerField(db_column="AuditUserId", blank=True, null=True)

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
        if (
            settings.ROW_SECURITY and not user.has_perms(
                LocationConfig.gql_mutation_create_region_locations_perms
            ) and not user.is_superuser
        ):
            if user.is_officer:
                from core.models import Officer

                return (
                    Officer.objects.filter(
                        code=user.username, has_login=True, validity_to__isnull=True
                    )
                    .get()
                    .officer_allowed_locations
                )
            elif user.is_claim_admin:
                from core.models.user import ClaimAdmin

                return (
                    ClaimAdmin.objects.filter(
                        code=user.username, has_login=True, validity_to__isnull=True
                    )
                    .get()
                    .officer_allowed_locations
                )
            elif user.is_superuser:
                return Location.objects
            else:
                return cls.objects.allowed(user.i_user_id, qs=True, strict=False)
        return queryset

    @staticmethod
    def build_user_location_filter_query(
        cls, user: core_models.InteractiveUser, queryset=None
    ):
        return cls.objects.build_user_location_filter_query(user, queryset=queryset)

    class Meta:
        managed = True
        db_table = "tblLocations"


class HealthFacilityLegalForm(models.Model):
    code = models.CharField(db_column="LegalFormCode", primary_key=True, max_length=1)
    legal_form = models.CharField(db_column="LegalForms", max_length=50)
    sort_order = models.IntegerField(db_column="SortOrder", blank=True, null=True)
    alt_language = models.CharField(
        db_column="AltLanguage", max_length=50, blank=True, null=True
    )

    class Meta:
        managed = True
        db_table = "tblLegalForms"


class HealthFacilitySubLevel(models.Model):
    code = models.CharField(db_column="HFSublevel", primary_key=True, max_length=1)
    health_facility_sub_level = models.CharField(
        db_column="HFSublevelDesc", max_length=50, blank=True, null=True
    )
    sort_order = models.IntegerField(db_column="SortOrder", blank=True, null=True)
    alt_language = models.CharField(
        db_column="AltLanguage", max_length=50, blank=True, null=True
    )

    class Meta:
        managed = True
        db_table = "tblHFSublevel"


class HealthFacility(core_models.VersionedModel, core_models.ExtendableModel):
    class HealthFacilityStatus(models.TextChoices):
        ACTIVE = "AC"
        INACTIVE = "IN"
        DELISTED = "DE"
        IDLE = "ID"

    id = models.AutoField(db_column="HfID", primary_key=True)
    uuid = models.CharField(
        db_column="HfUUID", max_length=36, default=uuid.uuid4, unique=True
    )

    code = models.CharField(db_column="HFCode", max_length=8)
    name = models.CharField(db_column="HFName", max_length=100)
    acc_code = models.CharField(
        db_column="AccCode", max_length=25, blank=True, null=True
    )
    legal_form = models.ForeignKey(
        HealthFacilityLegalForm,
        models.DO_NOTHING,
        db_column="LegalForm",
        related_name="health_facilities",
    )
    level = models.CharField(db_column="HFLevel", max_length=1)
    sub_level = models.ForeignKey(
        HealthFacilitySubLevel,
        models.DO_NOTHING,
        db_column="HFSublevel",
        blank=True,
        null=True,
        related_name="health_facilities",
    )
    location = models.ForeignKey(Location, models.DO_NOTHING, db_column="LocationId")
    address = models.CharField(
        db_column="HFAddress", max_length=100, blank=True, null=True
    )
    phone = models.CharField(db_column="Phone", max_length=50, blank=True, null=True)
    fax = models.CharField(db_column="Fax", max_length=50, blank=True, null=True)
    email = models.CharField(db_column="eMail", max_length=50, blank=True, null=True)

    care_type = models.CharField(db_column="HFCareType", max_length=1)

    services_pricelist = models.ForeignKey(
        "medical_pricelist.ServicesPricelist",
        models.DO_NOTHING,
        db_column="PLServiceID",
        blank=True,
        null=True,
        related_name="health_facilities",
    )
    items_pricelist = models.ForeignKey(
        "medical_pricelist.ItemsPricelist",
        models.DO_NOTHING,
        db_column="PLItemID",
        blank=True,
        null=True,
        related_name="health_facilities",
    )
    offline = models.BooleanField(db_column="OffLine", default=False)
    # row_id = models.BinaryField(db_column='RowID', blank=True, null=True)
    audit_user_id = models.IntegerField(db_column="AuditUserID")
    contract_start_date = models.DateField(
        db_column="ContractStartDate", blank=True, null=True
    )
    contract_end_date = models.DateField(
        db_column="ContractEndDate", blank=True, null=True
    )
    status = models.CharField(
        max_length=2,
        choices=HealthFacilityStatus.choices,
        default=HealthFacilityStatus.ACTIVE,
    )

    def __str__(self):
        return self.code + " " + self.name

    @classmethod
    def get_queryset(cls, queryset, user, **kwargs):
        # GraphQL calls with an info object while Rest calls with the user itself
        if isinstance(user, ResolveInfo):
            user = user.context.user
        if (
            user.has_perms(
                LocationConfig.gql_query_health_facilities_perms
            ) and queryset is None
        ):
            queryset = HealthFacility.objects
        else:
            queryset = cls.filter_queryset(queryset)
        if settings.ROW_SECURITY and user.is_anonymous:
            return queryset.filter(id=-1)
        if settings.ROW_SECURITY and not user._u.is_superuser:
            return LocationManager().build_user_location_filter_query(
                user._u, queryset=queryset, loc_types=["D"]
            )
        return queryset

    class Meta:
        managed = True
        db_table = "tblHF"

    LEVEL_HEALTH_CENTER = "C"
    LEVEL_DISPENSARY = "D"
    LEVEL_HOSPITAL = "H"

    CARE_TYPE_IN_PATIENT = "I"
    CARE_TYPE_OUT_PATIENT = "O"
    CARE_TYPE_BOTH = "B"


class HealthFacilityCatchment(core_models.RowSecurityMixin, models.Model):
    row_scope = core_models.ParentScope("health_facility")

    id = models.AutoField(db_column="HFCatchmentId", primary_key=True)
    legacy_id = models.IntegerField(db_column="LegacyId", blank=True, null=True)
    health_facility = models.ForeignKey(
        HealthFacility, models.DO_NOTHING, db_column="HFID", related_name="catchments"
    )
    location = models.ForeignKey(
        Location, models.DO_NOTHING, db_column="LocationId", related_name="catchments"
    )
    catchment = models.IntegerField(db_column="Catchment", blank=True, null=True)
    validity_from = models.DateTimeField(
        db_column="ValidityFrom", blank=True, null=True
    )
    validity_to = models.DateTimeField(db_column="ValidityTo", blank=True, null=True)

    audit_user_id = models.IntegerField(db_column="AuditUserId", blank=True, null=True)

    class Meta:
        managed = True
        db_table = "tblHFCatchment"


class UserDistrict(core_models.VersionedModel):
    id = models.AutoField(db_column="UserDistrictID", primary_key=True)
    user = models.ForeignKey(
        core_models.InteractiveUser, models.DO_NOTHING, db_column="UserID"
    )
    location = models.ForeignKey(Location, models.DO_NOTHING, db_column="LocationId")
    audit_user_id = models.IntegerField(db_column="AuditUserID")

    class Meta:
        managed = True
        db_table = "tblUsersDistricts"

    @classmethod
    def get_user_districts(cls, user):
        """
        Retrieve the list of UserDistricts for a user, the locations are prefetched on two levels.
        :param user: InteractiveUser to filter on
        :return: UserDistrict *objects*
        """
        if hasattr(user, "_u"):
            user = user._u
        cachestringkey = f"user_districts_{user.id}"
        if LocationConfig.no_location_check:
            cachestringkey = "user_districts_all"
        cachedata = _cache_get(cachestringkey)
        districts = []
        if cachedata is None:
            cache_location_if_not_cached()
            cache_location_type = _cache_get("location_types")
            cachedata = []
            if user.is_superuser or LocationConfig.no_location_check:
                for loc in cache_location_type['D']:
                    cachedata.append([0, loc])
            elif not isinstance(user, core_models.InteractiveUser):
                if isinstance(user, core_models.TechnicalUser):
                    logger.warning(
                        f"get_user_districts called with a technical user `{user.username}`. "
                        "We'll return an empty list, but it should be handled before reaching here."
                    )
            else:
                districts = (
                    UserDistrict.objects.filter(
                        user=user,
                        location__type="D",
                        location__parent__isnull=False,
                        *UserDistrict.filter_validity(),
                        *Location.filter_validity(prefix="location__"),
                    )
                    .order_by("location__parent__code")
                    .order_by("location__code")
                )
            for d in districts:
                cachedata.append([d.id, d.location_id])
            _cache_set(cachestringkey, cachedata)
        if not districts and cachedata:
            location_ids = [d[1] for d in cachedata]
            locations = {loc.id: loc for loc in Location.objects.filter(id__in=location_ids)}

            parent_ids = {
                loc.parent_id for loc in locations.values()
                if loc and loc.parent_id
            }
            parents = {loc.id: loc for loc in Location.objects.filter(id__in=parent_ids)}

            for district_id, loc_id in cachedata:
                location = locations.get(loc_id)
                if not location:
                    logger.warning(f"Location ID {loc_id} could not be found even after fallback")
                    continue
                if location.parent_id:
                    location.parent = parents.get(location.parent_id)
                districts.append(UserDistrict(id=district_id, user=user, location=location))

        return districts

    @classmethod
    def get_user_locations(cls, user):
        """
        Retrieve the list of Locations in the UserDistricts of a certain user.
        :param user: InteractiveUser to filter on
        :return: Location objects to filter on.
        """
        if not core_models.InteractiveUser.is_interactive_user(user):
            return Location.objects.none()
        return (
            Location.objects.filter(*Location.filter_validity())
            .filter(parent__parent__userdistrict__user=user.i_user)
            .order_by("code")
        )

    @classmethod
    def get_queryset(cls, queryset, user):
        if isinstance(user, ResolveInfo):
            user = user.context.user
        if settings.ROW_SECURITY and user.is_anonymous:
            return queryset.filter(id=-1)
        if settings.ROW_SECURITY:
            pass
        return queryset


@receiver(post_save, sender=UserDistrict)
@receiver(post_delete, sender=UserDistrict)
def free_cache_post_user_district_save(sender, instance, **kwargs):
    free_cache_for_user_now_and_on_commit(instance.user_id)


@receiver(post_save, sender=Location)
def location_changed(sender, instance, **kwargs):
    update_location_cache(sender, instance, **kwargs)
    free_cache_for_user_now_and_on_commit()


@receiver(post_delete, sender=Location)
def location_deleted(sender, instance, **kwargs):
    cache_delete(f"location_{instance.id}", alias=LOCATION_CACHE)
    update_location_cache(sender, instance, location_id=instance.id, **kwargs)
    free_cache_for_user_now_and_on_commit()


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
        db_table = "tblOfficerVillages"

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
    location = models.ForeignKey(Location, models.DO_NOTHING, related_name="mutations")
    mutation = models.ForeignKey(
        core_models.MutationLog, models.DO_NOTHING, related_name="locations"
    )

    class Meta:
        managed = True
        db_table = "location_LocationMutation"


class HealthFacilityMutation(core_models.UUIDModel):
    health_facility = models.ForeignKey(
        HealthFacility, models.DO_NOTHING, related_name="mutations"
    )
    mutation = models.ForeignKey(
        core_models.MutationLog, models.DO_NOTHING, related_name="health_facilities"
    )

    class Meta:
        managed = True
        db_table = "location_HealthFacilityMutation"
