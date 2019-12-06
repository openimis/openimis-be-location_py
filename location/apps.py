from django.apps import AppConfig

MODULE_NAME = "location"

DEFAULT_CFG = {
    "gql_query_locations_perms": [],
    "gql_query_health_facilities_perms": []
}


class LocationConfig(AppConfig):
    name = MODULE_NAME

    gql_query_locations_perms = []
    gql_query_health_facilities_perms = []

    def _configure_permissions(self, cfg):
        LocationConfig.gql_query_locations_perms = cfg[
            "gql_query_locations_perms"]
        LocationConfig.gql_query_health_facilities_perms = cfg[
            "gql_query_health_facilities_perms"]

    def ready(self):
        from core.models import ModuleConfiguration
        cfg = ModuleConfiguration.get_or_default(MODULE_NAME, DEFAULT_CFG)
        self._configure_permissions(cfg)
