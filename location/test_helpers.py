import string
import random
from location.models import (
    Location,
    UserDistrict,
    HealthFacility,
    HealthFacilityLegalForm,
    HealthFacilitySubLevel,
    HealthFacilityCatchment,
)


def generate_random_string(length=6):
    letters = string.ascii_uppercase
    return "".join(random.choice(letters) for i in range(length))


def assign_user_districts(user, district_codes):
    for dc in district_codes:
        dc_location = Location.objects.get(code=dc, *Location.filter_validity())
        UserDistrict.objects.get_or_create(
            user=user.i_user,
            validity_to=None,
            location=dc_location,
            validity_from="2019-06-01",
            audit_user_id=-1,
        )


def create_test_location(loc_type, valid=True, custom_props=None):
    if custom_props is None:
        custom_props = {}
    else:
        custom_props = {k: v for k, v in custom_props.items() if hasattr(Location, k)}
    code = "TST-" + loc_type
    if "code" in custom_props:
        code = custom_props.pop("code")
    location = Location.objects.filter(code=code, validity_to__isnull=valid).first()
    if location is not None:
        return location
    else:
        return Location.objects.create(
            **{
                "code": code,
                "type": loc_type,
                "name": "Test location " + loc_type,
                "validity_from": "2019-06-01",
                "validity_to": None if valid else "2019-06-01",
                "audit_user_id": -1,
                **custom_props,
            }
        )


def create_test_village(custom_props=None):
    if custom_props is None:
        custom_props = {}

    code = custom_props.get("code", generate_random_string())
    if code:
        location = Location.objects.filter(code=code, validity_to__isnull=True).first()
        if location:
            return location

    name = custom_props.get("name", "Test Village " + code)
    custom_props["name"] = name
    test_region = create_test_location(
        "R",
        custom_props={
            "name": "Region " + name,
            "code": f"R-{code}",
        },
    )
    test_district = create_test_location(
        "D",
        custom_props={
            "parent": test_region,
            "name": "District " + name,
            "code": f"D-{code}",
        },
    )
    test_ward = create_test_location(
        "W",
        custom_props={
            "parent": test_district,
            "name": "Ward " + name,
            "code": f"W-{code}",
        },
    )
    custom_props["parent"] = test_ward
    # The generated code has to reach the village too, not only its ancestors.
    # Without it `create_test_location` falls back to its "TST-V" default, so
    # every argument-less call returned the *same* village - and with it
    # whatever officers, insurees and families earlier tests had attached to
    # it. That is how a test could pass on a fresh database and fail on a
    # long-lived one, or the reverse, with nothing in the test to explain it.
    custom_props["code"] = code
    test_village = create_test_location("V", custom_props=custom_props)

    return test_village


def create_test_basic_health_facility_legal_form():
    create_test_health_facility_legal_form(code="C", legal_form="Charity", sort_order=1)
    create_test_health_facility_legal_form(code="D", legal_form="District organization", sort_order=2)
    create_test_health_facility_legal_form(code="P", legal_form="Private organization", sort_order=3)
    create_test_health_facility_legal_form(code="G", legal_form="Government", sort_order=4)


def create_test_health_facility_legal_form(code="C", legal_form="Company", sort_order=1):
    """Create a test health facility legal form if it doesn't exist."""
    obj, created = HealthFacilityLegalForm.objects.get_or_create(
        code=code,
        defaults={
            "legal_form": legal_form,
            "sort_order": sort_order,
        }
    )
    return obj


def create_test_basic_health_facility_sub_level():
    create_test_health_facility_sub_level(code="D", health_facility_sub_level="Dispensary", sort_order=1)
    create_test_health_facility_sub_level(code="H", health_facility_sub_level="Hospital", sort_order=2)
    create_test_health_facility_sub_level(code="C", health_facility_sub_level="Health Centre", sort_order=3)


def create_test_health_facility_sub_level(code="S", health_facility_sub_level="Standard", sort_order=1):
    """Create a test health facility sub-level if it doesn't exist."""
    obj, created = HealthFacilitySubLevel.objects.get_or_create(
        code=code,
        defaults={
            "health_facility_sub_level": health_facility_sub_level,
            "sort_order": sort_order,
        }
    )
    return obj


