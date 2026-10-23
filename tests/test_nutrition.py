import json
from pathlib import Path

import pytest

from domestique.ingest import fuel_tag, icu, icu_comments

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "evals" / "fixtures" / "icu_nutrition_comments.json").read_text()
)


def comment(cid, content, created="2026-09-11T12:00:00Z", **extra):
    return {"id": cid, "created": created, "content": content, "deleted": False, **extra}


# --- 1.1 platform nutrition fields -------------------------------------------


def test_ride_without_logged_intake_keeps_ingested_null():
    row = icu.map_activity(FIXTURE["activity_no_intake"], "iX")
    assert row["kcal"] == 3100
    assert row["carbs_used_g"] == 520
    assert row["carbs_ingested_g"] is None


def test_platform_carbs_ingested_is_mapped():
    row = icu.map_activity(FIXTURE["activity_platform_carbs"], "iX")
    assert row["carbs_ingested_g"] == 60


def test_wellness_nutrition_and_hydration():
    row = icu.map_wellness(FIXTURE["wellness"], "iX")
    assert (row["kcal_consumed"], row["carbs_g"], row["protein_g"], row["fat_g"]) == (
        3600,
        520,
        140,
        90,
    )
    assert (row["hydration_ml"], row["hydration"]) == (3200, 3)


def test_wellness_without_nutrition_stays_null():
    row = icu.map_wellness({"id": "2026-09-12", "hrv": 70}, "iX")
    assert row["kcal_consumed"] is None
    assert row["hydration_ml"] is None


# --- 2.2 fuel tag parser -----------------------------------------------------


def test_full_tag():
    tag = fuel_tag.parse("#fuel 1.5l 240g 1100kcal")
    assert tag == fuel_tag.Tag(fluid_ml=1500, carbs_g=240, kcal=1100)


def test_full_tag_any_order_and_millilitres():
    tag = fuel_tag.parse("great ride\n#fuel 1100kcal 750ml 240g")
    assert tag is not None
    assert (tag.fluid_ml, tag.carbs_g, tag.kcal) == (750, 240, 1100)


def test_partial_tag_keeps_unknown_words_as_text():
    text = "#fuel 2 bottles 90g"
    tag = fuel_tag.parse(text)
    assert tag is not None
    assert tag.carbs_g == 90
    assert tag.fluid_ml is None
    assert tag.kcal is None
    assert tag.rest == ("2", "bottles")


def test_partial_tag_comment_text_is_stored_untouched():
    row = icu_comments.map_comment(comment(1, "#fuel 2 bottles 90g"), "iX", 7)
    assert "2 bottles" in row["answer"]
    assert row["answer"] == "#fuel 2 bottles 90g"
    assert "fuel" in row["tags"]


@pytest.mark.parametrize(
    "text", ["legs were heavy", "", "talking about #fuel mid-line 90g", "#fueling 90g"]
)
def test_no_tag(text):
    assert fuel_tag.parse(text) is None
    row = icu_comments.map_comment(comment(1, text), "iX", 7)
    assert row["tags"] == ["comment"]
    assert icu_comments.latest_tag([row]) is None


def test_decimal_comma_and_case():
    tag = fuel_tag.parse("#FUEL 1,5L 60G")
    assert tag is not None
    assert (tag.fluid_ml, tag.carbs_g) == (1500, 60)


def test_last_tag_line_in_one_comment_wins():
    tag = fuel_tag.parse("#fuel 60g\n#fuel 90g")
    assert tag is not None
    assert tag.carbs_g == 90


def test_later_tag_wins_across_comments():
    rows = [
        icu_comments.map_comment(comment(2, "#fuel 1l 120g", "2026-09-11T12:10:00Z"), "iX", 7),
        icu_comments.map_comment(
            comment(1, "#fuel 2l 240g 900kcal", "2026-09-11T12:00:00Z"), "iX", 7
        ),
    ]
    found = icu_comments.latest_tag(rows)
    assert found is not None
    tag, cid = found
    assert cid == "2"
    assert (tag.fluid_ml, tag.carbs_g, tag.kcal) == (1000, 120, None)


def test_deleted_and_system_comments_do_not_supply_intake():
    rows = [
        icu_comments.map_comment(comment(1, "#fuel 90g", "2026-09-11T12:00:00Z"), "iX", 7),
        icu_comments.map_comment(
            comment(2, "#fuel 300g", "2026-09-11T12:05:00Z", deleted=True), "iX", 7
        ),
        icu_comments.map_comment(
            comment(3, "[domestique]\n#fuel 10g", "2026-09-11T12:10:00Z"), "iX", 7
        ),
    ]
    found = icu_comments.latest_tag(rows)
    assert found is not None
    assert found[0].carbs_g == 90


# --- 2.3 reconcile -----------------------------------------------------------


def test_disagreement_keeps_tag_and_retains_platform_value():
    intake = icu_comments.reconcile(fuel_tag.Tag(carbs_g=90), "501", 60)
    assert intake.carbs_g == 90
    assert intake.platform_carbs_g == 60
    assert intake.carbs_differ is True


def test_agreement_is_not_flagged():
    intake = icu_comments.reconcile(fuel_tag.Tag(carbs_g=60), "501", 60.0)
    assert intake.carbs_differ is False


def test_tag_without_carbs_falls_back_to_platform():
    intake = icu_comments.reconcile(fuel_tag.Tag(fluid_ml=1500), "501", 60)
    assert intake.carbs_g == 60
    assert intake.fluid_ml == 1500
    assert intake.carbs_differ is False


def test_tag_without_platform_value():
    intake = icu_comments.reconcile(fuel_tag.Tag(carbs_g=90), "501", None)
    assert (intake.carbs_g, intake.platform_carbs_g, intake.carbs_differ) == (90, None, False)
