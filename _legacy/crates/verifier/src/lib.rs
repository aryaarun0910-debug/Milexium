//! Independent Rust implementation of Milexium's evidence hash-chain verifier.
//!
//! # Why this crate exists
//!
//! Verifiability is Milexium's moat. The normative reference verifier lives in
//! Python (`app/verify/hash_chain_verifier.py`, built on
//! `app/canonical/events.py`). This crate re-implements the *same*
//! contract in a second language and is differential-tested (see
//! `evidence/conformance/property-tests/test_rust_verifier_parity.py`) to produce
//! **byte-for-byte identical** results on the same inputs. An independent
//! second implementation that agrees on every clean and tampered chain is a
//! far stronger correctness claim than a single implementation checked against
//! itself.
//!
//! The Python side stays the source of truth; this crate must match it, never
//! the other way around.
//!
//! # Parity contract (must match Python exactly)
//!
//! `canonical_json(payload)` mirrors Python's
//! `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`:
//!
//! * **sorted keys** -- object keys are emitted in ascending order. Rust
//!   `str` ordering is UTF-8 byte order, which for well-formed UTF-8 equals
//!   Unicode code-point order, which is what Python's default `sorted()` uses
//!   on `str` keys. So the two agree even for non-ASCII keys.
//! * **compact separators** -- `,` between items and `:` between key/value,
//!   with no incidental whitespace.
//! * **`ensure_ascii=True`** -- every non-ASCII scalar is escaped to a
//!   `\uXXXX` sequence (astral code points become a UTF-16 surrogate pair
//!   `\uXXXX\uXXXX`), lowercase hex, exactly as CPython's
//!   `c_encode_basestring_ascii` does. `serde_json` does **not** do this by
//!   default, so this crate serializes by hand rather than via
//!   `serde_json::to_string`.
//!
//! # A note on `verify_chain`'s re-serialization
//!
//! The Python verifier does not trust the stored `payload_json` string; it
//! `json.loads(...)` it and hands the parsed value to `compute_hash`, which
//! re-serializes canonically. So what must round-trip identically is
//! *parse -> canonical-serialize*, not the stored bytes. This crate does the
//! same: parse `payload_json` into a [`serde_json::Value`], then feed it to
//! [`compute_hash`].

use serde::Deserialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};

/// One raw stored event row, matching a dict from
/// `SqliteCanonicalStore.raw_rows_for_tenant`. Extra columns present in the
/// row (`event_id`, `tenant_id`, `occurred_at`, ...) are ignored: serde only
/// binds the fields the verifier actually needs.
#[derive(Debug, Clone, Deserialize)]
pub struct RawRow {
    pub aggregate_id: String,
    pub sequence: i64,
    #[serde(default)]
    pub prev_hash: Option<String>,
    pub hash: String,
    #[serde(default)]
    pub idempotency_key: Option<String>,
    /// The canonical JSON string as it is stored. `verify_chain` parses this
    /// and re-serializes it, matching the Python reference.
    pub payload_json: String,
}

/// A detected chain corruption. Mirrors Python's `ChainViolation` dataclass
/// field-for-field (`aggregate_id`, `sequence`, `kind`, `detail`) so the two
/// implementations' outputs can be compared as identical sets.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, serde::Serialize)]
pub struct Violation {
    pub aggregate_id: String,
    pub sequence: i64,
    pub kind: String,
    pub detail: String,
}

/// Deterministic JSON serialization matching Python's
/// `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`.
pub fn canonical_json(value: &Value) -> String {
    let mut out = String::new();
    write_canonical(value, &mut out);
    out
}

