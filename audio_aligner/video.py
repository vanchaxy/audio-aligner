import io
from fractions import Fraction

import av
import click
import librosa
import numpy as np

AV_TIME_BASE_Q = 1000000

DEFAULT_FPS = Fraction(24000, 1001)


def get_video_fps(video_path: str) -> Fraction:
    with av.open(video_path, 'r') as container:
        if container.streams.video:
            s = container.streams.video[0]
        else:
            return DEFAULT_FPS
    if s.average_rate and s.average_rate.denominator != 0:
        return s.average_rate
    if s.guessed_rate and s.guessed_rate.denominator != 0:
        return s.guessed_rate
    if s.codec_context and s.codec_context.framerate and s.codec_context.framerate.denominator != 0:
        return s.codec_context.framerate
    return DEFAULT_FPS


def load_audio_track(
    video_path: str,
    audio_track: int,
    sample_rate: int,
    max_duration: int,
    target_fps: Fraction,
) -> np.ndarray:
    input_container = av.open(video_path, 'r')

    input_fps = get_video_fps(video_path)
    audio_speed_factor = float(target_fps / input_fps)

    input_audio_stream = input_container.streams.audio[audio_track]

    title = input_audio_stream.metadata.get('title')
    language = input_audio_stream.metadata.get('language')
    loading_text = 'Loading audio track number'
    if title:
        loading_text += f' {title}'
    if language:
        loading_text += f' ({language})'
    loading_text += f' from {audio_track}:{video_path}'
    click.echo(loading_text)

    if audio_speed_factor != 1.0:
        # TODO
        click.echo(
            click.style(
                f'FPS mismatch detected! Speed factor: {audio_speed_factor:.2f}',
                fg='yellow',
            ),
        )

    if (
        input_audio_stream.duration is not None
        and input_audio_stream.time_base is not None
        and input_audio_stream.time_base != 0
    ):
        stream_duration_seconds = int(
            input_audio_stream.duration * input_audio_stream.time_base,
        )
    else:
        stream_duration_seconds = int(input_container.duration / AV_TIME_BASE_Q)

    if not max_duration or max_duration > stream_duration_seconds:
        max_duration = stream_duration_seconds

    output_codec = 'pcm_s16le'
    output_layout = 'mono'
    output_format = 's16'

    wav_buffer = io.BytesIO()

    output_container = None
    try:
        output_container = av.open(wav_buffer, mode='w', format='wav')

        output_audio_stream = output_container.add_stream(
            output_codec,
            rate=sample_rate,
            layout=output_layout,
        )

        resampler = av.AudioResampler(
            format=output_format,
            layout=output_layout,
            rate=sample_rate,
        )

        with click.progressbar(length=max_duration, label='Converting audio to WAV') as bar:
            bar.update(0, current_item=0)
            for frame in input_container.decode(input_audio_stream):
                resampled_frames = resampler.resample(frame)
                for resampled_frame in resampled_frames:
                    for packet in output_audio_stream.encode(resampled_frame):
                        output_container.mux(packet)

                current_frame_time = float(frame.pts * input_audio_stream.time_base)
                bar.update(
                    current_frame_time - bar.current_item,
                    current_item=current_frame_time,
                )
                if max_duration and current_frame_time > max_duration:
                    bar.update(max_duration)
                    break

        resampled_frames = resampler.resample(None)
        for resampled_frame in resampled_frames:
            for packet in output_audio_stream.encode(resampled_frame):
                output_container.mux(packet)

        for packet in output_audio_stream.encode():
            output_container.mux(packet)

        wav_buffer.seek(0)
        y, _ = librosa.load(wav_buffer, sr=None)

        return y

    finally:
        input_container.close()
        if output_container:
            output_container.close()
        wav_buffer.close()
