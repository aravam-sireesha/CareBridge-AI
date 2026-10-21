"""Tests for the dependency-free service modules: CSV safety, bulk need validation, verification decisions."""
from datetime import date, datetime

import pytest

from app.services import bulk_needs, csvsafe, verification


# --------------------------------------------------------------------------- csv_safe
@pytest.mark.parametrize("payload", [
    "=1+1", "+SUM(A1:A9)", "-2+3", "@SUM(1,1)", "\t=1+1", "\r=1+1", "\n=1+1",
    "=HYPERLINK(\"http://evil\",\"x\")", "  =1+1", "\u00a0=1+1", "\u200b=1+1", "\ufeff=1+1",
])
def test_formula_payloads_are_neutralised(payload):
    out = csvsafe.csv_safe(payload)
    assert isinstance(out, str) and out.startswith("'"), payload
    assert out[1:] == payload


@pytest.mark.parametrize("text", ["Hope Home", "School supplies", "a=b", "x+y", "100% done", "naïve – café", "తిరుపతి", ""])
def test_ordinary_text_is_unchanged(text):
    assert csvsafe.csv_safe(text) == text


def test_numbers_dates_and_none():
    assert csvsafe.csv_safe(None) == ""
    assert csvsafe.csv_safe(-5) == -5
    assert csvsafe.csv_safe(-5.5) == -5.5
    assert csvsafe.csv_safe(float("nan")) == ""
    assert csvsafe.csv_safe(float("inf")) == ""
    assert csvsafe.csv_safe(True) == "yes"
    assert csvsafe.csv_safe(date(2026, 10, 17)) == "2026-10-17"
    assert csvsafe.csv_safe(datetime(2026, 10, 17, 9, 30, 5, 999)) == "2026-10-17 09:30:05"
    assert csvsafe.csv_safe(["a", "=b"]) == "a; =b"          # joined text is checked as a whole
    assert csvsafe.csv_safe(["=a", "b"]).startswith("'")


def test_report_has_metadata_and_escapes_everything():
    import csv, io
    text = csvsafe.build_report("Donations", datetime(2026, 10, 17, 8, 0, 0), {"status": "=evil()", "category": ""},
                                ["id", "name"], [[1, "=cmd|' /C calc'!A0"], [2, "Fine"], [3, "+1+1"], [4, "@SUM(A1)"]])
    assert text.startswith("\ufeff")
    cells = list(csv.reader(io.StringIO(text.lstrip("\ufeff"), newline="")))
    assert cells[0] == ["Report", "Donations"]
    assert cells[1] == ["Generated (UTC)", "2026-10-17 08:00:00"]
    assert cells[2] == ["Filters", "status==evil()"]          # empty filters are left out; the value cannot start a formula
    assert ["id", "name"] in cells and ["2", "Fine"] in cells
    assert ["1", "'=cmd|' /C calc'!A0"] in cells               # the payload is defused, not removed
    assert ["Rows", "4"] in cells
    # The real safety property: no cell in the whole file can start a formula.
    for row in cells:
        for cell in row:
            assert not cell.lstrip(" \u00a0").startswith(("=", "+", "-", "@", "\t", "\r")), cell


def test_a_formula_typed_into_a_filter_value_is_defused():
    import csv, io
    text = csvsafe.build_report("T", datetime(2026, 1, 1), {}, ["a"], [["=1+1"]], include_meta=True)
    assert ["'=1+1"] in list(csv.reader(io.StringIO(text.lstrip("\ufeff"), newline="")))


def test_report_without_metadata_is_plain():
    text = csvsafe.build_report("T", datetime(2026, 1, 1), {}, ["a"], [[1]], include_meta=False)
    assert text.lstrip("\ufeff") == "a\r\n1\r\n"


# --------------------------------------------------------------------------- bulk upload
def _parse(text):
    return bulk_needs.parse_csv(text)


def _validate(text, **kw):
    kw.setdefault("is_admin", False)
    kw.setdefault("own_org_id", 7)
    _, records, _ = _parse(text)
    return bulk_needs.validate(records, **kw)


HEAD = "title,category,quantity,urgency,description,required_by,location,beneficiaries,organization_id\n"


def test_template_round_trips_with_no_errors():
    res = _validate(bulk_needs.template_csv())
    assert [r.status for r in res] == ["valid", "valid", "valid"]
    assert res[0].data["org_id"] == 7 and res[0].data["urgency"] == "high" and res[0].data["quantity"] == 40
    assert res[2].data["required_by"] is None


