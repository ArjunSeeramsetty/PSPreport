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
    cfg = Path(__file__).resolve().parents[1] / "config" / "sources.yaml"
    sources = load_sources(cfg)
    assert len(sources) > 0
    assert any(x.source_id == "wbes_national" for x in sources)


def test_sources_yaml_contains_all_five_rldcs_public():
    cfg = Path(__file__).resolve().parents[1] / "config" / "sources.yaml"
    sources = load_sources(cfg)
    rldc_regions = {s.region for s in sources if s.domain == "RLDC" and s.access_mode == "public"}
    expected_regions = {"SR", "NR", "WR", "ER", "NER"}
    assert expected_regions.issubset(rldc_regions)


def test_rldc_report_sources_yaml_contains_all_five_public_rldcs():
    import yaml

    cfg = Path(__file__).resolve().parents[1] / "config" / "rldc_report_sources.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    rldc_sources = data.get("rldc_sources", {})

    expected_rldcs = {"SRLDC", "NRLDC", "WRLDC", "ERLDC", "NERLDC"}
    assert set(rldc_sources.keys()) == expected_rldcs

    for name, config in rldc_sources.items():
        assert config.get("access_mode") == "public", f"{name} must have access_mode: public"
        assert "listing_url" in config, f"{name} must define listing_url"
        assert "allow_domains" in config, f"{name} must define allow_domains"
