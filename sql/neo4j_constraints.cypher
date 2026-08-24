CREATE CONSTRAINT region_code IF NOT EXISTS
FOR (r:Region) REQUIRE r.code IS UNIQUE;

CREATE CONSTRAINT state_code IF NOT EXISTS
FOR (s:State) REQUIRE s.code IS UNIQUE;

CREATE CONSTRAINT source_entity_key IF NOT EXISTS
FOR (e:SourceEntity) REQUIRE e.entity_key IS UNIQUE;

CREATE CONSTRAINT report_type_name IF NOT EXISTS
FOR (rt:ReportType) REQUIRE rt.name IS UNIQUE;

CREATE CONSTRAINT metric_name IF NOT EXISTS
FOR (m:Metric) REQUIRE m.name IS UNIQUE;

CREATE CONSTRAINT timeseries_uuid IF NOT EXISTS
FOR (ts:TimeSeries) REQUIRE ts.uuid IS UNIQUE;

CREATE CONSTRAINT observation_key IF NOT EXISTS
FOR (o:Observation) REQUIRE o.observation_key IS UNIQUE;

CREATE CONSTRAINT country_code IF NOT EXISTS
FOR (country:Country) REQUIRE country.code IS UNIQUE;

CREATE CONSTRAINT grid_entity_key IF NOT EXISTS
FOR (entity:GridEntity) REQUIRE entity.key IS UNIQUE;

CREATE CONSTRAINT voltage_node_key IF NOT EXISTS
FOR (node:VoltageNode) REQUIRE node.key IS UNIQUE;

CREATE CONSTRAINT transmission_line_key IF NOT EXISTS
FOR (line:TransmissionLine) REQUIRE line.key IS UNIQUE;