def test_file_level_errors():
    with pytest.raises(bulk_needs.BulkError, match="empty"):
        _parse("   \n")
    with pytest.raises(bulk_needs.BulkError, match="no data rows"):
        _parse("category,quantity\n")
    with pytest.raises(bulk_needs.BulkError, match="Missing required"):
        _parse("title,urgency\nx,high\n")
    with pytest.raises(bulk_needs.BulkError, match="comma"):
        _parse("category;quantity\nFood;3\n")
    with pytest.raises(bulk_needs.BulkError, match="binary|text CSV"):
        _parse("category,quantity\nFood,\x003\n")
    with pytest.raises(bulk_needs.BulkError, match="same name"):
        _parse("category,quantity,qty\nFood,3,4\n")
    with pytest.raises(bulk_needs.BulkError, match="larger than"):
        _parse("category,quantity\n" + "Food,1\n" * 200_000)
    rows = "category,quantity\n" + "Food,1\n" * (bulk_needs.MAX_ROWS + 1)
    with pytest.raises(bulk_needs.BulkError, match="Too many rows"):
        _parse(rows)


def test_bom_aliases_and_ignored_columns():
    headers, records, info = _parse("\ufeffPriority,Category,QTY,Secret Column\nhigh,Food,3,zzz\n")
    assert headers[:3] == ["urgency", "category", "quantity"]
    assert info["ignored_columns"] == ["secret_column"]       # reported, not silently swallowed
    assert records[0].cells["urgency"] == "high"


def test_row_errors_are_specific_and_nothing_is_dropped():
    csv_text = HEAD + "\n".join([
        ",Food,10,high,,,,,",                  # ok
        ",,10,high,,,,,",                      # category missing
        ",Food,ten,high,,,,,",                 # quantity not a number
        ",Food,-3,high,,,,,",                  # negative -> not digits only
        ",Food,3,urgent,,,,,",                 # bad urgency
        ",Food,3,high,,31/12/2026,,,",         # non-ISO date
        ",Food,3,high,,2026-12-31,,abc,",      # beneficiaries not a number
        ",Food,99999999999,high,,,,,",         # integer overflow guarded
        ",Food,3,high,,,,200000,",             # beneficiaries too large
    ])
    res = _validate(csv_text)
    assert len(res) == 9
    assert res[0].status == "valid"
    assert all(r.status == "invalid" for r in res[1:])
    assert any("category is required" in e for e in res[1].errors)
    assert any("quantity must be a whole number" in e for e in res[2].errors)
    assert any("urgency must be one of" in e for e in res[4].errors)
    assert any("ISO date" in e for e in res[5].errors)
    assert any("between" in e for e in res[7].errors)
    assert [r.row for r in res] == list(range(1, 10))


def test_organization_cannot_write_for_another_organization():
    res = _validate(HEAD + ",Food,3,high,,,,,99\n", is_admin=False, own_org_id=7)
    assert res[0].status == "invalid"
    assert "own organization" in res[0].errors[0]
    own = _validate(HEAD + ",Food,3,high,,,,,7\n", is_admin=False, own_org_id=7)
    assert own[0].status == "valid" and own[0].data["org_id"] == 7
    unlinked = _validate(HEAD + ",Food,3,high,,,,,\n", is_admin=False, own_org_id=None)
    assert unlinked[0].status == "invalid"


def test_admin_needs_a_real_organization():
    base = HEAD + ",Food,3,high,,,,,\n"
    assert _validate(base, is_admin=True, own_org_id=None)[0].status == "invalid"
    assert _validate(base, is_admin=True, own_org_id=None, default_org_id=5, known_org_ids={5})[0].data["org_id"] == 5
    ghost = _validate(HEAD + ",Food,3,high,,,,,42\n", is_admin=True, own_org_id=None, known_org_ids={5})
    assert ghost[0].status == "invalid" and "does not exist" in ghost[0].errors[0]
    text_id = _validate(HEAD + ",Food,3,high,,,,,abc\n", is_admin=True, own_org_id=None, known_org_ids={5})
    assert text_id[0].status == "invalid"


def test_duplicates_inside_the_file_are_flagged_not_dropped():
    res = _validate(HEAD + "Rice,Food,3,high,,2026-12-01,,,\nrice,FOOD,9,low,,2026-12-01,,,\nRice,Food,3,high,,2026-12-02,,,\n")
    assert [r.status for r in res] == ["valid", "duplicate", "valid"]
    assert res[1].duplicate_of == 1


def test_extra_cells_and_control_characters():
    res = _validate(HEAD + ",Food,3,high,,,,,,unexpected\n")
    assert res[0].status == "invalid" and "more values" in res[0].errors[0]
    clean = _validate(HEAD + 'Ti\x07tle,Food,3,high,"Line1\r\nLine2",,,,\n')
    assert clean[0].data["title"] == "Title" and clean[0].data["description"] == "Line1\nLine2"