fn write_canonical(value: &Value, out: &mut String) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        // Integers serialize exactly; `serde_json::Number`'s `Display` matches
        // Python's `str(int)`/`repr(float)` for the payload types this system
        // stores (ints, and the occasional simple float). Exotic float
        // formatting (huge exponents, -0.0) is out of the tested payload
        // surface -- see the crate report's honest-limitations note.
        Value::Number(n) => out.push_str(&n.to_string()),
        Value::String(s) => write_json_string_ascii(s, out),
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_canonical(item, out);
            }
            out.push(']');
        }
        Value::Object(map) => {
            // Sort keys explicitly rather than relying on serde_json's default
            // BTreeMap ordering, so parity does not depend on whether the
            // `preserve_order` feature is enabled somewhere in the tree.
            let mut entries: Vec<(&String, &Value)> = map.iter().collect();
            entries.sort_by(|a, b| a.0.cmp(b.0));
            out.push('{');
            for (i, (k, v)) in entries.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_json_string_ascii(k, out);
                out.push(':');
                write_canonical(v, out);
            }
            out.push('}');
        }
    }
}

/// Escape a string exactly as CPython's `json` encoder does with
/// `ensure_ascii=True`: printable ASCII passes through, the five short escapes
/// are used, and everything else (control chars, DEL, all non-ASCII) becomes
/// a lowercase `\uXXXX` escape -- with astral code points split into a UTF-16
/// surrogate pair.
fn write_json_string_ascii(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            // Printable ASCII (0x20..=0x7e), minus the specials handled above.
            c if (' '..='~').contains(&c) => out.push(c),
            c => {
                let cp = c as u32;
                if cp <= 0xFFFF {
                    push_u_escape(cp, out);
                } else {
                    // UTF-16 surrogate pair, matching CPython.
                    let n = cp - 0x1_0000;
                    let hi = 0xD800 + ((n >> 10) & 0x3FF);
                    let lo = 0xDC00 + (n & 0x3FF);
                    push_u_escape(hi, out);
                    push_u_escape(lo, out);
                }
            }
        }
    }
    out.push('"');
}

fn push_u_escape(code_unit: u32, out: &mut String) {
    use std::fmt::Write;
    // Always four lowercase hex digits, e.g. U+00E9 -> é.
    let _ = write!(out, "\\u{code_unit:04x}");
}

/// The normative event hash, matching `app/canonical/events.py`:
/// `sha256((prev_hash or "") + canonical_json(payload) + str(sequence) +
/// aggregate_id + (idempotency_key or ""))`, all UTF-8, returned as a lowercase
/// hex digest.
pub fn compute_hash(
    prev_hash: Option<&str>,
    payload: &Value,
    sequence: i64,
    aggregate_id: &str,
    idempotency_key: Option<&str>,
) -> String {
    let mut hasher = Sha256::new();
    hasher.update(prev_hash.unwrap_or("").as_bytes());
    hasher.update(canonical_json(payload).as_bytes());
    hasher.update(sequence.to_string().as_bytes());
    hasher.update(aggregate_id.as_bytes());
    hasher.update(idempotency_key.unwrap_or("").as_bytes());
    hex_lower(&hasher.finalize())
}

fn hex_lower(bytes: &[u8]) -> String {
    use std::fmt::Write;
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        let _ = write!(s, "{b:02x}");
    }
    s
}

