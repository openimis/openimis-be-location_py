from django.apps import AppConfig

from core.rights_declaration import RightsDeclaration

MODULE_NAME = "location"


# Rights, by entity then by action. `move` and `createRegion` are business actions with
# their own identifier: moving a location within the tree and creating a region are not
# the same thing as modifying or creating any given location.
DJANGO_PERMS = {
    "location": {
        "query": ("location.view_location", 121901),
        "create": ("location.add_location", 121902),
        "update": ("location.change_location", 121903),
        "delete": ("location.delete_location", 121904),
        "move": ("location.move_location", 121905),
        "createRegion": ("location.add_region_location", 121906),
    },
    "healthFacility": {
        "query": ("location.view_healthfacility", 121101),
        "create": ("location.add_healthfacility", 121102),
        "update": ("location.change_healthfacility", 121103),
        "delete": ("location.delete_healthfacility", 121104),
    },
}

_PERM_CFG = {
    "gql_query_locations_perms": ("location", "query"),
    "gql_mutation_create_locations_perms": ("location", "create"),
    "gql_mutation_edit_locations_perms": ("location", "update"),
    "gql_mutation_delete_locations_perms": ("location", "delete"),
    "gql_mutation_move_location_perms": ("location", "move"),
    "gql_mutation_create_region_locations_perms": ("location", "createRegion"),
    "gql_query_health_facilities_perms": ("healthFacility", "query"),
    "gql_mutation_create_health_facilities_perms": ("healthFacility", "create"),
    "gql_mutation_edit_health_facilities_perms": ("healthFacility", "update"),
    "gql_mutation_delete_health_facilities_perms": ("healthFacility", "delete"),
}

RIGHTS = RightsDeclaration(MODULE_NAME, DJANGO_PERMS, _PERM_CFG)

perms = RIGHTS.perms
django_perms = RIGHTS.django_perm_names
configured_perms = RIGHTS.configured
require = RIGHTS.require


DEFAULT_CFG = {
    "location_types": ["R", "D", "W", "V"],
    "no_location_check": False,
    "health_facility_level": [
        {
            "code": "D",
            "display": "Dispensary",
        },
        {
            "code": "C",
            "display": "Health Centre",
        },
        {
            "code": "H",
            "display": "Hospital",
        },
    ],
    "health_facility_contract_dates_mandatory": False,
}


class LocationConfig(AppConfig):
    name = MODULE_NAME

    location_types = []
    # Rights: constants, no longer overridable. They go neither through DEFAULT_CFG
    # nor through ready(): `ModuleConfiguration.get_or_default` now ignores any
    # `_perms` key stored in the database.
    gql_query_locations_perms = RIGHTS.perms("location", "query")
    gql_query_health_facilities_perms = RIGHTS.perms("healthFacility", "query")
    gql_mutation_create_locations_perms = RIGHTS.perms("location", "create")
    gql_mutation_create_region_locations_perms = RIGHTS.perms("location", "createRegion")
    gql_mutation_edit_locations_perms = RIGHTS.perms("location", "update")
    gql_mutation_delete_locations_perms = RIGHTS.perms("location", "delete")
    gql_mutation_move_location_perms = RIGHTS.perms("location", "move")
    gql_mutation_create_health_facilities_perms = RIGHTS.perms("healthFacility", "create")
    gql_mutation_edit_health_facilities_perms = RIGHTS.perms("healthFacility", "update")
    gql_mutation_delete_health_facilities_perms = RIGHTS.perms("healthFacility", "delete")
    no_location_check = None
    health_facility_level = []
    health_facility_contract_dates_mandatory = None

    def __load_config(self, cfg):
        print("Load cfg", cfg)
        for field in cfg:
            if hasattr(LocationConfig, field):
                setattr(LocationConfig, field, cfg[field])

    def ready(self):
        from core.models import ModuleConfiguration

        cfg = ModuleConfiguration.get_or_default(MODULE_NAME, DEFAULT_CFG)
        self.__load_config(cfg)

    def set_dataloaders(self, dataloaders):
        from .dataloaders import LocationLoader, HealthFacilityLoader

        dataloaders["location_loader"] = LocationLoader()
        dataloaders["health_facility_loader"] = HealthFacilityLoader()
