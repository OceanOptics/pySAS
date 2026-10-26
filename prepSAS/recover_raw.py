"""Inspect and conservatively recover one pySAS Satlantic raw file.

Header-delimited records are *candidates*: corruption can introduce a false
header or obscure a real one. Inspection includes invalid candidates; recovery
retains only fully validated frames and writes to a new file.

Example:
    python -m prepSAS.recover_raw data.raw extracted_calibration_directory --recover-output data.recovered.raw --figures
    python -m prepSAS.recover_raw data.raw extracted_calibration_directory --recover-output data.recovered.raw --audit
    python -m prepSAS.recover_raw data.raw extracted_calibration_directory --recover-output data.simple.raw --no-stitch-fragments
    python -m prepSAS.recover_raw raw_directory extracted_calibration_directory --recover-output recovered_directory
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from struct import error as StructError, unpack

from pySatlantic.instrument import Instrument


MIN_TIMESTAMP = datetime(2020, 1, 1, tzinfo=timezone.utc)


def format_bytes(size: int) -> str:
    """Format a byte count with decimal SI prefixes."""
    if size >= 1_000_000:
        return f"{size / 1_000_000:.2f} MB"
    if size >= 1_000:
        return f"{size / 1_000:.2f} kB"
    return f"{size} B"


def count_covered_bytes(spans: list[tuple[int, int]]) -> int:
    """Count the union of covered byte intervals in the source file."""
    covered = 0
    left = right = 0
    for start, end in sorted(spans):
        if start > right:
            covered += right - left
            left, right = start, end
        else:
            right = max(right, end)
    return covered + right - left


def frame_error(parser: Instrument, frame: bytes, header: str) -> str | None:
    """Return a reason if a timestamp-free frame fails calibration checks."""
    cal = parser.cal[header]
    if not cal.variable_frame_length and len(frame) != cal.frame_length:
        return f"expected {cal.frame_length} frame bytes, got {len(frame)}"
    if cal.variable_frame_length and (not frame.endswith(b"\r\n") or frame.count(b"\r\n") != 1):
        return "variable-length frame has missing or extra line terminators"
    if header == "$GPRMC":
        star = frame.rfind(b"*")
        if star < 0 or frame[star + 3:] != b"\r\n":
            return "missing NMEA checksum"
        try:
            checksum = int(frame[star + 1:star + 3], 16)
        except ValueError:
            return "invalid NMEA checksum digits"
        actual = 0
        for byte in frame[1:star]:
            actual ^= byte
        if checksum != actual:
            return "NMEA checksum mismatch"
    try:
        _, calibration_valid = parser.parse_frame(
            frame, header,
            flag_get_auxiliary_variables=True,
            flag_get_unusable_variables=True,
        )
        if calibration_valid is not None and not bool(calibration_valid):
            return "calibration checksum or terminator validation failed"
    except Exception as exc:  # Invalid binary data can raise many parser errors.
        return f"{type(exc).__name__}: {str(exc)[:120]}"
    return None


def decode_timestamp(suffix: bytes, latest: datetime) -> datetime | None:
    """Decode pySAS's seven-byte (year/day, time) trailer."""
    if len(suffix) != 7:
        return None
    try:
        day, clock = unpack("!ii", b"\x00" + suffix)
        if not 1_000_001 <= day <= 9_999_366 or not 0 <= clock <= 999_999_999:
            return None
        value = datetime.strptime(f"{day:07d}{clock:09d}000", "%Y%j%H%M%S%f")
        value = value.replace(tzinfo=timezone.utc)
        return value if MIN_TIMESTAMP <= value <= latest else None
    except (StructError, ValueError, OverflowError):
        return None


