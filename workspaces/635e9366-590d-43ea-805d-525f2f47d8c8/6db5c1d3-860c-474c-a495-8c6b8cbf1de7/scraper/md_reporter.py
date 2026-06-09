#!/usr/bin/env python3
"""
Markdown Test Reporter — Generate structured Markdown reports from test results.

Usage:
    from md_reporter import write_test_report
    write_test_report(results, 'test_report.md')

CLI:
    python3 md_reporter.py --test-results results.json report.md
    python3 md_reporter.py --discover tests/ report.md
    python3 md_reporter.py --coverage coverage.json report.md
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime


def format_duration(seconds):
    """Format a duration in seconds to a human-readable string."""
    if seconds is None:
        return "0.0ms"
    if seconds < 0:
        return f"-{format_duration(-seconds)}"
    if seconds < 0.001:
        return f"{seconds * 1000:.1f}ms"
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    return f"{int(seconds // 60)}m {int(seconds % 60)}s"


def collect_test_results(test_runner_result):
    """
    Collect test results from a unittest.TestResult or unittest.TestRunner result.
    
    Args:
        test_runner_result: A TestResult object or tuple (result, output)
        
    Returns:
        dict with keys: total, passed, failed, errors, skipped, duration, tests
    """
    # Handle different return types from test runners
    result = test_runner_result
    if isinstance(test_runner_result, tuple) and len(test_runner_result) >= 2:
        result = test_runner_result[0]

    # Extract result info
    result_info = {
        'total': result.testsRun,
        'passed': result.testsRun - len(result.failures) - len(result.errors),
        'failures': len(result.failures),
        'errors': len(result.errors),
        'skipped': len(result.skipped),
        'duration': getattr(result, 'duration', 0),
        'tests': [],
    }

    for test, traceback in result.failures:
        result_info['tests'].append({
            'name': str(test),
            'status': 'FAIL',
            'traceback': traceback,
        })

    for test, traceback in result.errors:
        result_info['tests'].append({
            'name': str(test),
            'status': 'ERROR',
            'traceback': traceback,
        })

    for test, reason in getattr(result, 'skipped', []):
        result_info['tests'].append({
            'name': str(test),
            'status': 'SKIPPED',
            'reason': reason,
        })

    return result_info


def write_test_report(results, filename, title=None, config=None):
    """
    Generate a structured Markdown test report file.
    
    Args:
        results: dict from collect_test_results(), or a TestResult object
        filename: Output .md file path
        title: Optional report title (default: auto-generated)
        config: Optional dict with extra metadata (version, description, etc.)
    
    Returns:
        Path to the generated report file
    """
    # Accept raw TestResult objects too
    if hasattr(results, 'testsRun'):
        results = collect_test_results(results)

    title = title or f"Test Report — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    lines = []
    
    # Header
    lines.append(f"# {title}")
    lines.append("")

    # Configuration metadata
    if config:
        lines.append("## Configuration")
        lines.append("")
        lines.append("| Key | Value |")
        lines.append("| --- | --- |")
        for k, v in config.items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    total = results['total']
    passed = results['passed']
    failures = results['failures']
    errors = results['errors']
    skipped = results['skipped']
    duration = format_duration(results.get('duration', 0))

    pass_rate = (passed / total * 100) if total > 0 else 0

    lines.append(f"- **Total tests**: {total}")
    lines.append(f"- **Passed**: {passed} ({pass_rate:.1f}%)")
    lines.append(f"- **Failed**: {failures}")
    lines.append(f"- **Errors**: {errors}")
    lines.append(f"- **Skipped**: {skipped}")
    lines.append(f"- **Duration**: {duration}")
    lines.append("")

    # Status badge
    if failures > 0 or errors > 0:
        lines.append(f"![Status](https://img.shields.io/badge/status-{failures + errors}_failing-red)")
    elif total > 0:
        lines.append(f"![Status](https://img.shields.io/badge/status-all_passing-brightgreen)")
    lines.append("")

    # Detailed results table
    if results.get('tests'):
        lines.append("## Test Details")
        lines.append("")
        lines.append("| # | Test | Status | Detail |")
        lines.append("| --- | --- | --- | --- |")
        for i, t in enumerate(results['tests'], 1):
            status = t['status']
            # Emoji status
            if status == 'FAIL':
                icon = '❌'
            elif status == 'ERROR':
                icon = '💥'
            elif status == 'SKIPPED':
                icon = '⏭️'
            else:
                icon = '✅'

            detail = ''
            if status in ('FAIL', 'ERROR'):
                tb = t.get('traceback', '')
                # Take first meaningful line of traceback
                for line in tb.split('\n'):
                    line = line.strip()
                    if line and 'Traceback' not in line and 'File' not in line:
                        detail = line[:80]
                        break
                if not detail:
                    detail = '(see traceback below)'
            elif status == 'SKIPPED':
                detail = t.get('reason', '')
            
            lines.append(f"| {i} | `{t['name']}` | {icon} {status} | {detail} |")
        lines.append("")

    # Failure details with collapsible sections
    has_failures = [t for t in results.get('tests', []) if t['status'] in ('FAIL', 'ERROR')]
    if has_failures:
        lines.append("## Failure Details")
        lines.append("")
        for t in has_failures:
            lines.append(f"<details>")
            lines.append(f"<summary><strong>{t['status']}</strong>: {t['name']}</summary>")
            lines.append("")
            lines.append("```")
            traceback = t.get('traceback', 'No traceback captured')
            lines.append(traceback[:2000])  # Truncate very long tracebacks
            lines.append("```")
            lines.append("")
            lines.append("</details>")
            lines.append("")

    # Timestamp footer
    lines.append("---")
    lines.append(f"*Report generated: {datetime.now().isoformat()}*")
    lines.append("")

    content = '\n'.join(lines)

    # Create parent directory if needed
    parent = os.path.dirname(filename)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"  📝 Test report written: {filename} ({len(content)} bytes)")
    return filename


def write_coverage_report(coverage_data, filename):
    """
    Generate a Markdown coverage report.
    
    Args:
        coverage_data: dict with keys mapping to coverage percentages
                       e.g. {'statement': 85.0, 'branch': 72.5}
        filename: Output .md file path
    
    Returns:
        Path to the generated report file
    """
    lines = []
    lines.append("# Coverage Report")
    lines.append("")
    lines.append("| Metric | Coverage | Status |")
    lines.append("| --- | --- | --- |")
    
    for metric, value in coverage_data.items():
        if isinstance(value, (int, float)):
            bar_len = 20
            filled = int(value / 100 * bar_len)
            bar = '█' * filled + '░' * (bar_len - filled)
            status = '✅' if value >= 80 else ('⚠️' if value >= 50 else '❌')
            lines.append(f"| {metric} | {value:.1f}% {bar} | {status} |")
    
    lines.append("")
    lines.append("---")
    lines.append(f"*Report generated: {datetime.now().isoformat()}*")
    lines.append("")

    content = '\n'.join(lines)
    
    parent = os.path.dirname(filename)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"  📊 Coverage report written: {filename} ({len(content)} bytes)")
    return filename



# ---------------------------------------------------------------------------
# NEW FEATURE: Combined Dashboard Report
# ---------------------------------------------------------------------------

def write_dashboard_report(test_results, coverage_data, filename, title=None, config=None):
    """
    Generate a combined Markdown dashboard with test results AND coverage data.

    Produces a single-page report with summary cards, coverage detail, test
    details table, and collapsible failure sections — suitable for CI artifacts
    or project documentation.

    Args:
        test_results: dict from collect_test_results(), or a TestResult object
        coverage_data: dict with coverage metric -> percentage (float 0-100)
        filename: Output .md file path
        title: Optional report title (default: auto-generated)
        config: Optional dict with extra metadata

    Returns:
        Path to the generated dashboard file
    """
    if hasattr(test_results, 'testsRun'):
        test_results = collect_test_results(test_results)

    title = title or f"Project Dashboard \u2014 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    lines = []
    lines.append(f"# {title}")
    lines.append("")

    # Configuration metadata
    if config:
        lines.append("## Configuration")
        lines.append("")
        lines.append("| Key | Value |")
        lines.append("| --- | --- |")
        for k, v in config.items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

    # Summary section
    lines.append("## Summary")
    lines.append("")

    total = test_results['total']
    passed = test_results['passed']
    failures = test_results['failures']
    errors = test_results['errors']
    skipped = test_results['skipped']
    duration = format_duration(test_results.get('duration', 0))
    pass_rate = (passed / total * 100) if total > 0 else 0

    # Summary cards in a table layout
    lines.append('<table>')
    lines.append('<tr>')
    lines.append(f'<td align="center"><strong>\U0001f9ea Tests</strong><br/>{total}</td>')
    lines.append(f'<td align="center"><strong>\u2705 Passed</strong><br/>{passed} ({pass_rate:.1f}%)</td>')
    lines.append(f'<td align="center"><strong>\u274c Failed</strong><br/>{failures}</td>')
    lines.append(f'<td align="center"><strong>\U0001f4a5 Errors</strong><br/>{errors}</td>')
    lines.append(f'<td align="center"><strong>\u23ed\ufe0f Skipped</strong><br/>{skipped}</td>')
    lines.append(f'<td align="center"><strong>\u23f1\ufe0f Duration</strong><br/>{duration}</td>')
    lines.append('</tr>')
    lines.append('</table>')
    lines.append("")

    # Coverage cards
    if coverage_data:
        lines.append('<table>')
        lines.append('<tr>')
        for metric, value in coverage_data.items():
            if isinstance(value, (int, float)):
                icon = '\u2705' if value >= 80 else ('\u26a0\ufe0f' if value >= 50 else '\u274c')
                lines.append(
                    f'<td align="center"><strong>{icon} {metric}</strong><br/>{value:.1f}%</td>'
                )
        lines.append('</tr>')
        lines.append('</table>')
        lines.append("")

    # Status badge
    if failures > 0 or errors > 0:
        lines.append(f"![Status](https://img.shields.io/badge/status-{failures + errors}_failing-red)")
    elif total > 0:
        lines.append(f"![Status](https://img.shields.io/badge/status-all_passing-brightgreen)")
    lines.append("")

    # Coverage detail table
    if coverage_data:
        lines.append("## Coverage Detail")
        lines.append("")
        lines.append("| Metric | Coverage | Status |")
        lines.append("| --- | --- | --- |")
        for metric, value in coverage_data.items():
            if isinstance(value, (int, float)):
                bar_len = 20
                filled = int(value / 100 * bar_len)
                bar = '\u2588' * filled + '\u2591' * (bar_len - filled)
                status = '\u2705' if value >= 80 else ('\u26a0\ufe0f' if value >= 50 else '\u274c')
                lines.append(f"| {metric} | {value:.1f}% {bar} | {status} |")
        lines.append("")

    # Test detail table
    if test_results.get('tests'):
        lines.append("## Test Details")
        lines.append("")
        lines.append("| # | Test | Status | Detail |")
        lines.append("| --- | --- | --- | --- |")
        for i, t in enumerate(test_results['tests'], 1):
            status = t['status']
            if status == 'FAIL':
                icon = '\u274c'
            elif status == 'ERROR':
                icon = '\U0001f4a5'
            elif status == 'SKIPPED':
                icon = '\u23ed\ufe0f'
            else:
                icon = '\u2705'

            detail = ''
            if status in ('FAIL', 'ERROR'):
                tb = t.get('traceback', '')
                for line in tb.split('\n'):
                    line = line.strip()
                    if line and 'Traceback' not in line and 'File' not in line:
                        detail = line[:80]
                        break
                if not detail:
                    detail = '(see traceback below)'
            elif status == 'SKIPPED':
                detail = t.get('reason', '')

            lines.append(f"| {i} | `{t['name']}` | {icon} {status} | {detail} |")
        lines.append("")

    # Failure details (collapsible)
    has_failures = [t for t in test_results.get('tests', []) if t['status'] in ('FAIL', 'ERROR')]
    if has_failures:
        lines.append("## Failure Details")
        lines.append("")
        for t in has_failures:
            lines.append(f"<details>")
            lines.append(f"<summary><strong>{t['status']}</strong>: {t['name']}</summary>")
            lines.append("")
            lines.append("```")
            traceback = t.get('traceback', 'No traceback captured')
            lines.append(traceback[:2000])
            lines.append("```")
            lines.append("")
            lines.append("</details>")
            lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Dashboard generated: {datetime.now().isoformat()}*")
    lines.append("")

    content = '\n'.join(lines)

    parent = os.path.dirname(filename)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"  \U0001f4ca Dashboard report written: {filename} ({len(content)} bytes)")
    return filename


# ---------------------------------------------------------------------------
# NEW FEATURE: MarkdownSummary context manager
# ---------------------------------------------------------------------------

from contextlib import contextmanager


@contextmanager
def MarkdownSummary(filename, title=None, config=None):
    """
    Context manager for building a Markdown report step by step.

    Yields a builder object with .add_section(), .add_table(), .add_code_block()
    and .add_line() methods. Writes the file on exit.

    Usage:
        with MarkdownSummary('report.md', title='My Report') as report:
            report.add_section('Results', 'All tests passed.')
            report.add_table(['Name', 'Status'], [['test_a', 'PASS']])
    """
    class ReportBuilder:
        def __init__(self):
            self.lines = []
            if title:
                self.lines.append(f"# {title}")
                self.lines.append("")
            if config:
                self.lines.append("## Configuration")
                self.lines.append("")
                self.lines.append("| Key | Value |")
                self.lines.append("| --- | --- |")
                for k, v in config.items():
                    self.lines.append(f"| {k} | {v} |")
                self.lines.append("")

        def add_section(self, heading, body=None):
            """Add a section with optional body text."""
            self.lines.append(f"## {heading}")
            self.lines.append("")
            if body:
                self.lines.append(body)
                self.lines.append("")
            return self

        def add_line(self, text):
            """Add a single line of text."""
            self.lines.append(text)
            return self

        def add_table(self, headers, rows):
            """Add a Markdown table with headers and row data."""
            self.lines.append("| " + " | ".join(headers) + " |")
            self.lines.append("| " + " | ".join("---" for _ in headers) + " |")
            for row in rows:
                safe_row = [str(cell).replace("|", "\|") for cell in row]
                self.lines.append("| " + " | ".join(safe_row) + " |")
            self.lines.append("")
            return self

        def add_code_block(self, code, language=""):
            """Add a fenced code block."""
            self.lines.append(f"```{language}")
            self.lines.append(code)
            self.lines.append("```")
            self.lines.append("")
            return self

        def add_raw(self, text):
            """Add raw markdown text."""
            self.lines.append(text)
            return self

    builder = ReportBuilder()
    yield builder

    content = '\n'.join(builder.lines)

    parent = os.path.dirname(filename)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"  \U0001f4dd Markdown summary written: {filename} ({len(content)} bytes)")
def load_results_from_json(path):
    """Load test results from a JSON file."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def discover_and_run_tests(paths, pattern='test_*.py'):
    """
    Discover and run tests from given paths using unittest.
    
    Args:
        paths: List of directory/file paths to discover
        pattern: Test file pattern (default: test_*.py)
    
    Returns:
        Dict of test results (compatible with write_test_report)
    """
    import unittest
    import io

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for p in paths:
        if os.path.isfile(p) and p.endswith('.py'):
            # Load a single test file
            loader = unittest.TestLoader()
            try:
                # Import the module
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    os.path.splitext(os.path.basename(p))[0], p
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    # Find tests in the module
                    module_suite = loader.loadTestsFromModule(mod)
                    suite.addTest(module_suite)
            except Exception as e:
                print(f"  ⚠️  Could not load {p}: {e}")
        elif os.path.isdir(p):
            # Discover tests in directory
            discovered = loader.discover(p, pattern=pattern)
            suite.addTest(discovered)

    # Run the suite
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=0)
    t0 = time.time()
    result = runner.run(suite)
    elapsed = time.time() - t0

    # Collect results
    collected = collect_test_results(result)
    collected['duration'] = elapsed

    # Print summary to stderr
    print(f"\n  Test run: {collected['total']} tests, "
          f"{collected['passed']} passed, "
          f"{collected['failures']} failed, "
          f"{collected['errors']} errors, "
          f"{collected['skipped']} skipped "
          f"({format_duration(elapsed)})",
          file=sys.stderr)

    return collected


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Generate Markdown test/coverage reports',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --test-results results.json report.md
  %(prog)s --discover tests/ report.md
  %(prog)s --discover test_md_reporter.py report.md
  %(prog)s --coverage coverage.json coverage.md
        """
    )

    parser.add_argument('output', help='Output Markdown file path')

    # Mutually exclusive input sources
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        '--test-results', '-t', metavar='FILE',
        help='Load test results from a JSON file'
    )
    input_group.add_argument(
        '--discover', '-d', metavar='PATH', nargs='+',
        help='Discover and run tests from path(s)'
    )
    input_group.add_argument(
        '--coverage', '-c', metavar='FILE',
        help='Load coverage data from a JSON file'
    )

    parser.add_argument(
        '--title', '-T',
        help='Custom report title'
    )
    parser.add_argument(
        '--config', '-C', metavar='FILE',
        help='JSON config file with metadata for the report'
    )
    parser.add_argument(
        '--pattern', '-p', default='test_*.py',
        help='Test file pattern for discovery (default: test_*.py)'
    )

    return parser.parse_args(argv)


def main(argv=None):
    """CLI entry point."""
    args = parse_args(argv)

    # Load optional config
    config = None
    if args.config:
        if os.path.exists(args.config):
            with open(args.config, 'r', encoding='utf-8') as f:
                config = json.load(f)
            print(f"  📋 Loaded config from {args.config}")
        else:
            print(f"  ⚠️  Config file not found: {args.config}")

    if args.test_results:
        # Generate test report from JSON
        if not os.path.exists(args.test_results):
            print(f"  ❌ Test results file not found: {args.test_results}")
            return 1
        results = load_results_from_json(args.test_results)
        write_test_report(results, args.output, title=args.title, config=config)
        return 0

    elif args.discover:
        # Discover, run tests, and generate report
        collected = discover_and_run_tests(args.discover, pattern=args.pattern)
        write_test_report(collected, args.output, title=args.title, config=config)
        return 0

    elif args.coverage:
        # Generate coverage report from JSON
        if not os.path.exists(args.coverage):
            print(f"  ❌ Coverage file not found: {args.coverage}")
            return 1
        with open(args.coverage, 'r', encoding='utf-8') as f:
            coverage_data = json.load(f)
        write_coverage_report(coverage_data, args.output)
        return 0

    return 0


if __name__ == '__main__':
    if len(sys.argv) > 1:
        sys.exit(main())
    # Demo: generate a sample report
    sample_results = {
        'total': 18,
        'passed': 16,
        'failures': 1,
        'errors': 1,
        'skipped': 0,
        'duration': 0.345,
        'tests': [
            {
                'name': 'test_csv_creates_file (test_scraper.TestDataExporter)',
                'status': 'PASS'
            },
            {
                'name': 'test_rate_limit_enforces_minimum_delay (test_scraper.TestRateLimit)',
                'status': 'FAIL',
                'traceback': 'AssertionError: 0.089 < 0.08'
            },
            {
                'name': 'test_json_creates_valid_file (test_scraper.TestDataExporter)',
                'status': 'ERROR',
                'traceback': 'json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)'
            },
        ]
    }

    write_test_report(sample_results, 'demo_test_report.md', config={
        'version': '1.0.0',
        'suite': 'scraper tests',
    })
    write_coverage_report({'statement': 87.5, 'branch': 71.2}, 'demo_coverage_report.md')
    print("\n✅ Demo reports generated. Open the .md files to view.")
