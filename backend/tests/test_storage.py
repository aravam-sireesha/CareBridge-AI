"""Private storage: nothing from the client is trusted. Magic-byte typing, active-content PDFs, random keys, forced-download signed URLs."""
import pytest

from app.services import storage as st
from app.services.storage import UploadError

PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 20
LIMIT = 1024 * 1024


@pytest.mark.parametrize("data,ctype", [(PDF, "application/pdf"), (PNG, "image/png"), (JPG, "image/jpeg"), (WEBP, "image/webp")])
def test_each_allowed_type_is_recognised_from_its_bytes_not_its_name(data, ctype):
    assert st.sniff(data) == ctype
    assert st.validate_upload("whatever.exe", ctype, data, LIMIT)[0] == ctype


@pytest.mark.parametrize("data", [b"MZ\x90\x00 an executable", b"<html><script>alert(1)</script></html>", b"GIF89a....", b"PK\x03\x04 a zip", b"#!/bin/sh\nrm -rf /", b"<svg onload=alert(1)>", b"x" * 100])
def test_everything_else_is_refused(data):
    with pytest.raises(UploadError):
        st.validate_upload("a.pdf", "application/pdf", data, LIMIT)


def test_the_declared_type_must_match_the_real_one():
    for declared in ("image/png", "application/pdf", "text/html", "", None):
        with pytest.raises(UploadError, match="does not match"):
            st.validate_upload("a.jpg", declared, JPG if declared != "image/png" else PDF, LIMIT)
    assert st.validate_upload("a.png", "IMAGE/PNG; charset=binary", PNG, LIMIT)[0] == "image/png"      # case and parameters are tolerated


def test_a_script_pretending_to_be_a_pdf_by_extension_is_still_refused():
    with pytest.raises(UploadError):
        st.validate_upload("invoice.pdf", "application/pdf", b"<script>steal()</script>", LIMIT)


@pytest.mark.parametrize("marker", [b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/OpenAction", b"/RichMedia", b"/XFA"])
def test_pdfs_with_active_content_are_refused(marker):
    with pytest.raises(UploadError, match="active content"):
        st.validate_upload("a.pdf", "application/pdf", PDF + b"\n<< " + marker + b" (app.alert(1)) >>", LIMIT)


def test_size_and_emptiness_are_enforced():
    with pytest.raises(UploadError, match="empty"):
        st.validate_upload("a.pdf", "application/pdf", b"", LIMIT)
    with pytest.raises(UploadError, match="too large"):
        st.validate_upload("a.pdf", "application/pdf", PDF + b"0" * LIMIT, LIMIT)
    st.validate_upload("a.pdf", "application/pdf", PDF + b"0" * (LIMIT - len(PDF)), LIMIT)           # exactly at the limit is fine
    for bad in (None, "text", 123):
        with pytest.raises(UploadError):
            st.validate_upload("a.pdf", "application/pdf", bad, LIMIT)


@pytest.mark.parametrize("raw,expected", [("../../etc/passwd", "passwd"), ("C:\\Users\\me\\scan.pdf", "scan.pdf"), ("a\x00b\r\n.pdf", "ab.pdf"), ("..", "document"), ("", "document"),
                                          (None, "document"), ("<script>.pdf", "script.pdf"), ("x" * 300 + ".pdf", "x" * 100)])
def test_file_names_are_reduced_to_something_harmless(raw, expected):
    assert st.safe_filename(raw) == expected


def test_object_keys_are_random_and_never_contain_the_file_name():
    a = st.object_key("organization", 7, "darpan", "application/pdf"); b = st.object_key("organization", 7, "darpan", "application/pdf")
    assert a != b and a.startswith("organization/7/darpan/") and a.endswith(".pdf") and ".." not in a
    assert len(a.rsplit("/", 1)[1]) == 32 + len(".pdf")


def test_every_owner_type_has_an_allow_list_of_kinds():
    assert "police_verification" in st.KINDS["volunteer"] and "police_verification" not in st.KINDS["organization"]
    assert st.KINDS["delivery"] == {"delivery_proof"}


def test_limits_come_from_the_environment_but_are_clamped():
    assert st.max_bytes({}) == 5 * 1024 * 1024 and st.max_bytes({"UPLOAD_MAX_MB": "2"}) == 2 * 1024 * 1024
    assert st.max_bytes({"UPLOAD_MAX_MB": "9999"}) == 20 * 1024 * 1024 and st.max_bytes({"UPLOAD_MAX_MB": "x"}) == 5 * 1024 * 1024 and st.max_bytes({"UPLOAD_MAX_MB": "0"}) == int(0.1 * 1024 * 1024)
    assert st.signed_url_seconds({}) == 300 and st.signed_url_seconds({"S3_SIGNED_URL_SECONDS": "86400"}) == 900 and st.signed_url_seconds({"S3_SIGNED_URL_SECONDS": "1"}) == 30


class FakeS3:
    def __init__(self, fail=False):
        self.puts, self.urls, self.deletes, self.fail = [], [], [], fail

    def put_object(self, **kw):
        if self.fail: raise ConnectionError("https://bucket/secret-key")
        self.puts.append(kw)

    def generate_presigned_url(self, op, Params, ExpiresIn):
        if self.fail: raise ConnectionError("x")
        self.urls.append((op, Params, ExpiresIn)); return f"https://signed.example/{Params['Key']}?X-Amz-Expires={ExpiresIn}"

    def delete_object(self, **kw): self.deletes.append(kw)


ENV = {"S3_BUCKET": "cb-private", "S3_ACCESS_KEY": "AK", "S3_SECRET_KEY": "SK"}


def test_storage_is_only_configured_with_bucket_and_both_keys():
    assert st.configured(ENV) and not st.configured({}) and not st.configured({**ENV, "S3_SECRET_KEY": " "}) and st.get_storage({}) is None


def test_uploads_are_forced_to_download_and_signed_urls_are_short_lived_attachments():
    fake = FakeS3(); s = st.S3Storage(ENV, client=fake)
    s.put("organization/1/darpan/abc.pdf", PDF, "application/pdf")
    assert fake.puts[0]["ContentDisposition"] == "attachment" and fake.puts[0]["Bucket"] == "cb-private" and fake.puts[0]["ContentType"] == "application/pdf"
    url = s.signed_url("organization/1/darpan/abc.pdf", 99999, 'evil"; name.pdf')
    op, params, expires = fake.urls[0]
    assert op == "get_object" and expires == 900                                                  # clamped to 15 minutes
    assert params["ResponseContentDisposition"] == 'attachment; filename="evil name.pdf"' and "evil\"" not in params["ResponseContentDisposition"]
    assert expires <= 900 and "signed.example" in url
    assert fake.urls and s.signed_url("k", 1, "a.pdf") and fake.urls[1][2] == 30


def test_storage_errors_never_leak_endpoints_or_keys():
    s = st.S3Storage(ENV, client=FakeS3(fail=True))
    for call in (lambda: s.put("k", PDF, "application/pdf"), lambda: s.signed_url("k", 60, "a.pdf")):
        with pytest.raises(st.StorageUnavailable) as e:
            call()
        assert "secret-key" not in str(e.value) and str(e.value) == "ConnectionError"
    assert "SK" not in repr(s) and "AK" not in repr(s)


def test_delete_goes_to_the_right_object():
    fake = FakeS3(); st.S3Storage(ENV, client=fake).delete("a/b.pdf")
    assert fake.deletes == [{"Bucket": "cb-private", "Key": "a/b.pdf"}]