def inspect(raw_path: Path, cal_path: Path, bucket_minutes: int | None = None) -> dict:
    if not cal_path.is_dir():
        raise ValueError("Pass a directory of extracted .cal/.tdf files; loading a SIP archive extracts files")
    parser = Instrument(str(cal_path))
    calibrations = parser.cal
    headers = sorted((name.encode("ascii") for name in calibrations), key=len, reverse=True)
    if not headers:
        raise ValueError("Calibration contains no frame headers")

    raw = raw_path.read_bytes()
    pattern = re.compile(b"(" + b"|".join(re.escape(header) for header in headers) + b")")
    matches = list(pattern.finditer(raw))
    latest = datetime.now(timezone.utc) + timedelta(days=1)
    by_header = defaultdict(Counter)
    by_bucket = defaultdict(Counter) if bucket_minutes is not None else None
    totals = Counter()
    examples = defaultdict(list)
    first_time = last_time = None

    for i, match in enumerate(matches):
        header = match.group().decode("ascii")
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        record = raw[match.start():end]
        frame, suffix = record[:-7], record[-7:]
        timestamp = decode_timestamp(suffix, latest)
        cal = calibrations[header]
        expected = None if cal.variable_frame_length else cal.frame_length
        issues = []
        if timestamp is None:
            issues.append("timestamp")
        if expected is not None and len(frame) != expected:
            issues.append("length")
        parse_error = frame_error(parser, frame, header)
        if parse_error:
            issues.append("parse")

        status = "valid" if not issues else "invalid"
        for counts in (totals, by_header[header]):
            counts["candidates"] += 1
            counts[status] += 1
            for issue in issues:
                counts[f"bad_{issue}"] += 1
        if timestamp is not None:
            first_time = min(first_time, timestamp) if first_time else timestamp
            last_time = max(last_time, timestamp) if last_time else timestamp
            if by_bucket is not None:
                bucket = timestamp.replace(second=0, microsecond=0)
                bucket -= timedelta(minutes=bucket.minute % bucket_minutes)
                by_bucket[bucket.isoformat()][status] += 1
        elif by_bucket is not None:
            by_bucket["unplaced"][status] += 1
        if issues:
            key = "+".join(issues)
            if len(examples[key]) < 5:
                examples[key].append({
                    "offset": match.start(), "header": header,
                    "record_bytes": len(record), "frame_bytes": len(frame),
                    "expected_frame_bytes": expected,
                    "timestamp": timestamp.isoformat() if timestamp else None,
                    "parse_error": parse_error,
                })

    report = {
        "raw_file": str(raw_path), "calibration": str(cal_path),
        "raw_bytes": len(raw), "leading_unmatched_bytes": matches[0].start() if matches else len(raw),
        "first_timestamp": first_time.isoformat() if first_time else None,
        "last_timestamp": last_time.isoformat() if last_time else None,
        "totals": dict(totals),
        "by_header": {k: dict(v) for k, v in sorted(by_header.items())},
        "examples": dict(examples),
    }
    if by_bucket is not None:
        report["by_time_bucket"] = {k: dict(v) for k, v in sorted(by_bucket.items())}
    return report


def strip_inserted_timestamps(
    frame: bytes, prefixes: tuple[bytes, ...], lower: datetime, upper: datetime,
) -> tuple[bytes, list[dict]]:
    """Remove logger timestamps and retain their positions in the clean bytes."""
    pieces = []
    removed = []
    copied_to = cursor = 0
    clean_length = 0
    while cursor <= len(frame) - 7:
        positions = [frame.find(prefix, cursor) for prefix in prefixes]
        positions = [pos for pos in positions if pos >= 0]
        if not positions:
            break
        pos = min(positions)
        timestamp = decode_timestamp(frame[pos:pos + 7], upper)
        if timestamp is not None and lower <= timestamp <= upper:
            pieces.append(frame[copied_to:pos])
            clean_length += pos - copied_to
            removed.append({"source_offset": pos, "source_after": pos + 7,
                            "clean_offset": clean_length, "timestamp": timestamp.isoformat()})
            cursor = copied_to = pos + 7
        else:
            cursor = pos + 1
    pieces.append(frame[copied_to:])
    return b"".join(pieces), removed


