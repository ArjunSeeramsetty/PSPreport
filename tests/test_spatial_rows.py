"""Tests for deterministic spatial reconstruction of NRLDC continuation rows."""

from psp_pipeline.parsing.rldc.spatial_rows import (
    SpatialTextItem,
    reconstruct_generation_rows,
)


def test_reconstruct_generation_row_preserves_wrapped_label_and_columns() -> None:
    """A wrapped station name is associated with its nearby numeric baseline."""

    items = [
        SpatialTextItem(1, 6, "ACME SOLAR", 20.0, 60.0),
        SpatialTextItem(2, 6, "PRIVATE LTD", 30.0, 67.0),
        SpatialTextItem(3, 6, "300", 121.0, 62.0),
        SpatialTextItem(4, 6, "0", 165.0, 62.0),
        SpatialTextItem(5, 6, "0", 207.0, 62.0),
        SpatialTextItem(6, 6, "0", 246.0, 62.0),
        SpatialTextItem(7, 6, "280", 286.0, 62.0),
        SpatialTextItem(8, 6, "14:15", 329.0, 62.0),
        SpatialTextItem(9, 6, "0", 380.0, 62.0),
        SpatialTextItem(10, 6, "-", 420.0, 62.0),
        SpatialTextItem(11, 6, "2.5", 459.0, 62.0),
        SpatialTextItem(12, 6, "2.4", 502.0, 62.0),
        SpatialTextItem(13, 6, "2.3", 542.0, 62.0),
        SpatialTextItem(14, 6, "96", 582.0, 62.0),
        SpatialTextItem(15, 6, "-0.1", 620.0, 62.0),
    ]
    centers = {
        "InstalledCapacityMW": 121.0,
        "DeclaredCapacityMW": 165.0,
        "EveningPeakMW": 207.0,
        "OffPeakMW": 246.0,
        "DayPeakMW": 286.0,
        "DayPeakTime": 329.0,
        "MinimumGenerationMW": 380.0,
        "MinimumGenerationTime": 420.0,
        "ScheduledEnergyMU": 459.0,
        "GrossEnergyMU": 502.0,
        "NetEnergyMU": 542.0,
        "AverageMW": 582.0,
        "UIMU": 620.0,
    }

    rows = reconstruct_generation_rows(items, column_centers=centers)

    assert len(rows) == 1
    assert rows[0].label == "ACME SOLAR PRIVATE LTD"
    assert rows[0].values["InstalledCapacityMW"] == "300"
    assert rows[0].values["MinimumGenerationTime"] == "-"
    assert rows[0].value_item_ids["UIMU"] == 15