def create_test_health_facility(
    code=None, location_id=None, valid=True, custom_props=None
):
    if custom_props is None:
        custom_props = {}
    else:
        custom_props = {
            k: v for k, v in custom_props.items() if hasattr(HealthFacility, k)
        }

    if custom_props is not None and "code" in custom_props:
        code = custom_props.pop("code")
    elif not code:
        code = "TST-HF"
    if location_id:
        custom_props["location_id"] = location_id
    elif (
        location_id is None and "location" not in custom_props and "location_id" not in custom_props
    ):
        location = Location.objects.filter(type="D", validity_to__isnull=True).first()
        custom_props["location"] = location or create_test_location("D")

    # Ensure required reference data exists
    if not custom_props.get("legal_form"):
        legal_form = create_test_health_facility_legal_form()
        custom_props["legal_form"] = legal_form

    if not custom_props.get("sub_level") and "sub_level" not in custom_props:
        # Only set sub_level if not explicitly set to None
        sub_level = create_test_health_facility_sub_level()
        custom_props["sub_level"] = sub_level

    obj = HealthFacility.objects.filter(code=code, validity_to__isnull=valid).first()
    if obj is not None:
        if custom_props:
            HealthFacility.objects.filter(id=obj.id).update(**custom_props)
            obj.refresh_from_db()
    else:
        obj = HealthFacility.objects.create(
            **{
                "code": code,
                "level": "H",
                "name": "Test location " + code,
                "care_type": "B",
                "validity_from": "2019-01-01",
                "validity_to": None if valid else "2019-06-01",
                "audit_user_id": -1,
                "offline": False,
                **custom_props,
            }
        )
    # reseting custom props to avoid having it in next calls
    return obj


def create_test_health_catchment(hf, location, custom_props=None):
    if custom_props is None:
        custom_props = {}
    else:
        custom_props = {
            k: v for k, v in custom_props.items() if hasattr(HealthFacilityCatchment, k)
        }
    obj = HealthFacilityCatchment.objects.create(
        **{
            "location": location,
            "health_facility": hf,
            "catchment": 100,
            "validity_from": "2019-01-01",
            "validity_to": None,
            "audit_user_id": -1,
            **custom_props,
        }
    )

    return obj