def stitch_rejected_frames(
    raw: bytes, parser: Instrument, rejected: list[dict], accepted_spans: list[tuple[int, int]],
    markers: list[dict],
) -> tuple[list[dict], dict]:
    """Join timestamp-delimited chunks across other sensors' frames.

    Es is treated as a separate serial stream from the Lt/Li HyperSAS stream.
    Search is limited to 1.5 seconds and 12 eligible continuation chunks.
    Every accepted frame must have one unique chunk sequence, a matching
    calibrated checksum, and a real timestamp immediately after its last byte.
    Ambiguous, truncated, conflicting, and previously used chunks are excluded.
    """
    chunks = []
    start = 0
    for marker in markers:
        end = marker["source_offset"]
        if end > start:
            chunks.append({
                "start": start, "end": end, "payload": raw[start:end],
                "timestamp_bytes": raw[end:marker["source_after"]],
                "timestamp": marker["timestamp"],
                "time": datetime.fromisoformat(marker["timestamp"]),
            })
        start = marker["source_after"]
    starts = [chunk["start"] for chunk in chunks]

    header_pattern = re.compile(b"(" + b"|".join(
        re.escape(name.encode("ascii")) for name in sorted(parser.cal, key=len, reverse=True)) + b")")

    def stream(header: str) -> str | None:
        variable = parser.cal[header].core_groupname
        if variable == "ES":
            return "Es"
        if variable in {"LI", "LT"}:
            return "HyperSAS"
        return None

    chunk_streams = []
    for chunk in chunks:
        chunk_streams.append({stream(match.group().decode("ascii"))
                              for match in header_pattern.finditer(chunk["payload"])})

    blocked = set()
    span_index = 0
    for index, chunk in enumerate(chunks):
        while span_index < len(accepted_spans) and accepted_spans[span_index][1] <= chunk["start"]:
            span_index += 1
        if span_index < len(accepted_spans):
            left, right = accepted_spans[span_index]
            if left < chunk["end"] and chunk["start"] < right:
                blocked.add(index)

    proposals = []
    stats = Counter(chunks=len(chunks), blocked_chunks=len(blocked))
    for record in rejected:
        header = record["header"]
        group = stream(header)
        if group is None or parser.cal[header].variable_frame_length:
            continue
        offset = record["source_offset"]
        first_index = bisect_right(starts, offset) - 1
        if first_index < 0 or first_index in blocked:
            continue
        first = chunks[first_index]
        if not first["start"] <= offset < first["end"]:
            continue
        initial = first["payload"][offset - first["start"]:]
        if header_pattern.search(initial, len(header)):
            continue
        target = parser.cal[header].frame_length
        if len(initial) >= target:
            continue

        # A new header from this serial stream means its previous frame ended.
        options = []
        deadline = first["time"] + timedelta(seconds=1.5)
        truncated = False
        for index in range(first_index + 1, len(chunks)):
            chunk = chunks[index]
            if chunk["time"] > deadline:
                break
            if index - first_index > 30:
                truncated = True
                break
            if group in chunk_streams[index]:
                break
            if index in blocked or chunk_streams[index]:
                continue
            if chunk["time"] < first["time"] - timedelta(milliseconds=100):
                continue
            options.append(index)
            if len(options) == 12:
                truncated = True
                break

        if truncated:
            stats["truncated_starts"] += 1
            continue
        if not options or len(initial) + sum(len(chunks[i]["payload"]) for i in options) < target:
            continue
        stats["searched_starts"] += 1
        remaining_sizes = [0] * (len(options) + 1)
        for position in range(len(options) - 1, -1, -1):
            remaining_sizes[position] = remaining_sizes[position + 1] + len(chunks[options[position]]["payload"])
        solutions = []

        def search(position: int, size: int, selected: tuple[int, ...]) -> None:
            if len(solutions) > 1 or size + remaining_sizes[position] < target:
                return
            if size == target:
                frame = initial + b"".join(chunks[i]["payload"] for i in selected)
                if frame_error(parser, frame, header) is None:
                    solutions.append((selected, frame))
                return
            if position == len(options):
                return
            search(position + 1, size, selected)
            index = options[position]
            new_size = size + len(chunks[index]["payload"])
            if new_size <= target:
                search(position + 1, new_size, selected + (index,))

        search(0, len(initial), ())
        if len(solutions) == 1:
            selected, frame = solutions[0]
            final = chunks[selected[-1]]
            proposals.append({
                "source_offset": offset, "header": header,
                "frame": frame, "timestamp_bytes": final["timestamp_bytes"],
                "timestamp": final["timestamp"],
                "chunk_indices": (first_index,) + selected,
                "source_chunks": ([{"start": offset, "end": first["end"]}]
                                  + [{"start": chunks[i]["start"], "end": chunks[i]["end"]}
                                     for i in selected]),
            })
        elif len(solutions) > 1:
            stats["ambiguous_starts"] += 1

    # Do not assign any chunk to more than one newly reconstructed frame.
    owners = Counter(index for proposal in proposals for index in proposal["chunk_indices"])
    accepted = [proposal for proposal in proposals
                if all(owners[index] == 1 for index in proposal["chunk_indices"])]
    stats["unique_proposals"] = len(proposals)
    stats["conflicting_proposals"] = len(proposals) - len(accepted)
    stats["accepted_frames"] = len(accepted)
    return accepted, dict(stats)


