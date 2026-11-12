"""Connector for nadlan.gov.il -- the Israel Tax Authority's public sold-
property deals registry. Build order step 2 (see the plan); NOT wired into
CONNECTORS in routes/estates_data.py yet.

Confirmed from third-party tooling (not from any official doc, since none
exists): the registry's per-deal fields are signing date, price, price per
sqm, address, neighborhood, rooms, area, property type, floor,
buildingFloors, gush/helka/tat-helka, isFirstHand, and -- for roughly one
deal in five -- the SAME unit's prior sale (prevDeals/trend). That shape
maps directly onto this package's SaleTransaction/Unit/GeoParcel fields.

What's still unresolved, and has to be done by inspecting the live site in
a real browser (nadlan.gov.il is a JS-rendered app, not a documented REST
API) rather than guessed here:
  1. The actual request nadlan.gov.il's own frontend makes for a given
     settlement/date-range (URL, params, required headers).
  2. Confirming the Israel-only IP restriction, and arranging an Israeli
     egress path (proxy/VPS) if it's real -- this can't be solved in code.
  3. Whatever pagination/rate-limit behavior the endpoint has.

Once (1)-(3) are confirmed, this should mirror data_gov_il.py's shape:
fetch raw deals for a city, stage each one as a RawIngestRecord keyed by
(SOURCE, external_id) so re-runs don't duplicate, and nothing else --
normalize.py maps the raw payload into GeoParcel/Unit/SaleTransaction, this
file never writes a canonical table."""

SOURCE = 'nadlan_gov'


def ingest_city(city_name_hebrew):
    raise NotImplementedError(
        'nadlan.gov.il has no documented API -- the real request shape needs to be '
        'captured from the live site (browser devtools) before this can be implemented. '
        'See this module\'s docstring for what\'s already confirmed about the data shape.'
    )
