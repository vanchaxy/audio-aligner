import ctypes
import multiprocessing
import sys
from typing import TYPE_CHECKING

import click
import numpy as np

from audio_aligner.processing import get_chunks, process_single_chunk, share_arrays
from audio_aligner.video import get_video_fps, load_audio_track

if TYPE_CHECKING:
    from multiprocessing.sharedctypes import SynchronizedArray


def validate_positive_integer(ctx: click.Context, param: dict, value: int) -> int:
    if value < 1:
        raise click.BadParameter('Should be a positive integer.')
    return value


def validate_non_negative_integer(ctx: click.Context, param: dict, value: int) -> int:
    if value < 0:
        raise click.BadParameter('Should be a non-negative integer.')
    return value


@click.command(context_settings={'help_option_names': ['-h', '--help']})
@click.argument('reference_video', type=click.Path(exists=True, dir_okay=False))
@click.argument('secondary_video', type=click.Path(exists=True, dir_okay=False))
@click.option(
    '-ra',
    '--ref-audio-track',
    'ref_audio_track',
    type=int,
    default=0,
    show_default=True,
    help='Audio track number (0-indexed) from the reference video.',
)
@click.option(
    '-sa',
    '--sec-audio-track',
    'sec_audio_track',
    type=int,
    default=0,
    show_default=True,
    help='Audio track number (0-indexed) from the secondary video.',
)
@click.option(
    '-m',
    '--method',
    type=click.Choice(['rms', 'onset'], case_sensitive=False),
    default='onset',
    show_default=True,
    help='Algorithm for feature extraction and comparison.',
)
@click.option(
    '-md',
    '--max-duration',
    'max_duration',
    type=int,
    default=0,
    show_default=True,
    callback=validate_non_negative_integer,
    help='Maximum duration (seconds) from the start of each video to process. 0 for full length.',
)
@click.option(
    '-cd',
    '--chunk-duration',
    'chunk_duration',
    type=float,
    default=300,
    show_default=True,
    callback=validate_positive_integer,
    help='Duration (seconds) of audio chunks for parallel processing.',
)
@click.option(
    '-sr',
    '--sample-rate',
    'sample_rate',
    type=int,
    default=48000,
    show_default=True,
    help='Target sampling rate (Hz) for audio processing.',
)
@click.option(
    '-n',
    '--num-workers',
    'num_workers',
    type=int,
    default=1,
    show_default=True,
    callback=validate_positive_integer,
    help='Number of parallel worker processes.',
)
def align_audio_cli(
    reference_video: str,
    secondary_video: str,
    ref_audio_track: int,
    sec_audio_track: int,
    method: str,
    max_duration: int,
    chunk_duration: int,
    sample_rate: int,
    num_workers: int,
) -> None:
    target_fps = get_video_fps(reference_video)
    frame_duration = float(1000 / target_fps)

    reference_y = load_audio_track(
        reference_video,
        ref_audio_track,
        sample_rate,
        max_duration,
        target_fps=target_fps,
    )
    secondary_y = load_audio_track(
        secondary_video,
        sec_audio_track,
        sample_rate,
        max_duration,
        target_fps=target_fps,
    )

    chunk_tasks = get_chunks(reference_y, secondary_y, chunk_duration, sample_rate)
    if not chunk_tasks:
        click.echo(
            click.style(
                'Error: No processable audio chunks found. Check durations.',
                fg='red',
            ),
            err=True,
        )
        raise click.Abort

    shared_ref: np.ndarray | SynchronizedArray
    shared_sec: np.ndarray | SynchronizedArray

    if num_workers > 1:
        shared_ref = multiprocessing.Array(ctypes.c_float, reference_y.size)
        shared_sec = multiprocessing.Array(ctypes.c_float, secondary_y.size)

        np.copyto(np.frombuffer(shared_ref.get_obj(), dtype=np.float32), reference_y)
        np.copyto(np.frombuffer(shared_sec.get_obj(), dtype=np.float32), secondary_y)
    else:
        shared_ref = reference_y
        shared_sec = secondary_y

    share_arrays(shared_ref, shared_sec)

    worker_args = [(sample_rate, method, task_info) for task_info in chunk_tasks]

    chunk_delays_results = []
    bar_label = (
        f'Processing {len(chunk_tasks)} chunks ({min(num_workers, len(chunk_tasks))} workers)'
    )
    with click.progressbar(
        length=len(chunk_tasks),
        label=bar_label,
    ) as bar:
        if num_workers > 1:
            with multiprocessing.Pool(processes=min(num_workers, len(chunk_tasks))) as pool:
                result_iterator = pool.imap_unordered(process_single_chunk, worker_args)
                for result in result_iterator:
                    chunk_delays_results.append(result)
                    bar.update(1)
        else:
            for worker_arg in worker_args:
                result = process_single_chunk(worker_arg)
                chunk_delays_results.append(result)
                bar.update(1)

    valid_delays = [d for d in chunk_delays_results if d is not None]
    if not valid_delays:
        click.echo(
            click.style('Error: No valid delays calculated from any chunk.', fg='red'),
            err=True,
        )
        raise click.Abort

    print_results(valid_delays, chunk_duration, frame_duration)


def print_results(
    valid_delays: list[tuple[int, int]],
    chunk_duration: int,
    frame_duration: float,
) -> None:
    valid_delays.sort()
    click.echo(click.style('Delays per chunk:', fg='green'))
    for i, delay in valid_delays:
        chunk_start_time = int(i * chunk_duration)
        hours = chunk_start_time // 3600
        minutes = (chunk_start_time % 3600) // 60
        secs = chunk_start_time % 60

        click.echo(
            click.style(
                f'[{hours:02}:{minutes:02}:{secs:02}] {delay}ms',
                fg='red' if abs(delay) > frame_duration else 'green',
            ),
        )

    integers_delays = [d[1] for d in valid_delays]
    mode_delay = max(set(integers_delays), key=integers_delays.count)
    average_delay = int(sum(integers_delays) / len(integers_delays))
    max_delay = max(integers_delays, key=lambda d: abs(d))
    min_delay = min(integers_delays, key=lambda d: abs(d))
    click.echo(
        click.style(
            f'Mode delay: {mode_delay}ms',
            fg='red' if abs(mode_delay) > frame_duration else 'green',
        ),
    )
    click.echo(
        click.style(
            f'Average delay: {average_delay}ms',
            fg='red' if abs(average_delay) > frame_duration else 'green',
        ),
    )
    click.echo(
        click.style(
            f'Minimum delay: {min_delay}ms',
            fg='red' if abs(min_delay) > frame_duration else 'green',
        ),
    )
    click.echo(
        click.style(
            f'Maximum delay: {max_delay}ms',
            fg='red' if abs(max_delay) > frame_duration else 'green',
        ),
    )


if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        align_audio_cli(sys.argv[1:])
    else:
        align_audio_cli()
