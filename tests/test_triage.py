from insta360 import triage


def _touch(path, size=1024):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)


def test_pairs_master_with_proxy(tmp_path):
    _touch(tmp_path / "VID_20260227_142557_00_005.insv", 4096)
    _touch(tmp_path / "LRV_20260227_142557_01_005.lrv", 512)

    report = triage.scan(tmp_path)

    assert len(report.clips) == 1
    assert report.clips[0].status == triage.PAIRED
    assert report.redundant_bytes == 512
    assert report.at_risk_bytes == 0


def test_proxy_without_master_is_an_orphan(tmp_path):
    _touch(tmp_path / "LRV_20260228_112240_01_006.lrv", 2048)

    report = triage.scan(tmp_path)

    assert report.clips[0].status == triage.ORPHAN_PROXY
    assert report.at_risk_bytes == 2048
    assert report.redundant_bytes == 0


def test_master_without_proxy_is_not_at_risk(tmp_path):
    _touch(tmp_path / "VID_20260227_142557_00_005.insv", 4096)

    report = triage.scan(tmp_path)

    assert report.clips[0].status == triage.MASTER_ONLY
    assert report.at_risk_bytes == 0


def test_same_sequence_in_different_folders_does_not_pair(tmp_path):
    """Sequence numbers restart, so a clip key must include its directory."""
    _touch(tmp_path / "trip-a" / "VID_20260227_142557_00_005.insv")
    _touch(tmp_path / "trip-b" / "LRV_20260320_094114_01_005.lrv")

    report = triage.scan(tmp_path)

    assert len(report.clips) == 2
    assert {clip.status for clip in report.clips} == {triage.MASTER_ONLY, triage.ORPHAN_PROXY}


def test_photos_are_listed_separately(tmp_path):
    _touch(tmp_path / "IMG_20260314_090809_00_007.insp")

    report = triage.scan(tmp_path)

    assert not report.clips
    assert len(report.photos) == 1


def test_unexpected_names_are_reported_not_silently_dropped(tmp_path):
    _touch(tmp_path / "holiday.insv")
    _touch(tmp_path / "notes.txt")

    report = triage.scan(tmp_path)

    assert [p.name for p in report.unmatched] == ["holiday.insv"]
