from functools import reduce
import uuid

from core import fields, filter_validity
from django.conf import settings
from django.db import models
from core import models as core_models
from graphql import ResolveInfo
from .apps import LocationConfig
import logging

logger = logging.getLogger(__file__)


class LocationManager(models.Manager):
    def parents(self, location_id):
        parents = Location.objects.raw(
            """
            WITH CTE_PARENTS AS (
            SELECT
                LocationId,
                LocationType,
                ParentLocationId
            FROM
                tblLocations
            WHERE LocationId = %s
            UNION ALL

            SELECT
                parent.LocationId,
                parent.LocationType,
                parent.ParentLocationId
            FROM
                tblLocations parent
                INNER JOIN CTE_PARENTS leaf
                    ON parent.LocationId = leaf.ParentLocationId
            )
            SELECT * FROM CTE_PARENTS;
        """,
            (location_id,),
        )
        return self.filter(id__in=[x.id for x in parents])

    def children(self, location_id):
        children = Location.objects.raw(
            """
            WITH CTE_CHILDREN AS (
            SELECT
                LocationId,
                LocationType,
                ParentLocationId,
                0 as Level
            FROM
                tblLocations
            WHERE ParentLocationId = %s
            UNION ALL

            SELECT
                child.LocationId,
                child.LocationType,
                child.ParentLocationId,
                parent.Level + 1
            FROM
                tblLocations child
                INNER JOIN CTE_CHILDREN parent
                    ON child.ParentLocationId = parent.LocationId
            )
            SELECT * FROM CTE_CHILDREN;
        """,
            (location_id,),
        )
        return self.filter(id__in=[x.id for x in children])


class Location(core_models.VersionedModel):
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
        if settings.ROW_SECURITY and not user.has_perms(LocationConfig.gql_mutation_create_locations_perms):
            dists = UserDistrict.get_user_districts(user._u)
            regs = set([d.location.parent.id for d in dists])
            dists = set([d.location.id for d in dists])
            filters = []
            prev = "id"
            for i, tpe in enumerate(LocationConfig.location_types):
                loc_ids = dists if i else regs
                filters += [models.Q(type__exact=tpe) & models.Q(**{"%s__in" % prev: loc_ids})]
                prev = "parent__" + prev if i > 1 else "parent_" + prev if i else prev
            return queryset.filter(reduce((lambda x, y: x | y), filters))
        return queryset

    class Meta:
        managed = False
        db_table = 'tblLocations'


class HealthFacilityLegalForm(models.Model):
    code = models.CharField(db_column='LegalFormCode', primary_key=True, max_length=1)
    legal_form = models.CharField(db_column='LegalForms', max_length=50)
    sort_order = models.IntegerField(db_column='SortOrder', blank=True, null=True)
    alt_language = models.CharField(db_column='AltLanguage', max_length=50, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'tblLegalForms'


class HealthFacilitySubLevel(models.Model):
    code = models.CharField(db_column='HFSublevel', primary_key=True, max_length=1)
    health_facility_sub_level = models.CharField(db_column='HFSublevelDesc', max_length=50, blank=True, null=True)
    sort_order = models.IntegerField(db_column='SortOrder', blank=True, null=True)
    alt_language = models.CharField(db_column='AltLanguage', max_length=50, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'tblHFSublevel'


class HealthFacility(core_models.VersionedModel):
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
    offline = models.BooleanField(db_column='OffLine')
    # row_id = models.BinaryField(db_column='RowID', blank=True, null=True)
    audit_user_id = models.IntegerField(db_column='AuditUserID')

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
        if settings.ROW_SECURITY:
            dist = UserDistrict.get_user_districts(user._u)
            return queryset.filter(
                location_id__in=[l.location_id for l in dist]
            )
        return queryset

    class Meta:
        managed = False
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
        managed = False
        db_table = 'tblHFCatchment'


class UserDistrict(core_models.VersionedModel):
    id = models.AutoField(db_column="UserDistrictID", primary_key=True)
    user = models.ForeignKey(
        core_models.InteractiveUser, models.DO_NOTHING, db_column="UserID"
    )
    location = models.ForeignKey(Location, models.DO_NOTHING, db_column="LocationId")
    audit_user_id = models.IntegerField(db_column="AuditUserID")

    class Meta:
        managed = False
        db_table = 'tblUsersDistricts'

    @classmethod
    def get_user_districts(cls, user):
        """
        Retrieve the list of UserDistricts for a user, the locations are prefetched on two levels.
        :param user: InteractiveUser to filter on
        :return: UserDistrict *objects*
        """
        if not isinstance(user, core_models.InteractiveUser):
            if isinstance(user, core_models.TechnicalUser):
                logger.warning(f"get_user_districts called with a technical user `{user.username}`. "
                               "We'll return an empty list, but it should be handled before reaching here.")
            return UserDistrict.objects.none()
        return (
            UserDistrict.objects.select_related("location")
            .only("location__id", "location__parent__id")
            .select_related("location__parent")
            .filter(user=user)
            .filter(*filter_validity())
            .order_by("location__parent_code")
            .order_by("location__code")
            .exclude(location__parent__isnull=True)
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
        managed = False
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
