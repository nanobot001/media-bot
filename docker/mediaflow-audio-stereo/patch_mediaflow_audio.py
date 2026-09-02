"""Apply bounded audio and timeline-metadata adaptations to the pinned MediaFlow image."""

from __future__ import annotations

from pathlib import Path


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one patch point in {path}, found {count}.")
    path.write_text(text.replace(old, new), encoding="utf-8")


def apply_patch(root: Path = Path("/mediaflow_proxy")) -> None:
    package = root / "mediaflow_proxy"

    _replace_once(
        package / "main.py",
        '    return {"status": "healthy"}\n',
        '    return {"status": "healthy", "capabilities": {\n'
        '        "force_audio_stereo": True,\n'
        '        "segmented_hls": True,\n'
        '        "hls_force_audio_stereo": True,\n'
        '    }}\n',
    )

    proxy = package / "routes" / "proxy.py"
    _replace_once(
        proxy,
        '    start: float | None = Query(None, description="Seek start time in seconds (used with transcode=true)"),\n):',
        '    start: float | None = Query(None, description="Seek start time in seconds (used with transcode=true)"),\n'
        '    force_audio_stereo: bool = Query(\n'
        '        False, description="Force audio transcoding to AAC stereo when source has more than two channels"\n'
        '    ),\n):',
    )
    _replace_once(
        proxy,
        '        return await handle_transcode(request, source, start_time=start)\n',
        '        return await handle_transcode(\n'
        '            request, source, start_time=start, force_audio_stereo=force_audio_stereo\n'
        '        )\n',
    )
    _replace_once(
        proxy,
        'async def transcode_hls_playlist(\n'
        '    request: Request,\n'
        '    proxy_headers: Annotated[ProxyRequestHeaders, Depends(get_proxy_headers)],\n'
        '    destination: str = Query(..., description="The URL of the source media.", alias="d"),\n'
        '):',
        'async def transcode_hls_playlist(\n'
        '    request: Request,\n'
        '    proxy_headers: Annotated[ProxyRequestHeaders, Depends(get_proxy_headers)],\n'
        '    destination: str = Query(..., description="The URL of the source media.", alias="d"),\n'
        '    force_audio_stereo: bool = Query(False, description="Force AAC stereo HLS output."),\n'
        '):',
    )
    _replace_once(
        proxy,
        '    if "api_password" in original:\n'
        '        params.append(f"api_password={quote(original[\'api_password\'], safe=\'\')}")\n'
        '    # Preserve header overrides (h_referer, h_origin, etc.)\n',
        '    if "api_password" in original:\n'
        '        params.append(f"api_password={quote(original[\'api_password\'], safe=\'\')}")\n'
        '    if original.get("force_audio_stereo") == "true":\n'
        '        params.append("force_audio_stereo=true")\n'
        '    # Preserve header overrides (h_referer, h_origin, etc.)\n',
    )
    _replace_once(
        proxy,
        '    seg: int | None = Query(None, description="Segment number (informational, for logging)."),\n'
        '):',
        '    seg: int | None = Query(None, description="Segment number (informational, for logging)."),\n'
        '    force_audio_stereo: bool = Query(False, description="Force AAC stereo output."),\n'
        '):',
    )
    _replace_once(
        proxy,
        '    return await handle_transcode_hls_segment(\n'
        '        request, source, start_time_ms=start_ms, end_time_ms=end_ms, segment_number=seg\n'
        '    )\n',
        '    return await handle_transcode_hls_segment(\n'
        '        request,\n'
        '        source,\n'
        '        start_time_ms=start_ms,\n'
        '        end_time_ms=end_ms,\n'
        '        segment_number=seg,\n'
        '        force_audio_stereo=force_audio_stereo,\n'
        '    )\n',
    )

    handler = package / "remuxer" / "transcode_handler.py"
    _replace_once(
        handler,
        '    start_time: float | None = None,\n) -> Response:',
        '    start_time: float | None = None,\n'
        '    force_audio_stereo: bool = False,\n) -> Response:',
    )
    _replace_once(
        handler,
        '    use_mkv_fast_path = cue_index is not None and not needs_video_transcode\n',
        '    use_mkv_fast_path = (\n'
        '        cue_index is not None\n'
        '        and not needs_video_transcode\n'
        '        and not force_audio_stereo\n'
        '        and not (start_time is not None and start_time > 0)\n'
        '    )\n',
    )
    _replace_once(
        handler,
        '        content = stream_transcode_universal(media_source_gen())\n',
        '        content = stream_transcode_universal(\n'
        '            media_source_gen(),\n'
        '            force_audio_stereo=force_audio_stereo,\n'
        '            duration_ms=(duration_seconds * 1000.0 if duration_seconds is not None else None),\n'
        '            start_decode_time_ms=(start_time or 0.0) * 1000.0,\n'
        '            skip_before_time_ms=(start_time or 0.0) * 1000.0,\n'
        '            seek_duration_ms=(duration_seconds - (start_time or 0.0)) * 1000.0\n'
        '            if duration_seconds is not None and start_time is not None and start_time > 0\n'
        '            else None,\n'
        '        )\n',
    )
    _replace_once(
        handler,
        '    segment_number: int | None = None,\n'
        ') -> Response:\n'
        '    """\n'
        '    Serve a single HLS fMP4 media segment (moof + mdat).\n',
        '    segment_number: int | None = None,\n'
        '    force_audio_stereo: bool = False,\n'
        ') -> Response:\n'
        '    """\n'
        '    Serve a single HLS fMP4 media segment (moof + mdat).\n',
    )
    _replace_once(
        handler,
        '                force_software_encode=True,\n'
        '            ):\n'
        '                seg_chunks.append(chunk)\n',
        '                force_software_encode=True,\n'
        '                force_audio_stereo=force_audio_stereo,\n'
        '            ):\n'
        '                seg_chunks.append(chunk)\n',
    )

    pipeline = package / "remuxer" / "transcode_pipeline.py"
    _replace_once(
        pipeline,
        '    force_software_encode: bool = False,\n) -> AsyncIterator[bytes]:',
        '    force_software_encode: bool = False,\n'
        '    force_audio_stereo: bool = False,\n'
        '    duration_ms: float | None = None,\n'
        '    seek_duration_ms: float | None = None,\n'
        '    skip_before_time_ms: float = 0.0,\n) -> AsyncIterator[bytes]:',
    )
    _replace_once(
        pipeline,
        '            do_audio_transcode = pyav_audio_needs_transcode(aus.codec_name) or pyav_audio_needs_transcode(\n'
        '                audio_mkv_codec\n'
        '            )\n',
        '            do_audio_transcode = (\n'
        '                pyav_audio_needs_transcode(aus.codec_name)\n'
        '                or pyav_audio_needs_transcode(audio_mkv_codec)\n'
        '                or (force_audio_stereo and (aus.channels or 0) > 2)\n'
        '            )\n',
    )
    _replace_once(
        pipeline,
        '            duration_ms=vs.duration_seconds * 1000.0\n'
        '            if vs and vs.duration_seconds and 0 < vs.duration_seconds < 86400\n'
        '            else 0.0,\n',
        '            duration_ms=(\n'
        '                seek_duration_ms\n'
        '                if seek_duration_ms is not None\n'
        '                else (\n'
        '                    duration_ms\n'
        '                    if duration_ms is not None\n'
        '                    else (\n'
        '                        vs.duration_seconds * 1000.0\n'
        '                        if vs and vs.duration_seconds and 0 < vs.duration_seconds < 86400\n'
        '                        else 0.0\n'
        '                    )\n'
        '                )\n'
        '            ),\n',
    )
    _replace_once(
        pipeline,
        '            if vs and packet.stream_index == vs.index and packet.codec_type == "video":\n',
        '            packet_time_ms = (packet.pts_seconds or 0.0) * 1000.0\n'
        '            if skip_before_time_ms > 0 and packet_time_ms < skip_before_time_ms:\n'
        '                return None, None\n\n'
        '            if vs and packet.stream_index == vs.index and packet.codec_type == "video":\n',
    )


if __name__ == "__main__":
    apply_patch()