def create_basic_test_locations():
    """
    Create basic test location hierarchy for testing purposes.
    Creates locations based on the provided SQL data structure.
    """
    from django.utils import timezone
    import uuid

    # Basic location data for testing
    location_data = [
        {
            "code": "R2",
            "name": "Tahida",
            "type": "R",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "68753566-9d2e-4cec-936e-4c6bf1968c0d",
        },
        {
            "code": "R2D1",
            "name": "Rajo",
            "type": "D",
            "parent_code": "R2",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "2ee8ea9c-aef7-400b-9b36-f391f956f73e",
        },
        {
            "code": "R2D2",
            "name": "Vida",
            "type": "D",
            "parent_code": "R2",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "176d0c41-13dc-4faf-9c1e-95109f086059",
        },
        {
            "code": "R2D1M1",
            "name": "Jaber",
            "type": "W",
            "parent_code": "R2D1",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "bf590058-be5c-494e-9e05-c7f2695c645e",
        },
        {
            "code": "R2D1M1V1",
            "name": "Utha",
            "type": "V",
            "parent_code": "R2D1M1",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "b2e5b0c1-3d57-408c-b7de-11511ce1cbcf",
        },
        {
            "code": "R2D2M1",
            "name": "Majhi",
            "type": "W",
            "parent_code": "R2D2",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "225789ce-4d14-4098-8ae2-3c90e96fae8f",
        },
        {
            "code": "R2D2M1V1",
            "name": "Radho",
            "type": "V",
            "parent_code": "R2D2M1",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "9ea9f849-2c7c-4454-810d-cf60bde6bdc7",
        },
        {
            "code": "R1",
            "name": "Ultha",
            "type": "R",
            "validity_from": timezone.datetime(2016, 1, 1),
            "uuid": "40c4010d-8c9d-4be3-8653-e647b21b19a9",
        },
        {
            "code": "R1D1",
            "name": "Rapta",
            "type": "D",
            "parent_code": "R1",
            "validity_from": timezone.datetime(2016, 1, 1),
            "uuid": "35043da3-1e04-46f9-a67e-00b9973b588f",
        },
        {
            "code": "R1D1M1",
            "name": "Jamu",
            "type": "W",
            "parent_code": "R1D1",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "820e1a1f-4195-445b-a14c-4f762fad6780",
        },
        {
            "code": "R1D1M2",
            "name": "Adhi",
            "type": "W",
            "parent_code": "R1D1",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "522c4c5e-10f1-4f6a-98ef-1ae75a259eb5",
        },
        {
            "code": "R1D1M3",
            "name": "Jobber",
            "type": "W",
            "parent_code": "R1D1",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "2641ec90-7879-469e-9d8b-f180c720a079",
        },
        {
            "code": "R1D1M4",
            "name": "Radler",
            "type": "W",
            "parent_code": "R1D1",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "6c3b52cb-7926-4345-8048-77ac99ae80c1",
        },
        {
            "code": "R1D1M5",
            "name": "Radler",
            "type": "W",
            "parent_code": "R1D1",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "6c3b52cb-7926-4345-8048-77ac99ae80c2",  # slight change for uniqueness
        },
        {
            "code": "R1D1M1V1",
            "name": "Rachla",
            "type": "V",
            "parent_code": "R1D1M1",
            "validity_from": timezone.datetime(2016, 1, 1),
            "uuid": "4842af48-fa6a-46fa-b5bb-08001bb58f5f",
        },
        {
            "code": "R1D1M1V2",
            "name": "Darbu",
            "type": "V",
            "parent_code": "R1D1M1",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "108a16ea-5d7d-4534-a7e5-ab82c474fa7f",
        },
        {
            "code": "R1D1M1V3",
            "name": "Agdo",
            "type": "V",
            "parent_code": "R1D1M1",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "eba563de-13cb-4cea-9bdd-ecab9a4344c5",
        },
        {
            "code": "R1D1M2V1",
            "name": "Jamula",
            "type": "V",
            "parent_code": "R1D1M2",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "40485985-e4ab-43f9-9700-bf80e342a1ee",
        },
        {
            "code": "R1D1M3V1",
            "name": "Rathula",
            "type": "V",
            "parent_code": "R1D1M3",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "f28d1e17-92ea-4db4-b26b-88ca429731b5",
        },
        {
            "code": "R1D1M4V1",
            "name": "Jobla",
            "type": "V",
            "parent_code": "R1D1M4",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "712451a5-6074-441c-9a57-5229d33a1a6c",
        },
        {
            "code": "R1D1M5V1",
            "name": "Rolo",
            "type": "V",
            "parent_code": "R1D1M5",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "e4a522fc-fa81-4954-9f11-1fee3853dbc0",
        },
        {
            "code": "R1D2",
            "name": "Jambero",
            "type": "D",
            "parent_code": "R1",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "6ca4b45b-ac17-4ff4-954c-dc1294bc66d1",
        },
        {
            "code": "R1D3",
            "name": "Uptol",
            "type": "D",
            "parent_code": "R1",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "e04c7312-46b0-4526-94d5-1717e4ec978f",
        },
        {
            "code": "R1D2M1",
            "name": "Actoloby",
            "type": "W",
            "parent_code": "R1D2",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "4cf9a26d-6cb9-48cc-b42b-55ef61a9d0f2",
        },
        {
            "code": "R1D2M2",
            "name": "Remorlogy",
            "type": "W",
            "parent_code": "R1D2",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "cac524c0-1bac-4c96-9376-9d0ee35eb0aa",
        },
        {
            "code": "R1D2M1V1",
            "name": "Holobo",
            "type": "V",
            "parent_code": "R1D2M1",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "ca5ec00f-eaa3-4af8-ac11-7bc5abb3341b",
        },
        {
            "code": "R1D2M1V2",
            "name": "Octo",
            "type": "V",
            "parent_code": "R1D2M1",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "d7c17b9f-c508-4b92-b308-4c3727a5ada0",
        },
        {
            "code": "R1D2M1V3",
            "name": "Raberjab",
            "type": "V",
            "parent_code": "R1D2M1",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "d862b77c-0e83-484b-b337-3c7adb06c034",
        },
        {
            "code": "R1D2M2V1",
            "name": "Agilo",
            "type": "V",
            "parent_code": "R1D2M2",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "b29ccc93-779d-459c-942c-df0b98b22ebb",
        },
        {
            "code": "R1D3M1",
            "name": "Uminal",
            "type": "W",
            "parent_code": "R1D3",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "7e89aae5-3627-49e9-aa94-bf387c510939",
        },
        {
            "code": "R1D3M1V1",
            "name": "Uminalum",
            "type": "V",
            "parent_code": "R1D3M1",
            "validity_from": timezone.datetime(2017, 1, 1),
            "uuid": "f30342eb-94bf-4155-92d2-77eaf6559cd6",
        },
    ]

    created_locations = {}
    for data in location_data:
        parent = None
        if "parent_code" in data:
            parent = created_locations.get(data["parent_code"])
            if not parent:
                # Try to find existing parent
                parent = Location.objects.filter(code=data["parent_code"], validity_to__isnull=True).first()

        location, created = Location.objects.get_or_create(
            code=data["code"],
            validity_to=None,
            defaults={
                "name": data["name"],
                "type": data["type"],
                "parent": parent,
                "validity_from": data["validity_from"],
                "validity_to": None,
                "audit_user_id": -1,
                "uuid": data.get("uuid", str(uuid.uuid4())),
            }
        )
        created_locations[data["code"]] = location

    return created_locations
