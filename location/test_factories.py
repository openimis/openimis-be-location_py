import random
import string

import factory

from location.models import (
    Location,
    HealthFacility,
    HealthFacilityLegalForm,
    HealthFacilitySubLevel,
    HealthFacilityCatchment,
)


def generate_random_string(length=6):
    letters = string.ascii_uppercase
    return "".join(random.choice(letters) for i in range(length))


class LocationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Location

    # the whole R/D/W/V chain derives its codes and names from the village at the bottom,
    # so the seed travels down the SubFactory chain instead of up
    class Params:
        base_code = factory.LazyFunction(generate_random_string)
        base_name = factory.LazyAttribute(lambda o: "Test Village " + o.base_code)

    type = "V"
    code = factory.LazyAttribute(lambda o: "TST-" + o.type)
    name = factory.LazyAttribute(lambda o: "Test location " + o.type)
    # literal kept from the legacy helper: the model default is py_datetime.now, and tests
    # compare filter_validity() windows against these fixed dates
    validity_from = "2019-06-01"
    audit_user_id = -1


class RegionFactory(LocationFactory):
    type = "R"
    code = factory.LazyAttribute(lambda o: f"R-{o.base_code}")
    name = factory.LazyAttribute(lambda o: f"Region {o.base_name}")


class DistrictFactory(LocationFactory):
    type = "D"
    code = factory.LazyAttribute(lambda o: f"D-{o.base_code}")
    name = factory.LazyAttribute(lambda o: f"District {o.base_name}")
    parent = factory.SubFactory(
        RegionFactory,
        base_code=factory.SelfAttribute("..base_code"),
        base_name=factory.SelfAttribute("..base_name"),
    )


class WardFactory(LocationFactory):
    type = "W"
    code = factory.LazyAttribute(lambda o: f"W-{o.base_code}")
    name = factory.LazyAttribute(lambda o: f"Ward {o.base_name}")
    parent = factory.SubFactory(
        DistrictFactory,
        base_code=factory.SelfAttribute("..base_code"),
        base_name=factory.SelfAttribute("..base_name"),
    )


class VillageFactory(LocationFactory):
    type = "V"
    code = factory.LazyAttribute(lambda o: o.base_code)
    name = factory.LazyAttribute(lambda o: o.base_name)
    parent = factory.SubFactory(
        WardFactory,
        base_code=factory.SelfAttribute("..base_code"),
        base_name=factory.SelfAttribute("..base_name"),
    )


class HealthFacilityLegalFormFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HealthFacilityLegalForm
        django_get_or_create = ("code",)

    code = "C"
    legal_form = "Company"
    sort_order = 1


class HealthFacilitySubLevelFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HealthFacilitySubLevel
        django_get_or_create = ("code",)

    code = "S"
    health_facility_sub_level = "Standard"
    sort_order = 1


class HealthFacilityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HealthFacility

    # no location default on purpose: the helper resolves it against existing districts
    code = "TST-HF"
    name = factory.LazyAttribute(lambda o: "Test location " + o.code)
    level = "H"
    care_type = "B"
    offline = False
    validity_from = "2019-01-01"
    audit_user_id = -1
    legal_form = factory.SubFactory(HealthFacilityLegalFormFactory)
    sub_level = factory.SubFactory(HealthFacilitySubLevelFactory)


class HealthFacilityCatchmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HealthFacilityCatchment

    catchment = 100
    validity_from = "2019-01-01"
    validity_to = None
    audit_user_id = -1