def test_dates_accept_iso_and_normalise_timezones():
    res = _validate(HEAD + ",Food,3,high,,2026-12-31T18:00:00+05:30,,,\n")
    assert res[0].data["required_by"] == datetime(2026, 12, 31, 12, 30)
    assert _validate(HEAD + ",Food,3,high,,1999-01-01,,,\n")[0].status == "invalid"


def test_text_that_looks_like_a_formula_is_stored_as_typed():
    """Escaping is applied when reports are exported (csv_safe), not by altering what an organization typed."""
    res = _validate(HEAD + "=1+1,Food,3,high,,,,,\n")
    assert res[0].status == "valid" and res[0].data["title"] == "=1+1"


# --------------------------------------------------------------------------- verification decisions
def test_approve_syncs_flag_and_status():
    out = verification.plan_decision("pending", False, "approve", None)
    assert out.new_status == "verified" and out.verified is True


def test_reject_and_request_info_require_a_reason():
    for decision in ("reject", "request_info"):
        for blank in (None, "", "   ", "\x00\x01"):
            with pytest.raises(verification.DecisionError) as err:
                verification.plan_decision("pending", False, decision, blank)
            assert err.value.status_code == 422
    out = verification.plan_decision("pending", False, "reject", "Registration number does not match.")
    assert out.new_status == "rejected" and out.verified is False and out.note.startswith("Registration")


def test_revoking_a_verified_organization_clears_the_flag():
    out = verification.plan_decision("verified", True, "reject", "Documents expired.")
    assert out.verified is False and out.new_status == "rejected"


def test_flag_wins_over_a_stale_status_string():
    """The old toggle endpoint set verified=True without touching verification_status."""
    assert verification.current_status("pending", True) == "verified"
    with pytest.raises(verification.DecisionError):
        verification.plan_decision("pending", True, "approve", None)    # already verified


def test_no_op_and_unknown_decisions_are_refused():
    with pytest.raises(verification.DecisionError):
        verification.plan_decision("under_review", False, "under_review", None)
    with pytest.raises(verification.DecisionError) as err:
        verification.plan_decision("pending", False, "delete_everything", None)
    assert err.value.status_code == 422


def test_note_is_trimmed_and_capped():
    out = verification.plan_decision("pending", False, "request_info", "x" * 5000)
    assert len(out.note) == verification.MAX_NOTE
    assert verification.current_status(None, None) == "pending"
    assert verification.current_status("nonsense", False) == "pending"


# --------------------------------------------------------------------------- paging / privacy / notification rules
from app.services import notify_rules, paging


def test_like_pattern_matches_wildcards_literally():
    assert paging.like_pattern("50%_off") == "%50\\%\\_off%"
    assert paging.like_pattern("a\\b") == "%a\\\\b%"
    assert paging.like_pattern(None) == "%%"
    assert len(paging.like_pattern("x" * 500)) == 102


def test_page_meta():
    assert paging.page_meta(1, 20, 0)["pages"] == 1
    assert paging.page_meta(2, 20, 41)["pages"] == 3
    assert paging.page_meta(1, 20, 40)["pages"] == 2


@pytest.mark.parametrize("age,band", [(None, "unknown"), (-1, "unknown"), (0, "0-5"), (5, "0-5"), (6, "6-11"), (11, "6-11"),
                                      (12, "12-14"), (14, "12-14"), (15, "15-17"), (17, "15-17"), (18, "18+"), (25, "18+")])
def test_age_group(age, band):
    assert paging.age_group(age) == band


@pytest.mark.parametrize("link", ["javascript:alert(1)", "//evil.com/x", "https://evil.com", "data:text/html,x", "/ok\\..\\x", "/a\nb", "", None, "  "])
def test_unsafe_notification_links_are_dropped(link):
    assert notify_rules.safe_link(link) is None


def test_safe_links_pass():
    assert notify_rules.safe_link("/donations") == "/donations"
    assert notify_rules.safe_link(" /admin/verification?status=pending ") == "/admin/verification?status=pending"


def test_security_notifications_cannot_be_disabled():
    off = {"in_app": False, "verification": False}
    assert notify_rules.wants_in_app(off, "security") is True
    assert notify_rules.wants_in_app(off, "donation") is False
    assert notify_rules.wants_in_app({"donation": False}, "donation") is False
    assert notify_rules.wants_in_app({"donation": False}, "need") is True
    assert notify_rules.wants_in_app(None, "verification") is True


def test_merge_prefs_validates():
    merged = notify_rules.merge_prefs({"in_app": False, "junk": 1}, {"donation": False})
    assert merged["in_app"] is False and merged["donation"] is False and "junk" not in merged
    with pytest.raises(ValueError, match="Unknown"):
        notify_rules.merge_prefs(None, {"security": False})       # security is not a switch
    with pytest.raises(ValueError, match="true or false"):
        notify_rules.merge_prefs(None, {"in_app": "no"})
