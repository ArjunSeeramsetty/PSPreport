from pathlib import Path

from psp_pipeline.models.source_registry import filter_sources, load_default_sources, load_sources


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


def test_filter_sources_excludes_controlled_by_default():
    sources = load_default_sources()
    filtered = filter_sources(sources, include_controlled=False)
    assert all(x.access_mode == "public" for x in filtered)
    assert not any(x.source_id == "wbes_national" for x in filtered)


def test_filter_sources_includes_controlled_when_enabled():
    sources = load_default_sources()
    filtered = filter_sources(sources, include_controlled=True)
    assert any(x.source_id == "wbes_national" for x in filtered)


def test_load_sources_reads_yaml_when_present():
    cfg = Path("config/sources.yaml")
    sources = load_sources(cfg)
    assert len(sources) > 0
    assert any(x.source_id == "wbes_national" for x in sources)
