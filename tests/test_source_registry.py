from psp_pipeline.models.source_registry import load_default_sources


def test_registry_contains_wbes_controlled_source():
    sources = load_default_sources()
    wbes = [x for x in sources if x.source_id == "wbes_national"]
    assert len(wbes) == 1
    assert wbes[0].access_mode == "controlled"


def test_registry_has_public_sources():
    sources = load_default_sources()
    assert any(x.access_mode == "public" for x in sources)
    assert any(x.domain == "RLDC" for x in sources)
    assert any(x.domain == "RPC" for x in sources)

