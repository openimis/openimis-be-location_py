from django.apps import AppConfig

MODULE_NAME = "location"

DEFAULT_CFG = {
    "location_types": ['R', 'D', 'W', 'V'],
    "gql_query_locations_perms": ["121901"],
    "gql_query_health_facilities_perms": ["121101"],
    "gql_mutation_create_locations_perms": ["121902"],
    "gql_mutation_edit_locations_perms": ["121903"],
    "gql_mutation_delete_locations_perms": ["121904"],
    "gql_mutation_move_location_perms": ["121905"],
    "gql_mutation_create_region_locations_perms": ["121906"],
    "gql_mutation_create_health_facilities_perms": ["121102"],
    "gql_mutation_edit_health_facilities_perms": ["121103"],
    "gql_mutation_delete_health_facilities_perms": ["121104"],
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
    "health_facility_contract_dates_mandatory": False
}


class LocationConfig(AppConfig):
    name = MODULE_NAME

    location_types = []
    gql_query_locations_perms = []
    gql_query_health_facilities_perms = []
    gql_mutation_create_locations_perms = []
    gql_mutation_create_region_locations_perms = []
    gql_mutation_edit_locations_perms = []
    gql_mutation_delete_locations_perms = []
    gql_mutation_move_location_perms = []
    gql_mutation_create_health_facilities_perms = []
    gql_mutation_edit_health_facilities_perms = []
    gql_mutation_delete_health_facilities_perms = []

    health_facility_level = []
    health_facility_contract_dates_mandatory = None
    no_location_check = None

    def __load_config(self, cfg):
        for field in cfg:
            if hasattr(LocationConfig, field):
                setattr(LocationConfig, field, cfg[field])

    def ready(self):
        from core.models import ModuleConfiguration

        cfg = ModuleConfiguration.get_or_default(MODULE_NAME, DEFAULT_CFG)
        self.__load_config(cfg)
        self._register_uba_link_types()

    @staticmethod
    def _register_uba_link_types():
        """
        Declare the two credentials held on a location module object.

        Location registers them rather than core because only it knows where they sit in
        the location tree, and that is exactly what `params` carries: the row filter reads
        it to turn a credential into a queryset filter, so no call site has to spell out
        the path from the model it filters to the linked object.

        `location_type` says the credential is held on a Location of that type, declared
        as a code and not a depth because `location_types` is deployment configuration.
        `location_field` says it is held on a model hanging off a location, naming the
        field that points there.
        """
        from core.apps import (
            CLAIM_ADMIN_UBA_LINK_TYPE,
            ENROLMENT_UBA_LINK_TYPE,
            HEALTH_FACILITY_MODEL,
            VILLAGE_LOCATION_TYPE,
            VILLAGE_MODEL,
        )
        from core.uba_link_types import register_uba_link_type

        register_uba_link_type(
            ENROLMENT_UBA_LINK_TYPE,
            "Enrolment officer of the village",
            models=(VILLAGE_MODEL,),
            params={"location_type": VILLAGE_LOCATION_TYPE},
        )
        register_uba_link_type(
            CLAIM_ADMIN_UBA_LINK_TYPE,
            "Claim administrator of the health facility",
            models=(HEALTH_FACILITY_MODEL,),
            params={"location_field": "location"},
        )

    def set_dataloaders(self, dataloaders):
        from .dataloaders import LocationLoader, HealthFacilityLoader

        dataloaders["location_loader"] = LocationLoader()
        dataloaders["health_facility_loader"] = HealthFacilityLoader()
