from backend.adapters.hls_publisher import HlsPublisher


def packaged(tmp_path, count=5):
    source = tmp_path / "hls"
    source.mkdir()
    lines = ["#EXTM3U", "#EXT-X-PLAYLIST-TYPE:VOD", "#EXT-X-TARGETDURATION:2"]
    for i in range(count):
        (source / f"{i:05d}.ts").write_bytes(b"ts")
        lines += ["#EXTINF:2.000,", f"{i:05d}.ts"]
    (source / "match.m3u8").write_text("\n".join(lines + ["#EXT-X-ENDLIST"]) + "\n")
    return source


def test_only_elapsed_segments_exist_and_playlist_grows(tmp_path):
    publisher = HlsPublisher(packaged(tmp_path), tmp_path / "out")
    publisher.reset()
    publisher.publish(5.0)  # Segments 0-2 s and 2-4 s are complete; 4-6 s is not.
    served = sorted(p.name for p in (tmp_path / "out").glob("*.ts"))
    assert served == ["00000.ts", "00001.ts"]
    live = (tmp_path / "out" / "live.m3u8").read_text()
    assert "#EXT-X-PLAYLIST-TYPE:EVENT" in live and "00002.ts" not in live and "ENDLIST" not in live
    publisher.publish(10.0, finished=True)
    assert "#EXT-X-ENDLIST" in (tmp_path / "out" / "live.m3u8").read_text()
    publisher.reset()
    assert list((tmp_path / "out").glob("*.ts")) == []


def test_restart_resumes_the_published_prefix_and_never_serves_past_the_clock(tmp_path):
    out = tmp_path / "out"
    first = HlsPublisher(packaged(tmp_path), out)
    first.reset()
    first.publish(6.0)
    restarted = HlsPublisher(tmp_path / "hls", out)
    restarted.resume()
    assert restarted.published == 3 and (out / "00002.ts").exists()  # Open players keep footage.
    restarted.publish(3.0)  # The clock is behind the resumed prefix: withdraw the future.
    assert sorted(p.name for p in out.glob("*.ts")) == ["00000.ts"]
    (out / "live.m3u8").write_text("#EXTM3U\n#EXTINF:2.000,\nother.ts\n")
    restarted.resume()  # A different recording's playlist is wiped, not trusted.
    assert restarted.published == 0 and list(out.glob("*.ts")) == []


def test_replay_edge_is_the_published_playlist(tmp_path):
    from backend.adapters.hls_media import HlsMedia, parse_segments
    publisher = HlsPublisher(packaged(tmp_path), tmp_path / "out")
    publisher.reset()
    publisher.publish(5.0)
    media = HlsMedia(parse_segments((tmp_path / "hls" / "match.m3u8").read_text()), published_dir=tmp_path / "out")
    assert media.published_edge() == 4.0
    assert media.stream_url == "/media/hls/live.m3u8"
