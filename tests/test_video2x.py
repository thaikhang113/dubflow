from autodub.media.video2x import build_video2x_command, run_video2x_or_fallback


def test_build_video2x_command_uses_external_binary():
    assert build_video2x_command(
        "video2x", "in.mp4", "out.mp4", profile="realesrgan",
        scale=4, model="realesr-animevideov3"
    ) == [
        "video2x", "-i", "in.mp4", "-o", "out.mp4",
        "-p", "realesrgan", "-s", "4",
        "--realesrgan-model", "realesr-animevideov3",
    ]


def test_video2x_failure_returns_ffmpeg_output(tmp_path):
    source = tmp_path / "dubbed.mp4"
    source.write_bytes(b"ffmpeg")
    output = tmp_path / "upscaled.mp4"

    result = run_video2x_or_fallback(
        str(source), str(output),
        command=["video2x"],
        run_command=lambda _command: (_ for _ in ()).throw(
            RuntimeError("video2x failed")),
    )

    assert result.output_path == str(source)
    assert not output.exists()
    assert result.used_video2x is False
    assert "video2x failed" in result.error
