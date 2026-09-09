// Run the same regressions without libtest's worker threads on older devices.
#[path = "../tests/decoder_regression.rs"]
mod regression;

fn main() {
    let cases: &[(&str, fn())] = &[
        (
            "dependency guard",
            regression::vulnerable_buffer_is_absent_from_lockfile,
        ),
        ("reader errors", regression::reader_errors_are_propagated),
        (
            "empty / invalid input",
            regression::empty_and_invalid_input_reach_eof,
        ),
        (
            "truncated frame",
            regression::truncated_last_frame_preserves_decoded_prefix,
        ),
        ("short reads", regression::short_reads_preserve_pcm),
        (
            "wrapped frame",
            regression::unaligned_stream_preserves_frames_across_buffer_wrap,
        ),
        (
            "upstream PCM",
            regression::pcm_matches_upstream_across_many_refills,
        ),
    ];
    for (name, run) in cases {
        eprintln!("START {name}");
        let start = std::time::Instant::now();
        run();
        eprintln!("PASS {name} ({:?})", start.elapsed());
    }
    eprintln!("PASS all {} decoder checks", cases.len());
}
