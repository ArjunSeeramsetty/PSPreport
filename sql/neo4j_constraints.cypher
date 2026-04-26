CREATE CONSTRAINT grid_entity_key IF NOT EXISTS
FOR (e:GridEntity) REQUIRE e.entity_key IS UNIQUE;

CREATE INDEX grid_entity_type IF NOT EXISTS
FOR (e:GridEntity) ON (e.entity_type);

CREATE INDEX timeseries_uuid_idx IF NOT EXISTS
FOR (e:GridEntity) ON (e.timeseries_uuid);

