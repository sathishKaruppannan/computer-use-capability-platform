from capability_platform.access.models import InquiryRecord
from capability_platform.access.tracking import JSONInquiryTracker
from capability_platform.models import ServiceType


def test_record_get_roundtrip_preserves_client_inquiry_id(tmp_path):
    tracker = JSONInquiryTracker(tmp_path)
    record = InquiryRecord(
        inquiry_id="internal-123",
        client_inquiry_id="client-req-001",
        client_id="demo-client",
        service_type=ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP,
        system_identifier="legacy-member-servicing-demo",
        capability_id="lookup-member-savings-balance.v1",
        reused_existing_capability=True,
    )
    tracker.record(record)

    loaded = tracker.get("internal-123")
    assert loaded is not None
    assert loaded.client_inquiry_id == "client-req-001"
    assert loaded.client_id == "demo-client"
    assert loaded.reused_existing_capability is True


def test_get_returns_none_for_unknown_inquiry_id(tmp_path):
    tracker = JSONInquiryTracker(tmp_path)
    assert tracker.get("does-not-exist") is None