/// Verify a batch of raw event rows, reporting every corruption found.
///
/// Groups rows by `aggregate_id` (first-seen order preserved, matching the
/// Python dict-iteration order), sorts each group by `sequence`, then walks it
/// checking for `duplicate_sequence`, `sequence_gap`, `prev_hash_mismatch`,
/// and `hash_mismatch` -- the same four checks, in the same order, with the
/// same `detail` strings as `app/verify/hash_chain_verifier.py`.
///
/// Returns `Err` only if a row's `payload_json` is not valid JSON (the Python
/// reference would raise `json.JSONDecodeError` in that case; corruption
/// itself is *reported*, never raised).
pub fn verify_chain(rows: &[RawRow]) -> Result<Vec<Violation>, serde_json::Error> {
    let mut violations: Vec<Violation> = Vec::new();

    // Group by aggregate_id, preserving first-seen order.
    let mut order: Vec<&str> = Vec::new();
    let mut groups: HashMap<&str, Vec<&RawRow>> = HashMap::new();
    for row in rows {
        let key = row.aggregate_id.as_str();
        if !groups.contains_key(key) {
            order.push(key);
        }
        groups.entry(key).or_default().push(row);
    }

    for aggregate_id in order {
        let mut group = groups.remove(aggregate_id).expect("group present");
        // Stable sort by sequence, matching Python's `sorted(..., key=sequence)`.
        group.sort_by_key(|r| r.sequence);

        let mut expected_sequence: i64 = 1;
        let mut expected_prev_hash: Option<String> = None;
        let mut seen_sequences: HashSet<i64> = HashSet::new();

        for row in group {
            let sequence = row.sequence;

            if seen_sequences.contains(&sequence) {
                violations.push(Violation {
                    aggregate_id: aggregate_id.to_string(),
                    sequence,
                    kind: "duplicate_sequence".to_string(),
                    detail: format!("sequence {sequence} appears more than once"),
                });
                continue;
            }
            seen_sequences.insert(sequence);

            if sequence != expected_sequence {
                violations.push(Violation {
                    aggregate_id: aggregate_id.to_string(),
                    sequence,
                    kind: "sequence_gap".to_string(),
                    detail: format!("expected sequence {expected_sequence}, found {sequence}"),
                });
            }

            if row.prev_hash != expected_prev_hash {
                violations.push(Violation {
                    aggregate_id: aggregate_id.to_string(),
                    sequence,
                    kind: "prev_hash_mismatch".to_string(),
                    detail: format!(
                        "expected prev_hash {}, found {}",
                        py_repr_opt(&expected_prev_hash),
                        py_repr_opt(&row.prev_hash),
                    ),
                });
            }

            let payload: Value = serde_json::from_str(&row.payload_json)?;
            let recomputed = compute_hash(
                row.prev_hash.as_deref(),
                &payload,
                sequence,
                aggregate_id,
                row.idempotency_key.as_deref(),
            );
            if recomputed != row.hash {
                violations.push(Violation {
                    aggregate_id: aggregate_id.to_string(),
                    sequence,
                    kind: "hash_mismatch".to_string(),
                    detail: format!("recomputed {} != stored {}", recomputed, row.hash),
                });
            }

            expected_sequence = sequence + 1;
            expected_prev_hash = Some(row.hash.clone());
        }
    }

    Ok(violations)
}

/// Render an `Option<String>` the way Python's `f"{value!r}"` does for the
/// values a `prev_hash` can hold: `None` -> `None`, and a string -> the string
/// wrapped in single quotes (Python's `repr`). `prev_hash` values in this
/// system are always `None` or a 64-char hex digest, so the single-quote form
/// is exact; the escaping below also covers the general string case for
/// robustness.
fn py_repr_opt(value: &Option<String>) -> String {
    match value {
        None => "None".to_string(),
        Some(s) => py_repr_str(s),
    }
}

fn py_repr_str(s: &str) -> String {
    // Python prefers single quotes, switching to double quotes only if the
    // string contains a single quote but no double quote.
    let quote = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::new();
    out.push(quote);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if (' '..='~').contains(&c) => out.push(c),
            c => {
                let cp = c as u32;
                if cp <= 0xFF {
                    let _ = write_fmt(&mut out, format_args!("\\x{cp:02x}"));
                } else if cp <= 0xFFFF {
                    let _ = write_fmt(&mut out, format_args!("\\u{cp:04x}"));
                } else {
                    let _ = write_fmt(&mut out, format_args!("\\U{cp:08x}"));
                }
            }
        }
    }
    out.push(quote);
    out
}

