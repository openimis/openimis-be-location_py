# openIMIS Backend Location reference module
This repository holds the files of the openIMIS Backend Location reference module.
It is dedicated to be deployed as a module of [openimis-be_py](https://github.com/openimis/openimis-be_py).

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

## Code climat (develop branch)

[![Maintainability](https://img.shields.io/codeclimate/maintainability/openimis/openimis-be-location_py.svg)](https://codeclimate.com/github/openimis/openimis-be-location_py/maintainability)
[![Test Coverage](https://img.shields.io/codeclimate/coverage/openimis/openimis-be-location_py.svg)](https://codeclimate.com/github/openimis/openimis-be-location_py)

## ORM mapping:
* tblLocations > Location
* tblHF > HealthFacility (partial mapping)
* tblUsersDistricts > UserDistrict

## Listened Django Signals
None

## Services
None

## Reports (template can be overloaded via report.ReportDefinition)
None

## GraphQL Queries
* health_facilities
* health_facilities_str (full text search on code + name)
* locations
* user_districts

## GraphQL Mutations - each mutation emits default signals and return standard error lists (cfr. openimis-be-core_py)
None

## Configuration options (can be changed via core.ModuleConfiguration)
* gql_query_locations_perms: necessary rights to call locations (default:) )[],
* gql_query_health_facilities_perms: necessary rights to call health_facilities and health_facilities_str (default:) [])

## openIMIS Modules Dependencies
* core.models.InteractiveUser