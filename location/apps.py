from django.apps import AppConfig

MODULE_NAME = "location"

DEFAULT_CFG = {
    "location_types": ['R', 'D', 'W', 'V'],
    "gql_query_locations_perms": [],
    "gql_query_health_facilities_perms": [],
    "gql_mutation_create_locations_perms": ["121902"],
    "gql_mutation_edit_locations_perms": ["121803"],
    "gql_mutation_delete_location_perms": ["121804"],
    "gql_mutation_move_location_perms": ["121905"],
}


class LocationConfig(AppConfig):
    name = MODULE_NAME

    location_types = []
    gql_query_locations_perms = []
    gql_query_health_facilities_perms = []
    gql_mutation_create_locations_perms = []
    gql_mutation_edit_locations_perms = []
    gql_mutation_delete_location_perms = []
    gql_mutation_move_location_perms = []

    def _configure_permissions(self, cfg):
        LocationConfig.location_types = cfg[
            "location_types"]
        LocationConfig.gql_query_locations_perms = cfg[
            "gql_query_locations_perms"]
        LocationConfig.gql_query_health_facilities_perms = cfg[
            "gql_query_health_facilities_perms"]
        LocationConfig.gql_mutation_create_locations_perms = cfg[
            "gql_mutation_create_locations_perms"
        ]
        LocationConfig.gql_mutation_edit_locations_perms = cfg[
            "gql_mutation_edit_locations_perms"
        ]
        LocationConfig.gql_mutation_delete_location_perms = cfg[
            "gql_mutation_delete_location_perms"
        ]
        LocationConfig.gql_mutation_move_location_perms = cfg[
            "gql_mutation_move_location_perms"
        ]

    def ready(self):
        from core.models import ModuleConfiguration
        cfg = ModuleConfiguration.get_or_default(MODULE_NAME, DEFAULT_CFG)
        self._configure_permissions(cfg)