fn write_fmt(out: &mut String, args: std::fmt::Arguments) -> std::fmt::Result {
    use std::fmt::Write;
    out.write_fmt(args)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    // Known-answer values below were produced by the Python reference
    // (app/canonical/events.py) and pasted here verbatim.

    #[test]
    fn canonical_json_sorts_keys_and_uses_compact_separators() {
        let v = json!({"b": 1, "a": 2, "nested": {"z": 9, "a": 8}});
        assert_eq!(
            canonical_json(&v),
            r#"{"a":2,"b":1,"nested":{"a":8,"z":9}}"#
        );
    }

    #[test]
    fn canonical_json_scalar_types_match_python() {
        let v = json!({"t": true, "f": false, "n": null, "x": 3, "y": -7});
        assert_eq!(
            canonical_json(&v),
            r#"{"f":false,"n":null,"t":true,"x":3,"y":-7}"#
        );
    }

    #[test]
    fn canonical_json_escapes_non_ascii_like_ensure_ascii() {
        // "cafe-acute" (U+00E9) / bus emoji (U+1F68C, astral -> surrogate
        // pair) / capital omega (U+03A9), keys sorted. Expected is the escaped
        // ASCII-only form the Python reference emits with ensure_ascii=True.
        let v = json!({"name": "caf\u{e9}", "emoji": "\u{1f68c}", "greek": "\u{3a9}"});
        assert_eq!(
            canonical_json(&v),
            "{\"emoji\":\"\\ud83d\\ude8c\",\"greek\":\"\\u03a9\",\"name\":\"caf\\u00e9\"}"
        );
    }

    #[test]
    fn canonical_json_escapes_control_chars_and_specials() {
        // 0x01 and 0x7f (DEL) -> \u escapes; tab/newline -> short escapes;
        // the " and \ specials -> \" and \\.
        let v = json!({"ctrl": "\u{01}\u{7f}\t\n", "quote": "a\"b\\c"});
        assert_eq!(
            canonical_json(&v),
            "{\"ctrl\":\"\\u0001\\u007f\\t\\n\",\"quote\":\"a\\\"b\\\\c\"}"
        );
    }

    #[test]
    fn compute_hash_known_answers() {
        let h1 = compute_hash(None, &json!({"i": 0}), 1, "req-0001", None);
        assert_eq!(
            h1,
            "b26b218f6ee3c37dec1976e7442b2c6b9f25a56f9e67c44f9d3f57df0a884f7f"
        );

        let h2 = compute_hash(Some(&h1), &json!({"i": 1}), 2, "req-0001", None);
        assert_eq!(
            h2,
            "2d591b4f07bca39815572a038f265979920843c1bd3fa4009e40f910de47b5f4"
        );

        let h3 = compute_hash(
            None,
            &json!({"override_reason": "family request"}),
            1,
            "req-0002",
            Some("override-cmd-abc123"),
        );
        assert_eq!(
            h3,
            "c2e2e0996b0c319c3be1d444f085627eb3297040517e0acd09883afa144d6493"
        );
    }

    /// Build a valid two-event chain and confirm the verifier accepts it.
    fn clean_chain() -> Vec<RawRow> {
        let p0 = json!({"i": 0});
        let h0 = compute_hash(None, &p0, 1, "req-0001", None);
        let p1 = json!({"i": 1});
        let h1 = compute_hash(Some(&h0), &p1, 2, "req-0001", None);
        vec![
            RawRow {
                aggregate_id: "req-0001".to_string(),
                sequence: 1,
                prev_hash: None,
                hash: h0.clone(),
                idempotency_key: None,
                payload_json: canonical_json(&p0),
            },
            RawRow {
                aggregate_id: "req-0001".to_string(),
                sequence: 2,
                prev_hash: Some(h0),
                hash: h1,
                idempotency_key: None,
                payload_json: canonical_json(&p1),
            },
        ]
    }

    #[test]
    fn verify_chain_accepts_a_clean_chain() {
        let rows = clean_chain();
        assert_eq!(verify_chain(&rows).unwrap(), vec![]);
    }

    #[test]
    fn verify_chain_flags_payload_tamper_as_hash_mismatch() {
        let mut rows = clean_chain();
        // Rewrite the second event's payload without recomputing its hash.
        rows[1].payload_json = r#"{"i":999}"#.to_string();
        let v = verify_chain(&rows).unwrap();
        assert!(v
            .iter()
            .any(|x| x.kind == "hash_mismatch" && x.sequence == 2));
    }

    #[test]
    fn verify_chain_flags_deleted_middle_as_gap() {
        let mut rows = clean_chain();
        // Extend to three, then drop the middle one.
        let p2 = json!({"i": 2});
        let h1 = rows[1].hash.clone();
        let h2 = compute_hash(Some(&h1), &p2, 3, "req-0001", None);
        rows.push(RawRow {
            aggregate_id: "req-0001".to_string(),
            sequence: 3,
            prev_hash: Some(h1),
            hash: h2,
            idempotency_key: None,
            payload_json: canonical_json(&p2),
        });
        rows.remove(1); // delete sequence 2
        let violations = verify_chain(&rows).unwrap();
        let kinds: HashSet<&str> = violations.iter().map(|v| v.kind.as_str()).collect();
        assert!(kinds.contains("sequence_gap") || kinds.contains("prev_hash_mismatch"));
    }

    #[test]
    fn verify_chain_flags_forged_hash_as_prev_hash_mismatch() {
        // Attacker recomputes the tampered event's own hash but cannot update
        // the downstream prev_hash, so the chain link breaks there.
        let p0 = json!({"i": 0});
        let h0 = compute_hash(None, &p0, 1, "req-0001", None);
        let p1 = json!({"i": 1});
        let h1 = compute_hash(Some(&h0), &p1, 2, "req-0001", None);
        let p2 = json!({"i": 2});
        let h2 = compute_hash(Some(&h1), &p2, 3, "req-0001", None);

        // Forge event 2's payload and its own hash consistently.
        let forged_payload = json!({"i": 999});
        let forged_hash = compute_hash(Some(&h0), &forged_payload, 2, "req-0001", None);

        let rows = vec![
            RawRow {
                aggregate_id: "req-0001".to_string(),
                sequence: 1,
                prev_hash: None,
                hash: h0.clone(),
                idempotency_key: None,
                payload_json: canonical_json(&p0),
            },
            RawRow {
                aggregate_id: "req-0001".to_string(),
                sequence: 2,
                prev_hash: Some(h0),
                hash: forged_hash,
                idempotency_key: None,
                payload_json: canonical_json(&forged_payload),
            },
            RawRow {
                aggregate_id: "req-0001".to_string(),
                sequence: 3,
                prev_hash: Some(h1), // still points at the ORIGINAL event-2 hash
                hash: h2,
                idempotency_key: None,
                payload_json: canonical_json(&p2),
            },
        ];
        let v = verify_chain(&rows).unwrap();
        assert!(v
            .iter()
            .any(|x| x.kind == "prev_hash_mismatch" && x.sequence == 3));
    }

    #[test]
    fn verify_chain_ignores_extra_row_columns() {
        // Rows from raw_rows_for_tenant carry event_id/tenant_id/etc.; serde
        // must skip them, not error.
        let p0 = json!({"i": 0});
        let h0 = compute_hash(None, &p0, 1, "req-0001", None);
        let row_json = format!(
            r#"[{{"event_id":"e1","tenant_id":"t1","aggregate_id":"req-0001","aggregate_type":"ServiceRequest","sequence":1,"occurred_at":"2026-07-23T08:00:00+00:00","actor_type":"system","actor_id":"scheduler","event_type":"recommendation","payload_json":{payload:?},"reason_codes":"[]","idempotency_key":null,"prev_hash":null,"hash":{hash:?}}}]"#,
            payload = canonical_json(&p0),
            hash = h0,
        );
        let rows: Vec<RawRow> = serde_json::from_str(&row_json).unwrap();
        assert_eq!(verify_chain(&rows).unwrap(), vec![]);
    }

    #[test]
    fn py_repr_matches_python_for_hash_and_none() {
        assert_eq!(py_repr_opt(&None), "None");
        assert_eq!(py_repr_opt(&Some("abc123".to_string())), "'abc123'");
    }
}