def recover(raw_path: Path, cal_path: Path, output_path: Path, inspection: dict,
            stitch_fragments: bool = True, write_audit: bool = False) -> tuple[dict, dict]:
    """Keep valid records, repair inserted timestamps, and optionally stitch fragments."""
    if output_path.resolve() == raw_path.resolve():
        raise ValueError("Recovery output must differ from the input file")
    audit_path = output_path.with_name(output_path.name + ".audit.json")
    if output_path.exists() or (write_audit and audit_path.exists()):
        raise FileExistsError("Recovery output or requested audit already exists; choose a new output path")
    if not inspection["first_timestamp"] or not inspection["last_timestamp"]:
        raise ValueError("Cannot establish the recording date from intact timestamps")

    lower = datetime.fromisoformat(inspection["first_timestamp"]) - timedelta(minutes=5)
    upper = datetime.fromisoformat(inspection["last_timestamp"]) + timedelta(minutes=5)
    days = []
    day = lower.date()
    while day <= upper.date():
        days.append(int(f"{day.year}{day.timetuple().tm_yday:03d}").to_bytes(3, "big"))
        day += timedelta(days=1)
    prefixes = tuple(days)

    parser = Instrument(str(cal_path))
    headers = sorted((name.encode("ascii") for name in parser.cal), key=len, reverse=True)
    pattern = re.compile(b"(" + b"|".join(re.escape(header) for header in headers) + b")")
    raw = raw_path.read_bytes()
    _, all_markers = strip_inserted_timestamps(raw, prefixes, lower, upper)
    matches = list(pattern.finditer(raw))
    retained = []
    accepted_spans = []
    covered_spans = [(marker["source_offset"], marker["source_after"])
                     for marker in all_markers]
    counts = Counter()
    by_header = defaultdict(Counter)
    rejected_records = []

    for i, match in enumerate(matches):
        offset = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        record = raw[offset:end]
        header = match.group().decode("ascii")
        frame, suffix = record[:-7], record[-7:]
        timestamp = decode_timestamp(suffix, upper)
        if timestamp is None or not lower <= timestamp <= upper:
            error = "missing or implausible final timestamp"
        else:
            error = frame_error(parser, frame, header)
        if error is None:
            status = "original_valid"
            repaired = record
        else:
            cleaned, markers = strip_inserted_timestamps(record, prefixes, lower, upper)
            cal = parser.cal[header]
            if cal.variable_frame_length:
                line_end = cleaned.find(b"\r\n")
                target_length = line_end + 2 if line_end >= 0 else None
            else:
                target_length = cal.frame_length
            terminal = next((marker for marker in markers
                             if marker["clean_offset"] == target_length), None)
            if target_length is None or len(cleaned) < target_length:
                cleaned_error = "incomplete frame"
            else:
                candidate = cleaned[:target_length]
                cleaned_error = frame_error(parser, candidate, header)
                if cleaned_error is None and terminal is None:
                    # The logger sometimes timestamps a read containing a full
                    # frame plus the start of unrelated data. Bound that lag.
                    terminal = next((marker for marker in markers
                                     if target_length < marker["clean_offset"] <= target_length + 128), None)
                    if terminal is None:
                        cleaned_error = "valid payload without a nearby following timestamp"
            if cleaned_error is None:
                lag = terminal["clean_offset"] - target_length
                status = "recovered"
                terminal_bytes = record[terminal["source_offset"]:terminal["source_after"]]
                repaired = candidate + terminal_bytes
                recovery_detail = {
                    "source_offset": offset, "source_bytes": len(record),
                    "output_bytes": len(repaired),
                    "header": header, "timestamp": terminal["timestamp"],
                    "timestamp_lag_bytes": lag,
                    "removed_timestamps": [marker for marker in markers
                                           if marker["source_offset"] < terminal["source_offset"]],
                    "discarded_tail_bytes": len(record) - terminal["source_after"],
                }
                source_end = offset + terminal["source_after"]
                covered_spans.append((offset, offset + terminal["source_offset"] - lag))
                covered_spans.append((offset + terminal["source_offset"], source_end))
            else:
                status = "rejected"
                error = cleaned_error

        counts[status] += 1
        by_header[header][status] += 1
        if status == "rejected":
            rejected_records.append({
                "source_offset": offset, "source_bytes": len(record),
                "header": header, "reason": error,
            })
        else:
            if status == "original_valid":
                recovery_detail = None
                source_end = end
                covered_spans.append((offset, end))
            retained.append({"source_offset": offset, "header": header,
                             "status": status, "data": repaired,
                             "recovery_detail": recovery_detail})
            accepted_spans.append((offset, source_end))

    if stitch_fragments:
        stitched, _ = stitch_rejected_frames(
            raw, parser, rejected_records, accepted_spans, all_markers)
        stitched_offsets = {item["source_offset"] for item in stitched}
        rejected_records = [item for item in rejected_records
                            if item["source_offset"] not in stitched_offsets]
        for item in stitched:
            header = item["header"]
            counts["rejected"] -= 1
            by_header[header]["rejected"] -= 1
            counts["recovered"] += 1
            by_header[header]["recovered"] += 1
            repaired = item["frame"] + item["timestamp_bytes"]
            detail = {
                "source_offset": item["source_offset"], "header": header,
                "output_bytes": len(repaired), "timestamp": item["timestamp"],
                "source_chunks": item["source_chunks"],
            }
            retained.append({"source_offset": item["source_offset"], "header": header,
                             "status": "recovered", "data": repaired,
                             "recovery_detail": detail})
            for chunk in item["source_chunks"]:
                covered_spans.append((chunk["start"], chunk["end"] + 7))

    retained.sort(key=lambda item: item["source_offset"])
    output = bytearray()
    recovered_records = []
    for item in retained:
        detail = item["recovery_detail"]
        if detail is not None:
            detail["output_offset"] = len(output)
            recovered_records.append(detail)
        output.extend(item["data"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("xb") as stream:
        stream.write(output)
    verification = inspect(output_path, cal_path)
    if verification["totals"].get("invalid", 0):
        raise RuntimeError("Recovered output failed validation; see output file before using it")
    valid_bytes = count_covered_bytes(covered_spans)
    if valid_bytes > len(raw):
        raise RuntimeError("Source byte coverage exceeds input length")
    ignored_bytes = len(raw) - valid_bytes
    byte_statistics = {
        "valid_bytes": valid_bytes, "ignored_bytes": ignored_bytes, "total_bytes": len(raw),
        "valid": format_bytes(valid_bytes), "ignored": format_bytes(ignored_bytes),
        "total": format_bytes(len(raw)),
        "recovered_percent": round(valid_bytes / len(raw) * 100, 2) if raw else 0.0,
    }
    audit = {
        "input": str(raw_path), "input_sha256": sha256(raw).hexdigest(),
        "output": str(output_path), "output_sha256": sha256(output).hexdigest(),
        "output_bytes": len(output), "calibration": str(cal_path),
        "counts": {status: counts.get(status, 0)
                   for status in ("original_valid", "recovered", "rejected")},
        "byte_statistics": byte_statistics,
        "by_header": {key: {status: value.get(status, 0)
                            for status in ("original_valid", "recovered", "rejected")}
                      for key, value in sorted(by_header.items())},
        "verification": verification["totals"],
        "recovered_records": recovered_records,
        "rejected_records": rejected_records,
    }
    if write_audit:
        with audit_path.open("x") as stream:
            json.dump(audit, stream, indent=2)
    summary = {key: value for key, value in audit.items()
               if key not in ("recovered_records", "rejected_records")}
    return summary, audit


def plot_spectra(recovered_path: Path, cal_path: Path, audit: dict | None = None) -> list[dict]:
    """Plot every validated spectral frame, grouped by provenance."""
    import plotly.graph_objects as go

    if audit is None:
        audit_path = recovered_path.with_name(recovered_path.name + ".audit.json")
        if not audit_path.is_file():
            raise FileNotFoundError(f"Recovery audit not found: {audit_path}; use --recover-output to plot during recovery")
        with audit_path.open() as stream:
            audit = json.load(stream)
    raw = recovered_path.read_bytes()
    if sha256(raw).hexdigest() != audit["output_sha256"]:
        raise ValueError("Recovered file hash does not match its recovery provenance")
    recovered_offsets = {entry["output_offset"] for entry in audit["recovered_records"]}

    parser = Instrument(str(cal_path))
    groups = {}
    for header, cal in parser.cal.items():
        variable = cal.core_groupname.upper()
        if variable not in {"ES", "LT", "LI"} or not cal.core_variables:
            continue
        # Satlantic spectral headers use HSE/HED for Es and HSL/HLD for Lt/Li.
        state = "dark" if header.startswith(("SATHED", "SATHLD")) else "light"
        key = (variable.title(), state)
        wavelengths = [float(cal.id[index]) for index in cal.core_variables]
        units = cal.units[cal.core_variables[0]]
        groups[key] = {
            "header": header, "wavelengths": wavelengths, "units": units,
            "valid": {"x": [], "y": [], "count": 0},
            "recovered": {"x": [], "y": [], "count": 0},
        }
    if len(groups) != 6:
        raise ValueError(f"Expected six Es/Lt/Li light/dark calibrations, found {len(groups)}")

    headers = sorted((header.encode("ascii") for header in parser.cal), key=len, reverse=True)
    pattern = re.compile(b"(" + b"|".join(re.escape(header) for header in headers) + b")")
    for match in pattern.finditer(raw):
        header = match.group().decode("ascii")
        cal = parser.cal[header]
        key = (cal.core_groupname.title(),
               "dark" if header.startswith(("SATHED", "SATHLD")) else "light")
        if key not in groups or groups[key]["header"] != header:
            continue
        frame = raw[match.start():match.start() + cal.frame_length]
        values, _ = parser.parse_frame(frame, header, flag_get_auxiliary_variables=False)
        spectrum = values[cal.core_groupname]
        status = "recovered" if match.start() in recovered_offsets else "valid"
        trace = groups[key][status]
        trace["x"].extend(groups[key]["wavelengths"])
        trace["x"].append(None)
        trace["y"].extend(float(value) for value in spectrum)
        trace["y"].append(None)
        trace["count"] += 1

    results = []
    for variable in ("Es", "Lt", "Li"):
        for state in ("light", "dark"):
            data = groups[(variable, state)]
            expected = audit["by_header"][data["header"]]
            expected_valid = expected.get("original_valid", 0)
            expected_recovered = expected.get("recovered", 0)
            if (data["valid"]["count"], data["recovered"]["count"]) != (expected_valid, expected_recovered):
                raise ValueError(f"Figure counts disagree with recovery audit for {data['header']}")
            results.append((variable, state, data))

    figure_paths = []
    for variable, state, data in results:
        fig = go.Figure()
        for status, color, opacity in (
            ("valid", "#1f77b4", 0.85),
            ("recovered", "#d95f02", 0.13),
        ):
            trace = data[status]
            fig.add_trace(go.Scattergl(
                x=trace["x"], y=trace["y"], mode="lines",
                name=f"{status.title()} (n={trace['count']:,})",
                line={"color": color, "width": 1}, opacity=opacity,
                connectgaps=False,
                hovertemplate="%{x:.2f} nm<br>%{y:.4g}<extra></extra>",
            ))
        fig.update_layout(
            title=f"{variable} {state} spectra",
            xaxis_title="Wavelength (nm)",
            yaxis_title=f"{variable} ({data['units']})",
            legend_title="Frame status",
            template="plotly_white",
            hovermode="closest",
        )
        path = recovered_path.with_name(f"{recovered_path.stem}.{variable}.{state}.html")
        fig.write_html(path, include_plotlyjs=True, full_html=True, auto_open=False)
        figure_paths.append({"variable": variable, "state": state, "path": str(path),
                             "valid": data["valid"]["count"],
                             "recovered": data["recovered"]["count"]})
    return figure_paths


def print_report(report: dict) -> None:
    print(f"Raw file: {report['raw_file']}")
    print(f"Calibration: {report['calibration']}")
    print(f"Bytes: {report['raw_bytes']:,}; before first known header: "
          f"{report['leading_unmatched_bytes']:,}")
    print(f"Timestamp span: {report['first_timestamp']} to {report['last_timestamp']}")
    print("Counts overlap: a candidate can fail more than one check.")
    print("Header                 candidates    valid  invalid  timestamp  length  parse")
    for header, counts in report["by_header"].items():
        print(f"{header:22} {counts.get('candidates', 0):10,} "
              f"{counts.get('valid', 0):8,} {counts.get('invalid', 0):8,} "
              f"{counts.get('bad_timestamp', 0):10,} {counts.get('bad_length', 0):7,} "
              f"{counts.get('bad_parse', 0):6,}")
    counts = report["totals"]
    print(f"{'TOTAL':22} {counts.get('candidates', 0):10,} "
          f"{counts.get('valid', 0):8,} {counts.get('invalid', 0):8,} "
          f"{counts.get('bad_timestamp', 0):10,} {counts.get('bad_length', 0):7,} "
          f"{counts.get('bad_parse', 0):6,}")
    if "by_time_bucket" in report:
        print("\nTime bucket (UTC)             valid  invalid")
        for bucket, counts in report["by_time_bucket"].items():
            print(f"{bucket:29} {counts.get('valid', 0):6,} {counts.get('invalid', 0):8,}")
    print("\nFirst examples by failure combination (byte offsets):")
    for issue, examples in report["examples"].items():
        print(f"  {issue}:")
        for example in examples:
            expected = example["expected_frame_bytes"]
            print(f"    {example['header']}@{example['offset']:,}: "
                  f"frame {example['frame_bytes']} bytes, expected {expected}, "
                  f"time {example['timestamp']}; {example['parse_error']}")
    print("\nCandidate counts are provisional; a damaged payload may contain a header-like byte sequence.")


def plan_inputs(raw_path: Path, output_path: Path | None, figures: bool,
                audit: bool = False) -> tuple[list[tuple[Path, Path | None]], bool]:
    """Resolve one file or a directory batch and reject every output collision up front."""
    is_directory = raw_path.is_dir()
    if is_directory:
        if output_path is None:
            raise ValueError("A raw directory requires --recover-output with a directory path")
        if (output_path.exists() or output_path.is_symlink()) and not output_path.is_dir():
            raise NotADirectoryError(f"Recovery output must be a directory: {output_path}")
        files = sorted(path for path in raw_path.iterdir()
                       if path.is_file() and path.suffix == ".raw")
        if not files:
            raise FileNotFoundError(f"No .raw files found in {raw_path}")
        jobs = [(path, output_path / path.name) for path in files]
    elif raw_path.is_file():
        if output_path is not None and output_path.is_dir():
            raise IsADirectoryError(f"Recovery output must be a filename: {output_path}")
        jobs = [(raw_path, output_path)]
    else:
        raise FileNotFoundError(f"Raw input not found: {raw_path}")

    for source, target in jobs:
        if target is None:
            continue
        if source.resolve() == target.resolve():
            raise ValueError(f"Recovery output would overwrite its input: {source}")
        candidates = [target]
        if audit:
            candidates.append(target.with_name(target.name + ".audit.json"))
        if figures:
            candidates.extend(target.with_name(f"{target.stem}.{variable}.{state}.html")
                              for variable in ("Es", "Lt", "Li") for state in ("light", "dark"))
        collisions = [path for path in candidates if path.exists() or path.is_symlink()]
        if collisions:
            raise FileExistsError("Output already exists: " + ", ".join(str(path) for path in collisions))
    return jobs, is_directory


def main() -> None:
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("raw", type=Path, help="One pySAS .raw file or a directory of .raw files")
    arg.add_argument("calibration", type=Path, help="Directory of matching .cal and .tdf files")
    arg.add_argument("--bucket-minutes", type=int,
                     help="Include optional UTC time-bucket counts at this interval (minutes)")
    arg.add_argument("--json", action="store_true", help="Print machine-readable report to stdout")
    arg.add_argument("--recover-output", type=Path,
                     help="Output filename for one raw file, or output directory for a raw directory")
    arg.add_argument("--audit", action="store_true",
                     help="Write a detailed .audit.json file beside each recovered output")
    arg.add_argument("--no-stitch-fragments", action="store_false", dest="stitch_fragments",
                     help="Skip checksum-validated spectral reassembly across interleaved logger chunks")
    arg.add_argument("--figures", action="store_true",
                     help="Write six Es/Lt/Li light/dark Plotly HTML figures beside the recovered file")
    args = arg.parse_args()
    if args.bucket_minutes is not None and (not 1 <= args.bucket_minutes <= 60 or 60 % args.bucket_minutes):
        arg.error("--bucket-minutes must divide 60 and be between 1 and 60")
    if not args.stitch_fragments and not args.recover_output:
        arg.error("--no-stitch-fragments requires --recover-output")
    if args.audit and not args.recover_output:
        arg.error("--audit requires --recover-output")
    jobs, is_directory = plan_inputs(args.raw, args.recover_output, args.figures, args.audit)
    results = []
    for source, target in jobs:
        report = inspect(source, args.calibration, args.bucket_minutes)
        recovery, provenance = (recover(source, args.calibration, target, report,
                                        args.stitch_fragments, args.audit)
                                if target is not None else (None, None))
        figures = (plot_spectra(target or source, args.calibration, provenance)
                   if args.figures else None)
        result = {"input": str(source), "inspection": report,
                  "recovery": recovery, "figures": figures}
        results.append(result)
        if not args.json and is_directory:
            byte_stats = recovery["byte_statistics"]
            frame_counts = recovery["counts"]
            print(f"{source.name} -> {target}: "
                  f"{frame_counts.get('original_valid', 0) + frame_counts.get('recovered', 0):,} frames, "
                  f"{byte_stats['valid']} valid of {byte_stats['total']} "
                  f"({byte_stats['recovered_percent']:.2f}%)")
            if args.bucket_minutes is not None:
                print_report(report)

    if args.json:
        if is_directory:
            print(json.dumps({"files": results}, indent=2))
        else:
            print(json.dumps({key: value for key, value in results[0].items() if key != "input"}, indent=2))
    elif not is_directory:
        result = results[0]
        print_report(result["inspection"])
        if result["recovery"]:
            print("\nRecovery output:")
            print(json.dumps(result["recovery"], indent=2))
        if result["figures"]:
            print("\nSpectrum figures:")
            for item in result["figures"]:
                print(f"  {item['variable']} {item['state']}: {item['path']} "
                      f"({item['valid']:,} valid, {item['recovered']:,} recovered)")


if __name__ == "__main__":
    main()
