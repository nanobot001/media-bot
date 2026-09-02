from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


PATCH_PATH = Path("docker/mediaflow-audio-stereo/patch_mediaflow_audio.py")
SPEC = spec_from_file_location("mediaflow_audio_stereo_patch", PATCH_PATH)
PATCH_MODULE = module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PATCH_MODULE)


def _write_vendor_fixture(root: Path) -> None:
    package = root / "mediaflow_proxy"
    (package / "routes").mkdir(parents=True)
    (package / "remuxer").mkdir(parents=True)
    (package / "main.py").write_text(
        'async def health_check():\n    return {"status": "healthy"}\n',
        encoding="utf-8",
    )
    (package / "routes" / "proxy.py").write_text(
        '''    start: float | None = Query(None, description="Seek start time in seconds (used with transcode=true)"),
):
        return await handle_transcode(request, source, start_time=start)
async def transcode_hls_playlist(
    request: Request,
    proxy_headers: Annotated[ProxyRequestHeaders, Depends(get_proxy_headers)],
    destination: str = Query(..., description="The URL of the source media.", alias="d"),
):
    pass
    if "api_password" in original:
        params.append(f"api_password={quote(original['api_password'], safe='')}")
    # Preserve header overrides (h_referer, h_origin, etc.)
    seg: int | None = Query(None, description="Segment number (informational, for logging)."),
):
    return await handle_transcode_hls_segment(
        request, source, start_time_ms=start_ms, end_time_ms=end_ms, segment_number=seg
    )
''',
        encoding="utf-8",
    )
    (package / "remuxer" / "transcode_handler.py").write_text(
        '''    start_time: float | None = None,
) -> Response:
    use_mkv_fast_path = cue_index is not None and not needs_video_transcode
    estimated_size = None
            if stream_offset > 0 and cue_index.seek_header:
                seek_header = cue_index.seek_header

            logger.info(
            if byte_offset > 0:
                stream_offset = byte_offset
                logger.info(
    if use_mkv_fast_path:
        content = stream_transcode_fmp4(media_source_gen())
    else:
        content = stream_transcode_universal(media_source_gen())
    segment_number: int | None = None,
) -> Response:
    """
    Serve a single HLS fMP4 media segment (moof + mdat).
                force_software_encode=True,
            ):
                seg_chunks.append(chunk)
''',
        encoding="utf-8",
    )
    (package / "remuxer" / "transcode_pipeline.py").write_text(
        '''    force_software_encode: bool = False,
) -> AsyncIterator[bytes]:
            duration_ms=vs.duration_seconds * 1000.0
            if vs and vs.duration_seconds and 0 < vs.duration_seconds < 86400
            else 0.0,
            do_audio_transcode = pyav_audio_needs_transcode(aus.codec_name) or pyav_audio_needs_transcode(
                audio_mkv_codec
            )
            if vs and packet.stream_index == vs.index and packet.codec_type == "video":
                pass
''',
        encoding="utf-8",
    )


def test_pinned_mediaflow_patch_is_exact_and_channel_aware(tmp_path):
    _write_vendor_fixture(tmp_path)

    PATCH_MODULE.apply_patch(tmp_path)

    main = (tmp_path / "mediaflow_proxy" / "main.py").read_text(encoding="utf-8")
    proxy = (tmp_path / "mediaflow_proxy" / "routes" / "proxy.py").read_text(encoding="utf-8")
    handler = (tmp_path / "mediaflow_proxy" / "remuxer" / "transcode_handler.py").read_text(encoding="utf-8")
    pipeline = (tmp_path / "mediaflow_proxy" / "remuxer" / "transcode_pipeline.py").read_text(encoding="utf-8")

    assert '"force_audio_stereo": True' in main
    assert '"segmented_hls": True' in main
    assert '"hls_force_audio_stereo": True' in main
    assert "force_audio_stereo: bool" in proxy
    assert "force_audio_stereo=force_audio_stereo" in proxy
    assert "Force AAC stereo HLS output" in proxy
    assert 'original.get("force_audio_stereo") == "true"' in proxy
    assert "force_audio_stereo: bool" in handler
    assert "and not force_audio_stereo" in handler
    assert "and not (start_time is not None and start_time > 0)" in handler
    assert "stream_transcode_universal(" in handler
    assert "force_audio_stereo=force_audio_stereo" in handler
    assert "duration_ms=(duration_seconds * 1000.0 if duration_seconds is not None else None)" in handler
    assert "start_decode_time_ms=(start_time or 0.0) * 1000.0" in handler
    assert "skip_before_time_ms=(start_time or 0.0) * 1000.0" in handler
    assert "seek_duration_ms=(duration_seconds - (start_time or 0.0)) * 1000.0" in handler
    assert "force_audio_stereo: bool" in pipeline
    assert "duration_ms: float | None = None" in pipeline
    assert "seek_duration_ms: float | None = None" in pipeline
    assert "skip_before_time_ms: float = 0.0" in pipeline
    assert "force_audio_stereo and (aus.channels or 0) > 2" in pipeline
    assert "packet_time_ms = (packet.pts_seconds or 0.0) * 1000.0" in pipeline
    assert "skip_before_time_ms > 0 and packet_time_ms < skip_before_time_ms" in pipeline
    assert "if duration_ms is not None" in pipeline

    with pytest.raises(RuntimeError):
        PATCH_MODULE.apply_patch(tmp_path)
