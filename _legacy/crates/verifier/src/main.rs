//! CLI wrapper around the [`verifier`] library, used by the Python
//! differential-parity test (`evidence/conformance/property-tests/test_rust_verifier_parity.py`).
//!
//! Contract: read a JSON array of raw event rows from stdin (the same shape as
//! `SqliteCanonicalStore.raw_rows_for_tenant` produces), run [`verify_chain`],
//! and write the violations as a JSON array to stdout with fields
//! `aggregate_id`, `sequence`, `kind`, `detail` -- matching Python's
//! `ChainViolation`. Exit 0 on success, exit 1 on malformed input.

use std::io::{self, Read, Write};

use verifier::{verify_chain, RawRow};

fn main() {
    if let Err(msg) = run() {
        eprintln!("verifier: {msg}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let mut input = String::new();
    io::stdin()
        .read_to_string(&mut input)
        .map_err(|e| format!("failed to read stdin: {e}"))?;

    let rows: Vec<RawRow> =
        serde_json::from_str(&input).map_err(|e| format!("invalid input JSON: {e}"))?;

    let violations =
        verify_chain(&rows).map_err(|e| format!("invalid payload_json in a row: {e}"))?;

    let out =
        serde_json::to_string(&violations).map_err(|e| format!("failed to serialize: {e}"))?;
    let mut stdout = io::stdout();
    stdout
        .write_all(out.as_bytes())
        .map_err(|e| format!("failed to write stdout: {e}"))?;
    Ok(())
}
